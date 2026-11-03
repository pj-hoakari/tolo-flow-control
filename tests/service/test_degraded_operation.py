from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.domain import (
    ArcFlow,
    ArcHistoryStat,
    ArcStagnation,
    ArcWindowSeries,
    Boundary,
    BoundaryDirection,
    ConfidenceFlag,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    FlowDirection,
    Graph,
    HistoryDigest,
    Node,
    NodeID,
    NodeKind,
    Observations,
    ObservationType,
    Reference,
)
from flow_control.domain.element_state import HistoryTier, Judgement, ObservationState
from flow_control.service import (
    EventContext,
    EventTerm,
    Request,
    ResolvedConfig,
    TenantContext,
    Verdict,
    handle_request,
)
from flow_control.service.diagnostics import ElementStateRecord, Warning, WarningCode

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
E = EdgeID("e")
ESTABLISHED = ArcHistoryStat(E, p90_stagnation=5.0, baseline_stagnation=5.0)
SURGING_LINE = tuple((NOW - timedelta(minutes=10 - i), 10.0 * i) for i in range(10))
FRESH = timedelta(0)
STAGNATION_WINDOW = ((NOW - timedelta(minutes=2), 5.0), (NOW - timedelta(minutes=1), 5.0))


def _graph() -> Graph:
    a, b = NodeID("a"), NodeID("b")
    boundary = Boundary(BoundaryDirection.ENTRY_AND_EXIT, active=True)
    return Graph(
        nodes=(
            Node(a, NodeKind.GOAL, True, boundary=boundary),
            Node(b, NodeKind.GOAL, True, boundary=boundary),
        ),
        edges=(
            Edge(
                E,
                a,
                b,
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                CurrentDirection.BIDIRECTIONAL,
                True,
                ObservationType.VECTOR,
            ),
        ),
    )


def _request(
    *,
    stat: ArcHistoryStat | None = ESTABLISHED,
    flow_window: tuple[tuple[datetime, float], ...] = SURGING_LINE,
    stagnation_window: tuple[tuple[datetime, float], ...] = STAGNATION_WINDOW,
    flag: ConfidenceFlag = ConfidenceFlag.OK,
    observed_ago: timedelta = FRESH,
    observed: bool = True,
) -> Request:
    observations = Observations(observed_at=NOW - observed_ago)
    if observed:
        observations = replace(
            observations,
            arc_flows=(ArcFlow(E, FlowDirection.A_TO_B, 100.0, confidence_flag=flag),),
            arc_stagnations=(ArcStagnation(E, 15.0, confidence_flag=flag),),
        )
    return Request(
        request_id="degraded-1",
        tenant_context=TenantContext("tenant-1"),
        event_context=EventContext(EventTerm.LONG),
        graph=_graph(),
        observations=observations,
        history_digest=HistoryDigest(
            arc_stats=() if stat is None else (stat,),
            window_series=(
                ArcWindowSeries(E, flow_samples=flow_window, stagnation_samples=stagnation_window),
            ),
        ),
        detection_state=DetectionState(
            arc_watch_states=(
                ArcWatchState(
                    E,
                    percentile_breached=True,
                    delta_breached=True,
                    stagnation_watch_since=NOW - timedelta(minutes=6),
                ),
            )
        ),
        references=Reference(),
        config=ResolvedConfig(surge_rate_threshold_percent_per_min=10.0),
        server_time=NOW,
    )


def _partial(held: str) -> Warning:
    return Warning(WarningCode.PARTIAL_COMBINED_TRIGGER, (("edge_id", "e"), ("held", held)))


def _record(
    observation: ObservationState, history: HistoryTier, line_points: int, *skipped: Judgement
) -> tuple[ElementStateRecord, ...]:
    return (ElementStateRecord("edge:e", observation, history, line_points, skipped),)


OK, ESTABLISHED_TIER = ObservationState.OK, HistoryTier.ESTABLISHED
UNDETERMINABLE = (Judgement.SURGE, Judgement.HIGH_STAGNATION, Judgement.COMBINED)
NO_SURGE = (Judgement.SURGE, Judgement.COMBINED)


