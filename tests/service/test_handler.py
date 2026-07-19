from dataclasses import replace
from datetime import datetime, timezone

from flow_control.detection.state import DetectionState
from flow_control.detection.triggers import Event, EventKind
from flow_control.domain.enums import CurrentDirection, DirectionConstraint, NodeKind, ObservationType
from flow_control.domain.graph import Edge, EdgeID, Graph, Node, NodeID
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import Observations
from flow_control.domain.references import Reference
from flow_control.service import (
    Request,
    ResolvedConfig,
    TenantCategory,
    TenantContext,
    Verdict,
    handle_request,
)


NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _request(graph: Graph | None = None) -> Request:
    return Request(
        request_id="request-1",
        tenant_context=TenantContext("tenant-1", TenantCategory.LONG_TERM),
        graph=graph or Graph(),
        observations=Observations(observed_at=NOW),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=NOW,
    )


def test_handle_request_returns_no_trigger_without_running_downstream() -> None:
    response = handle_request(_request())

    assert response.verdict is Verdict.SKIPPED_NO_TRIGGER
    assert response.optimization_result is None
    assert [item.step.value for item in response.diagnostics.steps_executed] == [
        "VALIDATION", "MODE_DECISION", "DETECTION"
    ]


def test_handle_request_rejects_unknown_schema() -> None:
    request = _request()
    request = replace(request, schema_version="request/unknown")

    response = handle_request(request)

    assert response.verdict is Verdict.ERROR_INVALID_INPUT
    assert response.updated_detection_state is request.detection_state


def test_handle_request_rejects_graph_over_fixed_limit() -> None:
    graph = Graph(nodes=tuple())
    # The node count alone is sufficient and does not require valid edges.
    from flow_control.domain.enums import NodeKind
    from flow_control.domain.graph import Node, NodeID

    graph = Graph(nodes=tuple(Node(NodeID(str(i)), NodeKind.GOAL, False, True) for i in range(11)))
    response = handle_request(_request(graph))

    assert response.verdict is Verdict.ERROR_SIZE_EXCEEDED


def test_handle_request_runs_all_steps_for_manual_danger_trigger() -> None:
    a, b, edge_id = NodeID("a"), NodeID("b"), EdgeID("e")
    graph = Graph(
        nodes=(
            Node(a, NodeKind.GOAL, True, True),
            Node(b, NodeKind.GOAL, True, True),
        ),
        edges=(
            Edge(edge_id, a, b, DirectionConstraint.BIDIRECTIONAL_PRIOR,
                 CurrentDirection.BIDIRECTIONAL, True, ObservationType.VECTOR),
        ),
    )
    request = _request(graph)
    request = replace(request, events=(
        Event(EventKind.DANGER_FLAG_UP, "edge:e", NOW),
    ))

    response = handle_request(request)

    assert response.verdict is Verdict.OPTIMIZED
    assert response.optimization_result is not None
    assert response.updated_detection_state.consecutive_skip_count == 0
    assert [item.step.value for item in response.diagnostics.steps_executed] == [
        "VALIDATION", "MODE_DECISION", "DETECTION", "FORECASTING", "DETOUR", "OPTIMIZATION", "FEEDBACK"
    ]
