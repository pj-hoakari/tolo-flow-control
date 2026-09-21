import asyncio
import json
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

import pytest
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.method import IdempotencyLevel, MethodInfo
from connectrpc.protocol import ProtocolType
from connectrpc.request import Headers, RequestContext
from google.protobuf import json_format
from hypercorn.asyncio import serve
from hypercorn.config import Config
from hypercorn.typing import ASGIFramework
from pyqwest import Client, HTTPTransport, HTTPVersion

import flow_control.rpc.server as server
from flow_control.detection.state import DetectionState
from flow_control.domain.enums import (
    CurrentDirection,
    DirectionConstraint,
    NodeKind,
    ObservationType,
)
from flow_control.domain.graph import Edge, EdgeID, Graph, Node, NodeID
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import Observations
from flow_control.domain.references import Reference
from flow_control.rpc import codec
from flow_control.rpc.auth import (
    AuthenticationError,
    CloudRunAuthenticator,
)
from flow_control.rpc.generated.tolo.flow.v1 import flow_pb2 as pb
from flow_control.rpc.generated.tolo.flow.v1.flow_connect import FlowControlServiceClient
from flow_control.service.config import ResolvedConfig
from flow_control.service.context import TenantContext
from flow_control.service.messages import Request, Response
from flow_control.service.verdict import Verdict
from tests.rpc.test_auth import _claims, _config, _token, _verifier

type _Receive = Callable[[], Awaitable[dict[str, object]]]
type _Send = Callable[[dict[str, object]], Awaitable[None]]
type _ASGIApp = Callable[[dict[str, object], _Receive, _Send], Awaitable[None]]

_RPC_HEADERS = [
    (b"workload-authorization", b"Bearer token"),
    (b"content-type", b"application/proto"),
    (b"connect-protocol-version", b"1"),
]


class _Authenticator:
    def __init__(
        self,
        *,
        ready: bool = True,
        error: Exception | None = None,
        delay_sec: float = 0.0,
    ) -> None:
        self._ready = ready
        self.error = error
        self.delay_sec = delay_sec
        self.refresh_calls = 0
        self.tokens: list[str] = []

    @property
    def ready(self) -> bool:
        return self._ready

    def refresh(self) -> None:
        self.refresh_calls += 1
        self._ready = True

    def authenticate(self, token: str) -> None:
        self.tokens.append(token)
        if self.delay_sec:
            time.sleep(self.delay_sec)
        if self.error is not None:
            raise self.error


def _create_app(
    authenticator: _Authenticator,
    settings: server.ServerSettings | None = None,
) -> _ASGIApp:
    app = server.create_app(
        settings=settings,
        authenticator=cast(CloudRunAuthenticator, cast(object, authenticator)),
    )
    return cast(_ASGIApp, app)


def _ctx(timeout_ms: int | None = None) -> RequestContext[pb.OptimizeRequest, pb.OptimizeResponse]:
    return RequestContext(
        method=MethodInfo(
            name="Optimize",
            service_name="tolo.flow.v1.FlowControlService",
            input=pb.OptimizeRequest,
            output=pb.OptimizeResponse,
            idempotency_level=IdempotencyLevel.UNKNOWN,
        ),
        http_method="POST",
        request_headers=Headers(),
        timeout_ms=timeout_ms,
    )


async def _invoke(
    app: _ASGIApp,
    scope: dict[str, object],
    messages: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    sent: list[dict[str, object]] = []
    index = 0

    async def receive() -> dict[str, object]:
        nonlocal index
        if index == len(messages):
            raise AssertionError("receive called after input exhausted")
        message = messages[index]
        index += 1
        return message

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent, index


def _http_scope(
    path: str, headers: list[tuple[bytes, bytes]], root_path: str = ""
) -> dict[str, object]:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "root_path": root_path,
        "headers": headers,
    }