@pytest.mark.parametrize(
    ("request_", "verdict", "warnings", "records"),
    [
        pytest.param(_request(), Verdict.OPTIMIZED, (), (), id="ok-line-established"),
        pytest.param(
            _request(stat=ArcHistoryStat(E, available_span_hours=2.0)),
            Verdict.OPTIMIZED,
            (),
            _record(OK, HistoryTier.SHORT, 11),
            id="history-short",
        ),
        pytest.param(
            _request(stat=None),
            Verdict.OPTIMIZED,
            (),
            _record(OK, HistoryTier.WINDOW_ONLY, 11),
            id="window-only",
        ),
        pytest.param(
            _request(flow_window=(), stagnation_window=()),
            Verdict.SKIPPED_NO_TRIGGER,
            (_partial("HIGH_STAGNATION"),),
            _record(OK, ESTABLISHED_TIER, 1, *NO_SURGE),
            id="window-empty",
        ),
        pytest.param(
            _request(stat=None, flow_window=(), stagnation_window=()),
            Verdict.SKIPPED_NO_TRIGGER,
            (),
            _record(OK, HistoryTier.NONE, 1, *UNDETERMINABLE),
            id="no-history",
        ),
        pytest.param(
            _request(flow_window=()),
            Verdict.SKIPPED_NO_TRIGGER,
            (_partial("HIGH_STAGNATION"),),
            _record(OK, ESTABLISHED_TIER, 1, *NO_SURGE),
            id="line-sparse",
        ),
        pytest.param(
            _request(flag=ConfidenceFlag.HOLD),
            Verdict.SKIPPED_NO_TRIGGER,
            (),
            _record(ObservationState.HOLD, ESTABLISHED_TIER, 11, *UNDETERMINABLE),
            id="hold",
        ),
        pytest.param(
            _request(flag=ConfidenceFlag.INVALID),
            Verdict.SKIPPED_NO_TRIGGER,
            (),
            _record(ObservationState.INVALID, ESTABLISHED_TIER, 10, *UNDETERMINABLE),
            id="invalid",
        ),
        pytest.param(
            _request(observed=False),
            Verdict.SKIPPED_NO_TRIGGER,
            (),
            _record(ObservationState.UNOBSERVED, ESTABLISHED_TIER, 10, *UNDETERMINABLE),
            id="unobserved",
        ),
        pytest.param(
            _request(observed_ago=timedelta(minutes=10)),
            Verdict.SKIPPED_NO_TRIGGER,
            (),
            _record(ObservationState.STALE, ESTABLISHED_TIER, 11, *UNDETERMINABLE),
            id="stale",
        ),
    ],
)
def test_element_state_decides_the_combined_trigger(request_, verdict, warnings, records):
    response = handle_request(request_)

    assert response.verdict is verdict
    assert response.diagnostics.warnings == warnings
    assert response.diagnostics.element_states == records


def test_surge_held_while_stagnation_is_undeterminable_is_warned():
    response = handle_request(_request(stat=None, stagnation_window=()))

    assert response.verdict is Verdict.SKIPPED_NO_TRIGGER
    assert response.diagnostics.warnings == (_partial("SURGE"),)
    assert response.diagnostics.element_states == _record(
        OK, HistoryTier.NONE, 11, Judgement.HIGH_STAGNATION, Judgement.COMBINED
    )


def test_zero_flow_line_makes_surge_undeterminable():
    zero_line = tuple((t, 0.0) for t, _ in SURGING_LINE)
    request = _request(flow_window=zero_line)
    request = replace(
        request,
        observations=replace(
            request.observations, arc_flows=(ArcFlow(E, FlowDirection.A_TO_B, 0.0),)
        ),
    )

    response = handle_request(request)

    assert response.verdict is Verdict.SKIPPED_NO_TRIGGER
    assert response.diagnostics.warnings == (_partial("HIGH_STAGNATION"),)
    assert response.diagnostics.element_states == _record(OK, ESTABLISHED_TIER, 11, *NO_SURGE)


def test_stagnation_without_surge_is_calm_not_undeterminable():
    flat_line = tuple((t, 50.0) for t, _ in SURGING_LINE)
    request = _request(flow_window=flat_line)
    request = replace(
        request,
        observations=replace(
            request.observations, arc_flows=(ArcFlow(E, FlowDirection.A_TO_B, 50.0),)
        ),
    )

    response = handle_request(request)

    assert response.verdict is Verdict.SKIPPED_NO_TRIGGER
    assert response.diagnostics.warnings == ()
    assert response.diagnostics.element_states == ()
