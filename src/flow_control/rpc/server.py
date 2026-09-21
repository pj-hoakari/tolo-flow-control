from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from connectrpc._protocol import _error_to_http_status
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext
from hypercorn.typing import (
    ASGIFramework,
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    ASGISendEvent,
    Scope,
)

from ..service.handler import handle_request
from ..service.messages import Response
from .auth import (
    AuthConfigurationError,
    AuthenticationError,
    AuthorizationError,
    CloudRunAuthenticator,
    create_authenticator,
    parse_workload_authorization,
)
from .codec import decode_request, encode_response
from .generated.tolo.flow.v1.flow_pb2 import OptimizeRequest, OptimizeResponse

LOGGER = logging.getLogger("flow_control.rpc")
RPC_PATH = "/tolo.flow.v1.FlowControlService/Optimize"
DEFAULT_MAX_REQUEST_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_EXECUTION_SEC = 720.0
_ARRIVAL_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "flow_control_arrival_deadline", default=None
)
T = TypeVar("T")


@dataclass(frozen=True)
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 8080
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_execution_sec: float = DEFAULT_MAX_EXECUTION_SEC

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServerSettings:
        values = env if env is not None else os.environ
        port = _positive_int(values.get("PORT", "8080"), "PORT", maximum=65535)
        max_bytes = _positive_int(
            values.get("TOLO_RPC_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES)),
            "TOLO_RPC_MAX_REQUEST_BYTES",
        )
        max_execution = _positive_float(
            values.get("TOLO_RPC_MAX_EXECUTION_SEC", str(DEFAULT_MAX_EXECUTION_SEC)),
            "TOLO_RPC_MAX_EXECUTION_SEC",
        )
        return cls(port=port, max_request_bytes=max_bytes, max_execution_sec=max_execution)


class _ExecutionPool:
    def __init__(self) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="flow-control"
        )
        self._slot = threading.Lock()
        self._closed = False

    def submit(self, function: Callable[[], T]) -> concurrent.futures.Future[T]:
        if self._closed or not self._slot.acquire(blocking=False):
            raise RuntimeError("optimization capacity exhausted")

        def run() -> T:
            try:
                return function()
            finally:
                self._slot.release()

        try:
            return self._executor.submit(run)
        except BaseException:
            self._slot.release()
            raise

    def shutdown(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)


class FlowControlService:
    def __init__(
        self,
        pool: _ExecutionPool,
        max_execution_sec: float,
    ) -> None:
        self._pool = pool
        self._max_execution_sec = max_execution_sec

    async def optimize(
        self, request: OptimizeRequest, ctx: RequestContext[OptimizeRequest, OptimizeResponse]
    ) -> OptimizeResponse:
        started = time.monotonic()
        transport_deadline = _transport_deadline(ctx)
        arrival_deadline = _ARRIVAL_DEADLINE.get()
        service_deadline = arrival_deadline or started + self._max_execution_sec
        deadline = min(
            transport_deadline if transport_deadline is not None else float("inf"), service_deadline
        )
        if deadline <= started:
            raise _connect_error("deadline_exceeded", "request deadline exceeded")

        try:
            future = self._pool.submit(lambda: self._run(request, deadline))
        except RuntimeError as exc:
            if str(exc) == "optimization capacity exhausted":
                raise _connect_error(
                    "resource_exhausted", "optimization capacity exhausted"
                ) from exc
            raise _connect_error("unavailable", "optimization executor unavailable") from exc

        future.add_done_callback(_consume_future_exception)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(_consume_asyncio_exception)
        timeout = max(0.0, deadline - time.monotonic())
        try:
            response = await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)
        except TimeoutError as exc:
            LOGGER.info(
                json.dumps(
                    {
                        "event": "rpc_finished",
                        "result": "deadline_exceeded",
                        "elapsed_ms": _elapsed(started),
                    },
                    separators=(",", ":"),
                )
            )
            raise _connect_error("deadline_exceeded", "request deadline exceeded") from exc
        except asyncio.CancelledError as exc:
            LOGGER.info(
                json.dumps(
                    {
                        "event": "rpc_finished",
                        "result": "canceled",
                        "elapsed_ms": _elapsed(started),
                    },
                    separators=(",", ":"),
                )
            )
            raise _connect_error("canceled", "request canceled") from exc
        except _DecodeFailureError as exc:
            raise _connect_error("invalid_argument", "invalid optimization request") from exc
        except Exception as exc:
            LOGGER.exception("optimization worker failed")
            raise _connect_error("internal", "optimization failed") from exc

        try:
            encoded = encode_response(response)
        except ValueError as exc:
            raise _connect_error("internal", "optimization response encoding failed") from exc
        request_id = response.request_id
        verdict = response.verdict.value
        LOGGER.info(
            json.dumps(
                {
                    "event": "rpc_finished",
                    "request_id": request_id,
                    "event_id": request.event_id,
                    "verdict": verdict,
                    "elapsed_ms": _elapsed(started),
                },
                separators=(",", ":"),
            )
        )
        return encoded

    def _run(self, request: OptimizeRequest, deadline: float) -> Response:
        try:
            domain_request = decode_request(request)
        except ValueError as exc:
            raise _DecodeFailureError from exc
        return handle_request(domain_request, deadline=deadline)