def _request() -> Request:
    now = datetime.now(UTC)
    return Request(
        request_id="r1",
        tenant_context=TenantContext(tenant_id="t1"),
        graph=Graph(
            nodes=(
                Node(NodeID("n1"), NodeKind.GOAL, True, True),
                Node(NodeID("n2"), NodeKind.TRANSIT_ONLY, False, True),
            ),
            edges=(
                Edge(
                    EdgeID("e1"),
                    NodeID("n1"),
                    NodeID("n2"),
                    DirectionConstraint.BIDIRECTIONAL_PRIOR,
                    CurrentDirection.A_TO_B,
                    True,
                    ObservationType.VECTOR,
                ),
            ),
        ),
        observations=Observations(observed_at=now),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=now,
    )


def test_authentication_precedes_body_and_unknown_paths_cannot_reach_generated() -> None:
    async def run() -> None:
        authenticator = _Authenticator(error=AuthenticationError("bad"))
        app = _create_app(authenticator)
        headers = [(b"workload-authorization", b"Bearer token")]
        sent, received = await _invoke(
            app,
            _http_scope(server.RPC_PATH, headers),
            [{"type": "http.request", "body": b"invalid", "more_body": False}],
        )
        assert sent[0]["status"] == 401
        assert received == 0

        sent, received = await _invoke(
            app,
            _http_scope("/mounted/other", headers, "/mounted"),
            [{"type": "http.request", "body": b"invalid", "more_body": False}],
        )
        assert sent[0]["status"] == 404
        assert received == 0

        sent, received = await _invoke(
            app,
            _http_scope("/mounted" + server.RPC_PATH, headers, "/mounted"),
            [{"type": "http.request", "body": b"invalid", "more_body": False}],
        )
        assert sent[0]["status"] == 401
        assert received == 0

    asyncio.run(run())


def test_ready_probe_refreshes_expired_trust() -> None:
    async def run() -> None:
        authenticator = _Authenticator(ready=False)
        app = _create_app(authenticator)
        sent, received = await _invoke(
            app,
            _http_scope("/readyz", []),
            [],
        )
        assert sent[0]["status"] == 200
        assert authenticator.refresh_calls == 1
        assert received == 0

    asyncio.run(run())


def test_connect_timeout_covers_authentication_and_body() -> None:
    async def run() -> None:
        slow_auth = _Authenticator(delay_sec=0.05)
        app = _create_app(slow_auth)
        sent, received = await _invoke(
            app,
            _http_scope(
                server.RPC_PATH,
                [(b"workload-authorization", b"Bearer token"), (b"connect-timeout-ms", b"5")],
            ),
            [],
        )
        assert sent[0]["status"] == 504
        assert received == 0

        authenticator = _Authenticator()
        app = _create_app(authenticator)
        entered = asyncio.Event()

        async def receive() -> dict[str, object]:
            entered.set()
            await asyncio.sleep(1)
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict[str, object]] = []

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        task = asyncio.ensure_future(
            app(
                _http_scope(
                    server.RPC_PATH,
                    [
                        (b"workload-authorization", b"Bearer token"),
                        (b"connect-timeout-ms", b"5"),
                    ],
                ),
                receive,
                send,
            )
        )
        await asyncio.wait_for(task, 1)
        assert sent[0]["status"] == 504
        assert entered.is_set()

    asyncio.run(run())


def _blocked_service(monkeypatch: pytest.MonkeyPatch, max_execution_sec: float):
    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()
    response = Response(
        request_id="r1",
        verdict=Verdict.SKIPPED_NO_TRIGGER,
        updated_detection_state=DetectionState(),
    )

    def decode(_: pb.OptimizeRequest) -> object:
        return object()

    def handle(_: object, *, deadline: float | None = None) -> Response:
        started.set()
        try:
            released.wait(1)
            return response
        finally:
            finished.set()

    monkeypatch.setattr(server, "decode_request", decode)
    monkeypatch.setattr(server, "handle_request", handle)
    monkeypatch.setattr(server, "encode_response", lambda _: pb.OptimizeResponse(request_id="r1"))
    return (
        server.FlowControlService(server._ExecutionPool(), max_execution_sec),
        started,
        released,
        finished,
    )


