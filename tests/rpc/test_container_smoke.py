"""実コンテナに対する smoke テスト

``TOLO_SMOKE_BASE_URL``（例 ``http://127.0.0.1:18080``）が設定されたときだけ実行する。
"""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from connectrpc.protocol import ProtocolType
from pyqwest import Client, HTTPTransport, HTTPVersion

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
from flow_control.rpc.generated.tolo.flow.v1.flow_connect import FlowControlServiceClient
from flow_control.service.config import OptimizationMode, ResolvedConfig
from flow_control.service.context import TenantContext
from flow_control.service.messages import Request
from flow_control.service.verdict import Verdict

BASE_URL = os.environ.get("TOLO_SMOKE_BASE_URL", "")

pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="TOLO_SMOKE_BASE_URL is not set; container smoke test is skipped"
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


def test_probes_report_healthy() -> None:
    async def run() -> None:
        async with HTTPTransport(http_version=HTTPVersion.HTTP1) as transport:
            client = Client(transport=transport)
            for path in ("/livez", "/readyz"):
                response = await client.get(f"{BASE_URL}{path}")
                assert response.status == 200, path

    asyncio.run(run())


@pytest.mark.parametrize("mode", [OptimizationMode.LIGHTWEIGHT, OptimizationMode.STRICT])
def test_optimize_runs_solver_in_container(mode: OptimizationMode) -> None:
    async def run() -> None:
        request = codec.encode_request(_danger_request(mode), event_id=f"smoke-{mode.value}")
        async with HTTPTransport(http_version=HTTPVersion.HTTP1) as transport:
            client = FlowControlServiceClient(
                BASE_URL,
                protocol=ProtocolType.CONNECT,
                send_compression=None,
                http_client=Client(transport=transport),
            )
            wire = await client.optimize(request)
        response = codec.decode_response(wire)
        assert response.request_id == request.request_id
        assert response.verdict is Verdict.OPTIMIZED
        assert response.optimization_result is not None

    asyncio.run(run())
