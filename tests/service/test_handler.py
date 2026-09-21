import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import flow_control.service.handler as handler_module
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
from flow_control.forecasting import forecast as forecasting_forecast
from flow_control.optimization import SolverStatus
from flow_control.optimization import optimize as optimization_optimize
from flow_control.service import (
    Request,
    ResolvedConfig,
    TenantCategory,
    TenantContext,
    Verdict,
    handle_request,
)

NOW = datetime(2026, 7, 20, tzinfo=UTC)


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


def _danger_request() -> Request:
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
    return replace(_request(graph), events=(Event(EventKind.DANGER_FLAG_UP, "edge:e", NOW),))


def test_handle_request_returns_no_trigger_without_running_downstream() -> None:
    response = handle_request(_request())

    assert response.verdict is Verdict.SKIPPED_NO_TRIGGER
    assert response.optimization_result is None
    assert [item.step.value for item in response.diagnostics.steps_executed] == [
        "VALIDATION",
        "MODE_DECISION",
        "DETECTION",
    ]


def test_handle_request_rejects_unknown_schema() -> None:
    request = _request()
    request = replace(request, schema_version="request/unknown")

    response = handle_request(request)

    assert response.verdict is Verdict.ERROR_INVALID_INPUT
    assert response.updated_detection_state is request.detection_state


def test_handle_request_rejects_graph_over_fixed_limit() -> None:
    graph = Graph(nodes=())
    # The node count alone is sufficient and does not require valid edges.
    from flow_control.domain.enums import NodeKind
    from flow_control.domain.graph import Node, NodeID

    graph = Graph(nodes=tuple(Node(NodeID(str(i)), NodeKind.GOAL, False, True) for i in range(11)))
    response = handle_request(_request(graph))

    assert response.verdict is Verdict.ERROR_SIZE_EXCEEDED


def test_handle_request_runs_all_steps_for_manual_danger_trigger() -> None:
    request = _danger_request()

    response = handle_request(request)

    assert response.verdict is Verdict.OPTIMIZED
    assert response.optimization_result is not None
    assert response.updated_detection_state.consecutive_skip_count == 0
    assert [item.step.value for item in response.diagnostics.steps_executed] == [
        "VALIDATION",
        "MODE_DECISION",
        "DETECTION",
        "FORECASTING",
        "DETOUR",
        "OPTIMIZATION",
        "FEEDBACK",
    ]


def test_handle_request_does_not_extend_short_deadline_to_minimum(monkeypatch) -> None:
    budgets = []

    def fake_optimize(*args, **_kwargs):
        budgets.append(args[8])
        return SimpleNamespace(
            optimization_result=SimpleNamespace(solver_status=SolverStatus.TIMEOUT)
        )

    monkeypatch.setattr(handler_module, "optimize", fake_optimize)
    response = handle_request(_danger_request(), deadline=time.monotonic() + 70.0)

    assert response.verdict is Verdict.SKIPPED_TIME
    assert budgets
    assert budgets[0] > 0.0
    assert budgets[0] < 30.0


def test_handle_request_reserves_buffer_so_a_solution_under_rpc_deadline_survives(
    monkeypatch,
) -> None:
    budgets = []
    clock = [100.0]

    def budget_consuming_optimize(*args, **kwargs):
        budgets.append(args[8])
        result = optimization_optimize(*args, **kwargs)
        clock[0] += args[8]
        return result

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(handler_module, "optimize", budget_consuming_optimize)
    response = handle_request(_danger_request(), deadline=170.0)

    assert budgets == [10.0]
    assert response.verdict is Verdict.OPTIMIZED


def test_handle_request_keeps_final_retry_budget_extension(monkeypatch) -> None:
    budgets = []
    request = replace(_danger_request(), detection_state=DetectionState(consecutive_skip_count=3))

    def fake_optimize(*args, **_kwargs):
        budgets.append(args[8])
        return SimpleNamespace(
            optimization_result=SimpleNamespace(solver_status=SolverStatus.TIMEOUT)
        )

    monkeypatch.setattr(handler_module, "optimize", fake_optimize)
    response = handle_request(request)

    assert response.verdict is Verdict.SKIPPED_TIME
    assert budgets
    assert budgets[0] > request.config.lightweight_opt_budget_sec


def test_handle_request_checks_deadline_after_forecasting(monkeypatch) -> None:
    original_forecast = forecasting_forecast
    optimize_called = False
    clock = [100.0]

    def monotonic() -> float:
        return clock[0]

    def slow_forecast(*args, **kwargs):
        result = original_forecast(*args, **kwargs)
        clock[0] = 100.01
        return result

    def fake_optimize(*_args, **_kwargs):
        nonlocal optimize_called
        optimize_called = True
        return SimpleNamespace(
            optimization_result=SimpleNamespace(solver_status=SolverStatus.OPTIMAL)
        )

    monkeypatch.setattr(time, "monotonic", monotonic)
    monkeypatch.setattr(handler_module, "forecast", slow_forecast)
    monkeypatch.setattr(handler_module, "optimize", fake_optimize)
    response = handle_request(_danger_request(), deadline=100.005)

    assert response.verdict is Verdict.SKIPPED_TIME
    assert not optimize_called
    assert [item.step.value for item in response.diagnostics.steps_executed] == [
        "VALIDATION",
        "MODE_DECISION",
        "DETECTION",
        "FORECASTING",
    ]