def test_timeout_keeps_single_executor_slot_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, started, released, finished = _blocked_service(monkeypatch, 0.01)
        try:
            first = asyncio.create_task(service.optimize(pb.OptimizeRequest(), _ctx()))
            assert await asyncio.to_thread(started.wait, 1)
            with pytest.raises(ConnectError) as first_error:
                await first
            assert first_error.value.code == Code.DEADLINE_EXCEEDED

            with pytest.raises(ConnectError) as second_error:
                await service.optimize(pb.OptimizeRequest(), _ctx())
            assert second_error.value.code == Code.RESOURCE_EXHAUSTED

            released.set()
            assert await asyncio.to_thread(finished.wait, 1)
            result = await service.optimize(pb.OptimizeRequest(), _ctx())
            assert result.request_id == "r1"
        finally:
            released.set()
            await asyncio.to_thread(service._pool.shutdown)

    asyncio.run(run())


def test_cancel_keeps_single_executor_slot_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, started, released, finished = _blocked_service(monkeypatch, 1.0)
        try:
            task = asyncio.create_task(service.optimize(pb.OptimizeRequest(), _ctx()))
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(ConnectError) as canceled:
                await task
            assert canceled.value.code == Code.CANCELED

            with pytest.raises(ConnectError) as second_error:
                await service.optimize(pb.OptimizeRequest(), _ctx())
            assert second_error.value.code == Code.RESOURCE_EXHAUSTED

            released.set()
            assert await asyncio.to_thread(finished.wait, 1)
        finally:
            released.set()
            await asyncio.to_thread(service._pool.shutdown)

    asyncio.run(run())


def test_body_limit_stops_before_generated_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        authenticator = _Authenticator()
        monkeypatch.setattr(
            server, "decode_request", lambda _: pytest.fail("decoded oversized body")
        )
        app = _create_app(authenticator, server.ServerSettings(max_request_bytes=1))
        sent, received = await _invoke(
            app,
            _http_scope(server.RPC_PATH, [(b"workload-authorization", b"Bearer token")]),
            [{"type": "http.request", "body": b"12", "more_body": False}],
        )
        assert sent[0]["status"] == 429
        assert received == 1

    asyncio.run(run())


async def _rpc_call(
    app: _ASGIApp, after_body: _Receive, headers: list[tuple[bytes, bytes]] | None = None
) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []
    delivered = 0

    async def receive() -> dict[str, object]:
        nonlocal delivered
        delivered += 1
        if delivered == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        return await after_body()

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(_http_scope(server.RPC_PATH, headers or _RPC_HEADERS), receive, send)
    return sent


async def _stay_connected() -> dict[str, object]:
    await asyncio.sleep(3600)
    return {"type": "http.disconnect"}


def _status(sent: list[dict[str, object]]) -> int:
    starts = [message for message in sent if message.get("type") == "http.response.start"]
    assert len(starts) == 1
    return cast(int, starts[0]["status"])


def _body(sent: list[dict[str, object]]) -> bytes:
    bodies = [message for message in sent if message.get("type") == "http.response.body"]
    assert len(bodies) == 1
    return cast(bytes, bodies[0]["body"])


def test_disconnect_cancels_generated_task_and_keeps_worker_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        started = threading.Event()
        released = threading.Event()
        finished = threading.Event()
        response = Response(
            request_id="r1",
            verdict=Verdict.SKIPPED_NO_TRIGGER,
            updated_detection_state=DetectionState(),
        )

        def handle(_: object, *, deadline: float | None = None) -> Response:
            del deadline
            started.set()
            try:
                released.wait(5)
                return response
            finally:
                finished.set()

        monkeypatch.setattr(server, "decode_request", lambda _: object())
        monkeypatch.setattr(server, "handle_request", handle)
        monkeypatch.setattr(
            server, "encode_response", lambda _: pb.OptimizeResponse(request_id="r1")
        )
        app = _create_app(_Authenticator())

        async def disconnect_once_started() -> dict[str, object]:
            _ = await asyncio.to_thread(started.wait, 5)
            return {"type": "http.disconnect"}

        disconnected = await asyncio.wait_for(_rpc_call(app, disconnect_once_started), 2)
        assert _status(disconnected) == 499
        assert json.loads(_body(disconnected))["code"] == "canceled"
        assert not finished.is_set()

        rejected = await asyncio.wait_for(_rpc_call(app, _stay_connected), 2)
        assert _status(rejected) == 429

        released.set()
        assert await asyncio.to_thread(finished.wait, 5)
        accepted = await asyncio.wait_for(_rpc_call(app, _stay_connected), 2)
        assert _status(accepted) == 200

    asyncio.run(run())