def create_app(
    *,
    settings: ServerSettings | None = None,
    authenticator: CloudRunAuthenticator | None = None,
) -> ASGIFramework:
    selected_settings = settings or ServerSettings.from_env()
    selected_auth = authenticator or create_authenticator()
    pool = _ExecutionPool()
    service = FlowControlService(pool, selected_settings.max_execution_sec)
    generated = _load_generated_app(service, selected_settings.max_request_bytes)

    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        scope_type = scope["type"]
        if scope_type == "lifespan":
            await _lifespan(scope, receive, send, selected_auth, pool)
            return
        if scope_type != "http":
            if scope_type == "websocket":
                await send(
                    cast(ASGISendEvent, cast(object, {"type": "websocket.close", "code": 1000}))
                )
            return
        path = _canonical_path(scope)
        if path == "/livez":
            await _send_json(send, 200, {"status": "ok"})
            return
        if path == "/readyz":
            if not selected_auth.ready:
                with suppress(Exception):
                    await asyncio.to_thread(selected_auth.refresh)
            status = 200 if selected_auth.ready else 503
            await _send_json(send, status, {"status": "ready" if status == 200 else "not_ready"})
            return
        if path != RPC_PATH:
            await _send_connect_error(send, "not_found", "not found")
            return
        await _authenticated_request(
            scope,
            receive,
            send,
            generated,
            selected_auth,
            selected_settings.max_request_bytes,
            selected_settings.max_execution_sec,
        )

    return app


async def _authenticated_request(
    scope: Scope,
    receive: ASGIReceiveCallable,
    send: ASGISendCallable,
    generated: ASGIFramework,
    authenticator: CloudRunAuthenticator,
    max_request_bytes: int,
    max_execution_sec: float,
) -> None:
    headers = list(scope["headers"]) if scope["type"] == "http" else []
    try:
        arrival_deadline = _request_deadline(headers, max_execution_sec)
    except _InvalidTimeoutError:
        await _send_connect_error(send, "invalid_argument", "invalid request timeout")
        return
    if arrival_deadline <= time.monotonic():
        await _send_connect_error(send, "deadline_exceeded", "request deadline exceeded")
        return
    deadline_token = _ARRIVAL_DEADLINE.set(arrival_deadline)
    try:
        await _authenticated_request_inner(
            scope,
            receive,
            send,
            generated,
            authenticator,
            max_request_bytes,
            arrival_deadline,
            headers,
        )
    finally:
        _ARRIVAL_DEADLINE.reset(deadline_token)


async def _authenticated_request_inner(
    scope: Scope,
    receive: ASGIReceiveCallable,
    send: ASGISendCallable,
    generated: ASGIFramework,
    authenticator: CloudRunAuthenticator,
    max_request_bytes: int,
    arrival_deadline: float,
    headers: list[tuple[bytes, bytes]],
) -> None:
    if _duplicate_credentials(headers):
        await _send_connect_error(send, "unauthenticated", "invalid workload authorization")
        return
    try:
        token = parse_workload_authorization(headers)
        await asyncio.wait_for(
            asyncio.to_thread(authenticator.authenticate, token),
            timeout=_remaining(arrival_deadline),
        )
    except TimeoutError:
        await _send_connect_error(send, "deadline_exceeded", "request deadline exceeded")
        return
    except AuthorizationError:
        await _send_connect_error(send, "permission_denied", "workload principal is not allowed")
        return
    except (AuthenticationError, AuthConfigurationError):
        await _send_connect_error(send, "unauthenticated", "workload authentication failed")
        return
    try:
        body = await asyncio.wait_for(
            _read_body(receive, max_request_bytes), timeout=_remaining(arrival_deadline)
        )
    except TimeoutError:
        await _send_connect_error(send, "deadline_exceeded", "request deadline exceeded")
        return
    except _BodyTooLargeError:
        await _send_connect_error(send, "resource_exhausted", "request body is too large")
        return
    except _ClientDisconnectedError:
        return

    sent = False
    receive_lock = asyncio.Lock()

    async def replay() -> ASGIReceiveEvent:
        nonlocal sent
        if not sent:
            sent = True
            return cast(
                ASGIReceiveEvent,
                cast(object, {"type": "http.request", "body": body, "more_body": False}),
            )
        async with receive_lock:
            return await receive()

    generated_task = asyncio.ensure_future(generated(scope, replay, send))
    disconnect_task = asyncio.create_task(_wait_for_disconnect(receive, receive_lock))
    try:
        done, _ = await asyncio.wait(
            (generated_task, disconnect_task), return_when=asyncio.FIRST_COMPLETED
        )
        if generated_task in done:
            await generated_task
        elif not disconnect_task.cancelled():
            disconnect_error = disconnect_task.exception()
            if disconnect_error is not None:
                raise disconnect_error
            if disconnect_task.result():
                generated_task.cancel()
                with suppress(asyncio.CancelledError):
                    await generated_task
    finally:
        for task in (generated_task, disconnect_task):
            if not task.done():
                task.cancel()
        _ = await asyncio.gather(generated_task, disconnect_task, return_exceptions=True)


