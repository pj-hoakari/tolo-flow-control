import asyncio
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import grpc
import pytest
from grpc_health.v1 import health_pb2

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
from flow_control.rpc.generated.tolo.flow.v1 import flow_pb2 as pb
from flow_control.service.config import ResolvedConfig
from flow_control.service.context import TenantContext
from flow_control.service.messages import Request, Response
from flow_control.service.verdict import Verdict

type _Optimize = grpc.aio.UnaryUnaryMultiCallable[pb.OptimizeRequest, pb.OptimizeResponse]


@asynccontextmanager
async def _serve(
    settings: server.ServerSettings,
) -> AsyncGenerator[tuple[_Optimize, grpc.aio.Channel]]:
    pool = server._ExecutionPool()
    grpc_server = server.create_server(settings, pool)
    port = grpc_server.add_insecure_port("127.0.0.1:0")
    await grpc_server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            yield (
                channel.unary_unary(
                    f"/{server.SERVICE_NAME}/Optimize",
                    request_serializer=pb.OptimizeRequest.SerializeToString,
                    response_deserializer=pb.OptimizeResponse.FromString,
                ),
                channel,
            )
    finally:
        await grpc_server.stop(None)
        await asyncio.to_thread(pool.shutdown)


async def _status(
    call: grpc.aio.UnaryUnaryCall[pb.OptimizeRequest, pb.OptimizeResponse],
) -> grpc.StatusCode:
    with pytest.raises(grpc.aio.AioRpcError) as error:
        _ = await call
    return error.value.code()


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


def _fake_decode(_: pb.OptimizeRequest) -> object:
    return object()


def _fake_encode(_: Response) -> pb.OptimizeResponse:
    return pb.OptimizeResponse(request_id="r1")


def _blocked_settings(monkeypatch: pytest.MonkeyPatch, max_execution_sec: float):
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
            _ = released.wait(1)
            return response
        finally:
            finished.set()

    monkeypatch.setattr(server, "decode_request", _fake_decode)
    monkeypatch.setattr(server, "handle_request", handle)
    monkeypatch.setattr(server, "encode_response", _fake_encode)
    return server.ServerSettings(max_execution_sec=max_execution_sec), released, started, finished


def test_timeout_keeps_single_executor_slot_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        settings, released, started, finished = _blocked_settings(monkeypatch, 0.05)
        try:
            async with _serve(settings) as (optimize, _):
                assert await _status(optimize(pb.OptimizeRequest())) == (
                    grpc.StatusCode.DEADLINE_EXCEEDED
                )
                assert started.is_set()
                assert await _status(optimize(pb.OptimizeRequest())) == (
                    grpc.StatusCode.RESOURCE_EXHAUSTED
                )

                released.set()
                assert await asyncio.to_thread(finished.wait, 1)
                result = await optimize(pb.OptimizeRequest())
                assert result.request_id == "r1"
        finally:
            released.set()

    asyncio.run(run())


def test_client_deadline_bounds_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        settings, released, _, _ = _blocked_settings(monkeypatch, 60.0)
        try:
            async with _serve(settings) as (optimize, _):
                status = await asyncio.wait_for(
                    _status(optimize(pb.OptimizeRequest(), timeout=0.05)), 2
                )
                assert status == grpc.StatusCode.DEADLINE_EXCEEDED
        finally:
            released.set()

    asyncio.run(run())


def test_cancel_keeps_single_executor_slot_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        settings, released, started, finished = _blocked_settings(monkeypatch, 5.0)
        try:
            async with _serve(settings) as (optimize, _):
                call = optimize(pb.OptimizeRequest())
                assert await asyncio.to_thread(started.wait, 1)
                _ = call.cancel()
                assert not finished.is_set()

                assert await _status(optimize(pb.OptimizeRequest())) == (
                    grpc.StatusCode.RESOURCE_EXHAUSTED
                )

                released.set()
                assert await asyncio.to_thread(finished.wait, 1)
        finally:
            released.set()

    asyncio.run(run())


def test_message_limit_stops_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        def decode(_: pb.OptimizeRequest) -> object:
            pytest.fail("decoded oversized message")

        monkeypatch.setattr(server, "decode_request", decode)
        async with _serve(server.ServerSettings(max_request_bytes=1)) as (optimize, _):
            status = await _status(optimize(pb.OptimizeRequest(request_id="12")))
        assert status == grpc.StatusCode.RESOURCE_EXHAUSTED

    asyncio.run(run())


def test_optimize_over_grpc() -> None:
    async def run() -> None:
        request = codec.encode_request(_request(), event_id="event-1")
        async with _serve(server.ServerSettings()) as (optimize, _):
            response = await optimize(request)
        assert response.request_id == "r1"

    asyncio.run(run())


def test_health_reports_serving() -> None:
    async def run() -> None:
        async with _serve(server.ServerSettings()) as (_, channel):
            check = channel.unary_unary(
                "/grpc.health.v1.Health/Check",
                request_serializer=health_pb2.HealthCheckRequest.SerializeToString,
                response_deserializer=health_pb2.HealthCheckResponse.FromString,
            )
            response = await check(health_pb2.HealthCheckRequest())
        assert response == health_pb2.HealthCheckResponse(status="SERVING")

    asyncio.run(run())
