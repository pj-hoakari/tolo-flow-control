from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import TypeVar, cast

import grpc
from grpc_health.v1 import health, health_pb2_grpc

from ..service.handler import handle_request
from ..service.messages import Response
from .codec import decode_request, encode_response
from .generated.tolo.flow.v1.flow_pb2 import OptimizeRequest, OptimizeResponse

LOGGER = logging.getLogger("flow_control.rpc")
SERVICE_NAME = "tolo.flow.v1.FlowControlService"
DEFAULT_MAX_REQUEST_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_EXECUTION_SEC = 720.0
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
        self._executor: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow-control")
        )
        self._slot: threading.Lock = threading.Lock()
        self._closed: bool = False

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
        self._pool: _ExecutionPool = pool
        self._max_execution_sec: float = max_execution_sec

    async def optimize(
        self,
        request: OptimizeRequest,
        context: grpc.aio.ServicerContext[OptimizeRequest, OptimizeResponse],
    ) -> OptimizeResponse:
        started = time.monotonic()
        time_remaining = cast(float | None, context.time_remaining())
        deadline = started + min(
            time_remaining if time_remaining is not None else float("inf"),
            self._max_execution_sec,
        )
        if deadline <= started:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "request deadline exceeded")

        try:
            future = self._pool.submit(lambda: self._run(request, deadline))
        except RuntimeError as exc:
            if str(exc) == "optimization capacity exhausted":
                await context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED, "optimization capacity exhausted"
                )
            await context.abort(grpc.StatusCode.UNAVAILABLE, "optimization executor unavailable")

        future.add_done_callback(_consume_future_exception)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(_consume_asyncio_exception)
        timeout = max(0.0, deadline - time.monotonic())
        try:
            response = await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)
        except TimeoutError:
            _log_finished("deadline_exceeded", started)
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "request deadline exceeded")
        except asyncio.CancelledError:
            _log_finished("canceled", started)
            raise
        except _DecodeFailureError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid optimization request")
        except Exception:
            LOGGER.exception("optimization worker failed")
            await context.abort(grpc.StatusCode.INTERNAL, "optimization failed")

        try:
            encoded = encode_response(response)
        except ValueError:
            await context.abort(grpc.StatusCode.INTERNAL, "optimization response encoding failed")
        LOGGER.info(
            json.dumps(
                {
                    "event": "rpc_finished",
                    "request_id": response.request_id,
                    "event_id": request.event_id,
                    "verdict": response.verdict.value,
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


def create_server(settings: ServerSettings, pool: _ExecutionPool) -> grpc.aio.Server:
    service = FlowControlService(pool, settings.max_execution_sec)
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", settings.max_request_bytes),
        ]
    )
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                SERVICE_NAME,
                {
                    "Optimize": grpc.unary_unary_rpc_method_handler(
                        service.optimize,
                        request_deserializer=OptimizeRequest.FromString,
                        response_serializer=OptimizeResponse.SerializeToString,
                    )
                },
            ),
        )
    )
    health_pb2_grpc.add_HealthServicer_to_server(health.aio.HealthServicer(), server)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
    return server


async def serve(settings: ServerSettings) -> None:
    pool = _ExecutionPool()
    server = create_server(settings, pool)
    _ = server.add_insecure_port(f"{settings.host}:{settings.port}")
    await server.start()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopping.set)
    _ = await stopping.wait()
    await server.stop(None)
    await asyncio.to_thread(pool.shutdown)


def main() -> None:
    asyncio.run(serve(ServerSettings.from_env()))


def _log_finished(result: str, started: float) -> None:
    LOGGER.info(
        json.dumps(
            {"event": "rpc_finished", "result": result, "elapsed_ms": _elapsed(started)},
            separators=(",", ":"),
        )
    )


def _consume_future_exception[R](future: concurrent.futures.Future[R]) -> None:
    with suppress(concurrent.futures.CancelledError):
        _ = future.exception()


def _consume_asyncio_exception[R](future: asyncio.Future[R]) -> None:
    with suppress(asyncio.CancelledError):
        _ = future.exception()


def _positive_int(value: str, name: str, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name) from exc
    if parsed <= 0 or (maximum is not None and parsed > maximum):
        raise ValueError(name)
    return parsed


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name) from exc
    if parsed <= 0 or not parsed < float("inf"):
        raise ValueError(name)
    return parsed


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class _DecodeFailureError(Exception):
    pass
