"""実コンテナに対する smoke テスト

``TOLO_SMOKE_ADDRESS``（例 ``127.0.0.1:18080``）が設定されたときだけ実行する。
"""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime

import grpc
import pytest

from flow_control.detection.state import DetectionState
from flow_control.detection.triggers import Event, EventKind
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
from flow_control.service.config import OptimizationMode, ResolvedConfig
from flow_control.service.context import TenantContext
from flow_control.service.messages import Request
from flow_control.service.verdict import Verdict

ADDRESS = os.environ.get("TOLO_SMOKE_ADDRESS", "")

pytestmark = pytest.mark.skipif(
    not ADDRESS, reason="TOLO_SMOKE_ADDRESS is not set; container smoke test is skipped"
)

NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _danger_request(mode: OptimizationMode) -> Request:
    """手動危険フラグで Detection を発火させ、実ソルバーまで到達させる要求"""
    a, b, edge_id = NodeID("a"), NodeID("b"), EdgeID("e")
    graph = Graph(
        nodes=(
            Node(a, NodeKind.GOAL, True, True),
            Node(b, NodeKind.GOAL, True, True),
        ),
        edges=(
            Edge(
                edge_id,
                a,
                b,
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                CurrentDirection.BIDIRECTIONAL,
                True,
                ObservationType.VECTOR,
            ),
        ),
    )
    return Request(
        request_id=f"smoke-{mode.value.lower()}",
        tenant_context=TenantContext(tenant_id="smoke-tenant"),
        graph=graph,
        observations=Observations(observed_at=NOW),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=replace(ResolvedConfig(), optimization_mode=mode),
        server_time=NOW,
        events=(Event(EventKind.DANGER_FLAG_UP, "edge:e", NOW),),
    )


@pytest.mark.parametrize("mode", [OptimizationMode.LIGHTWEIGHT, OptimizationMode.STRICT])
def test_optimize_runs_solver_in_container(mode: OptimizationMode) -> None:
    async def run() -> None:
        request = codec.encode_request(_danger_request(mode), event_id=f"smoke-{mode.value}")
        async with grpc.aio.insecure_channel(ADDRESS) as channel:
            optimize = channel.unary_unary(
                "/tolo.flow.v1.FlowControlService/Optimize",
                request_serializer=pb.OptimizeRequest.SerializeToString,
                response_deserializer=pb.OptimizeResponse.FromString,
            )
            wire = await optimize(request, wait_for_ready=True, timeout=120)
        response = codec.decode_response(wire)
        assert response.request_id == request.request_id
        assert response.verdict is Verdict.OPTIMIZED
        assert response.optimization_result is not None

    asyncio.run(run())