def test_iam_and_workload_headers_coexist_but_repeats_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        response = Response(
            request_id="r1",
            verdict=Verdict.SKIPPED_NO_TRIGGER,
            updated_detection_state=DetectionState(),
        )
        monkeypatch.setattr(server, "decode_request", lambda _: object())
        monkeypatch.setattr(server, "handle_request", lambda _, **__: response)
        monkeypatch.setattr(
            server, "encode_response", lambda _: pb.OptimizeResponse(request_id="r1")
        )
        authenticator = _Authenticator()
        app = _create_app(authenticator)

        accepted = await asyncio.wait_for(
            _rpc_call(
                app,
                _stay_connected,
                [
                    (b"authorization", b"Bearer token"),
                    (b"x-serverless-authorization", b"Bearer token"),
                    *_RPC_HEADERS,
                ],
            ),
            2,
        )
        assert _status(accepted) == 200
        assert authenticator.tokens == ["token"]

        sent, received = await _invoke(
            app,
            _http_scope(
                server.RPC_PATH,
                [
                    (b"workload-authorization", b"Bearer token"),
                    (b"Workload-Authorization", b"Bearer token"),
                ],
            ),
            [],
        )
        assert sent[0]["status"] == 401
        assert received == 0
        assert authenticator.tokens == ["token"]

    asyncio.run(run())


def test_compressed_request_is_refused_before_decompression() -> None:
    async def run() -> None:
        app = _create_app(_Authenticator())
        sent = await asyncio.wait_for(
            _rpc_call(app, _stay_connected, [*_RPC_HEADERS, (b"content-encoding", b"gzip")]),
            2,
        )
        assert _status(sent) == 501
        assert json.loads(_body(sent))["code"] == "unimplemented"

    asyncio.run(run())


def test_generated_client_binary_and_protojson_over_hypercorn(key_material) -> None:
    async def run() -> None:
        key, cert = key_material
        authenticator = CloudRunAuthenticator(_config(), _verifier(cert))
        token = _token(key, _claims())
        app = server.create_app(authenticator=authenticator)
        port_socket = socket.socket()
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
        port_socket.close()
        config = Config()
        config.bind = [f"127.0.0.1:{port}"]
        config.accesslog = None
        config.errorlog = None
        stopped = asyncio.Event()

        async def shutdown_trigger() -> None:
            await stopped.wait()

        server_task = asyncio.create_task(
            serve(cast(ASGIFramework, app), config, shutdown_trigger=shutdown_trigger)
        )
        try:
            for _ in range(100):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                except OSError:
                    await asyncio.sleep(0.01)
                else:
                    writer.close()
                    await writer.wait_closed()
                    del reader
                    break
            else:
                raise AssertionError("Hypercorn did not start")

            address = f"http://127.0.0.1:{port}"
            request = codec.encode_request(_request(), event_id="event-1")
            async with HTTPTransport(http_version=HTTPVersion.HTTP1) as transport:
                async_client = Client(transport=transport)
                client = FlowControlServiceClient(
                    address,
                    protocol=ProtocolType.CONNECT,
                    send_compression=None,
                    http_client=async_client,
                )
                binary_response = await client.optimize(
                    request,
                    headers={"workload-authorization": f"Bearer {token}"},
                )
                assert binary_response.request_id == "r1"

                json_response = await async_client.post(
                    f"{address}{server.RPC_PATH}",
                    headers={
                        "content-type": "application/json",
                        "accept": "application/json",
                        "workload-authorization": f"Bearer {token}",
                    },
                    content=json_format.MessageToJson(request).encode(),
                )
                assert json_response.status == 200
                wire_response = pb.OptimizeResponse()
                json_format.Parse(json_response.content.decode(), wire_response)
                assert wire_response.SerializeToString() == binary_response.SerializeToString()
        finally:
            stopped.set()
            await asyncio.wait_for(server_task, 5)

    asyncio.run(run())