async def _lifespan(
    scope: Scope,
    receive: ASGIReceiveCallable,
    send: ASGISendCallable,
    authenticator: CloudRunAuthenticator,
    pool: _ExecutionPool,
) -> None:
    del scope
    while True:
        message = await receive()
        if message.get("type") == "lifespan.startup":
            try:
                await asyncio.to_thread(authenticator.refresh)
            except Exception:
                LOGGER.exception("workload trust initialization failed")
            await send({"type": "lifespan.startup.complete"})
        elif message.get("type") == "lifespan.shutdown":
            await asyncio.to_thread(pool.shutdown)
            await send({"type": "lifespan.shutdown.complete"})
            return


def _load_generated_app(service: FlowControlService, max_request_bytes: int) -> ASGIFramework:
    from .generated.tolo.flow.v1.flow_connect import FlowControlServiceASGIApplication

    return cast(
        ASGIFramework,
        FlowControlServiceASGIApplication(
            service, read_max_bytes=max_request_bytes, compressions=()
        ),
    )


def main() -> None:
    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    settings = ServerSettings.from_env()
    config = Config()
    config.bind = [f"{settings.host}:{settings.port}"]
    asyncio.run(serve(create_app(settings=settings), config))


def _transport_deadline(ctx: RequestContext[OptimizeRequest, OptimizeResponse]) -> float | None:
    if ctx.timeout_ms is None:
        return None
    return time.monotonic() + max(0.0, ctx.timeout_ms / 1000.0)


def _canonical_path(scope: Scope) -> str:
    if scope["type"] == "lifespan":
        return ""
    path = scope["path"]
    root_path = scope["root_path"]
    if root_path:
        return path.removeprefix(root_path)
    return path


def _request_deadline(headers: list[tuple[bytes, bytes]], max_execution_sec: float) -> float:
    values = [value for key, value in headers if key.lower() == b"connect-timeout-ms"]
    if len(values) > 1:
        raise _InvalidTimeoutError
    started = time.monotonic()
    deadline = started + max_execution_sec
    if not values:
        return deadline
    try:
        value = values[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise _InvalidTimeoutError from exc
    if not value.isdecimal():
        raise _InvalidTimeoutError
    try:
        timeout_ms = int(value)
    except ValueError as exc:
        raise _InvalidTimeoutError from exc
    return min(deadline, started + timeout_ms / 1000.0)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


async def _read_body(receive: ASGIReceiveCallable, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            raise _ClientDisconnectedError
        if message.get("type") != "http.request":
            continue
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            raise _BodyTooLargeError
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def _duplicate_credentials(headers: list[tuple[bytes, bytes]]) -> bool:
    counts: dict[bytes, int] = {}
    for key, _ in headers:
        lowered = key.lower()
        if lowered in {
            b"workload-authorization",
            b"authorization",
            b"x-serverless-authorization",
        }:
            counts[lowered] = counts.get(lowered, 0) + 1
    return any(count > 1 for count in counts.values())


async def _wait_for_disconnect(receive: ASGIReceiveCallable, receive_lock: asyncio.Lock) -> bool:
    while True:
        async with receive_lock:
            message = await receive()
        if message.get("type") == "http.disconnect":
            return True


def _consume_future_exception(future: concurrent.futures.Future[Any]) -> None:
    with suppress(concurrent.futures.CancelledError):
        future.exception()


def _consume_asyncio_exception(future: asyncio.Future[Any]) -> None:
    with suppress(asyncio.CancelledError):
        future.exception()


async def _send_json(send: ASGISendCallable, status: int, value: object) -> None:
    body = json.dumps(value, separators=(",", ":")).encode("utf-8")
    await send(
        cast(
            ASGISendEvent,
            cast(
                object,
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": (
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                    ),
                },
            ),
        )
    )
    await send(
        cast(
            ASGISendEvent,
            cast(object, {"type": "http.response.body", "body": body, "more_body": False}),
        )
    )


async def _send_connect_error(send: ASGISendCallable, code: str, message: str) -> None:
    status = _error_to_http_status[Code[code.upper()]].code
    await _send_json(send, status, {"code": code, "message": message})


def _connect_error(code: str, message: str) -> Exception:
    return ConnectError(Code[code.upper()], message)


def _positive_int(value: str, name: str, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AuthConfigurationError(name) from exc
    if parsed <= 0 or (maximum is not None and parsed > maximum):
        raise AuthConfigurationError(name)
    return parsed


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AuthConfigurationError(name) from exc
    if parsed <= 0 or not parsed < float("inf"):
        raise AuthConfigurationError(name)
    return parsed


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class _BodyTooLargeError(Exception):
    pass


class _ClientDisconnectedError(Exception):
    pass


class _DecodeFailureError(Exception):
    pass


class _InvalidTimeoutError(Exception):
    pass
