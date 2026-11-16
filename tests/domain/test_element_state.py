from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from flow_control.domain import (
    ArcFlow,
    ArcHistoryStat,
    ArcStagnation,
    ArcWindowSeries,
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
)
from flow_control.domain.element_state import (
    BaselineSource,
    HistoryTier,
    ObservationState,
    assess_elements,
)

NOW = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
E1 = EdgeID("e1")


def _graph(time_resolution_s: int = 60) -> Graph:
    a, b = NodeID("a"), NodeID("b")
    return Graph(
        nodes=(
            Node(node_id=a, kind=NodeKind.GOAL, enabled=True),
            Node(node_id=b, kind=NodeKind.GOAL, enabled=True),
        ),
        edges=(
            Edge(
                edge_id=E1,
                endpoint_a=a,
                endpoint_b=b,
                direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
                current_direction=CurrentDirection.BIDIRECTIONAL,
                enabled=True,
                observation_type=ObservationType.VECTOR,
                time_resolution_s=time_resolution_s,
            ),
        ),
    )


def _observed(
    flag: ConfidenceFlag = ConfidenceFlag.OK, *, observed_at: datetime = NOW
) -> Observations:
    return Observations(
        observed_at=observed_at,
        arc_flows=(ArcFlow(E1, FlowDirection.A_TO_B, 10.0, confidence_flag=flag),),
        arc_stagnations=(ArcStagnation(E1, 3.0, confidence_flag=flag),),
    )


def _window(stagnation_count: int, flow_count: int = 0) -> ArcWindowSeries:
    return ArcWindowSeries(
        edge_id=E1,
        flow_samples=tuple((NOW - timedelta(minutes=i + 1), 10.0) for i in range(flow_count)),
        stagnation_samples=tuple(
            (NOW - timedelta(minutes=i + 1), 1.0) for i in range(stagnation_count)
        ),
    )


ESTABLISHED = ArcHistoryStat(E1, p90_stagnation=2.0, baseline_stagnation=1.5)


@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        (Observations(observed_at=NOW), ObservationState.UNOBSERVED),
        (_observed(ConfidenceFlag.INVALID), ObservationState.INVALID),
        (_observed(ConfidenceFlag.HOLD), ObservationState.HOLD),
        (_observed(), ObservationState.OK),
        (
            replace(
                _observed(),
                arc_flows=(
                    ArcFlow(E1, FlowDirection.A_TO_B, 0.0, confidence_flag=ConfidenceFlag.INVALID),
                ),
                arc_stagnations=(),
            ),
            ObservationState.INVALID,
        ),
    ],
    ids=["no-observation", "invalid", "hold", "ok", "observation-shaped-invalid"],
)
def test_observation_state_comes_from_presence_and_the_worst_flag(observations, expected):
    states = assess_elements(_graph(), observations, HistoryDigest(), NOW)

    assert states[E1].observation is expected


@pytest.mark.parametrize(
    ("time_resolution_s", "lag", "expected"),
    [
        (60, timedelta(seconds=119), ObservationState.OK),
        (60, timedelta(seconds=120), ObservationState.STALE),
        (10, timedelta(seconds=59), ObservationState.OK),
        (10, timedelta(seconds=60), ObservationState.STALE),
    ],
    ids=["below-two-resolutions", "two-resolutions", "below-floor", "floor"],
)
def test_observation_is_stale_after_two_resolutions_or_the_floor(time_resolution_s, lag, expected):
    states = assess_elements(
        _graph(time_resolution_s), _observed(observed_at=NOW - lag), HistoryDigest(), NOW
    )

    assert states[E1].observation is expected


def test_stale_overrides_hold_but_not_invalid():
    old = NOW - timedelta(minutes=10)

    hold = assess_elements(
        _graph(), _observed(ConfidenceFlag.HOLD, observed_at=old), HistoryDigest(), NOW
    )
    invalid = assess_elements(
        _graph(), _observed(ConfidenceFlag.INVALID, observed_at=old), HistoryDigest(), NOW
    )

    assert hold[E1].observation is ObservationState.STALE
    assert invalid[E1].observation is ObservationState.INVALID


@pytest.mark.parametrize(
    ("stat", "stagnation_samples", "tier", "source"),
    [
        (None, 0, HistoryTier.NONE, BaselineSource.NONE),
        (None, 1, HistoryTier.NONE, BaselineSource.NONE),
        (None, 2, HistoryTier.WINDOW_ONLY, BaselineSource.WINDOW),
        (ArcHistoryStat(E1, available_span_hours=2.0), 3, HistoryTier.SHORT, BaselineSource.WINDOW),
        (
            replace(ESTABLISHED, available_span_hours=3.9),
            3,
            HistoryTier.SHORT,
            BaselineSource.HISTORY,
        ),
        (
            replace(ESTABLISHED, available_span_hours=4.0),
            3,
            HistoryTier.ESTABLISHED,
            BaselineSource.HISTORY,
        ),
        (ESTABLISHED, 0, HistoryTier.ESTABLISHED, BaselineSource.HISTORY),
        (ArcHistoryStat(E1, p90_stagnation=2.0), 0, HistoryTier.ESTABLISHED, BaselineSource.NONE),
    ],
    ids=[
        "nothing",
        "one-window-sample",
        "window-only",
        "p90-null",
        "span-under-4h",
        "span-4h",
        "window-empty",
        "no-baseline-anywhere",
    ],
)
def test_history_tier_and_baseline_source(stat, stagnation_samples, tier, source):
    history = HistoryDigest(
        arc_stats=() if stat is None else (stat,), window_series=(_window(stagnation_samples),)
    )

    state = assess_elements(_graph(), _observed(), history, NOW)[E1]

    assert (state.history, state.baseline_source) == (tier, source)


def test_window_empty_uses_the_history_baseline_as_the_recent_average():
    history = HistoryDigest(arc_stats=(ESTABLISHED,))

    basis = assess_elements(_graph(), _observed(), history, NOW)[E1].stagnation_basis()

    assert basis is not None
    assert (basis.recent, basis.baseline, basis.p90) == (1.5, 1.5, 2.0)


def test_p90_is_only_used_when_the_history_is_established():
    history = HistoryDigest(
        arc_stats=(replace(ESTABLISHED, available_span_hours=1.0),), window_series=(_window(3),)
    )

    basis = assess_elements(_graph(), _observed(), history, NOW)[E1].stagnation_basis()

    assert basis is not None
    assert basis.p90 is None


@pytest.mark.parametrize(
    ("flow_count", "points", "surge_judged"),
    [(0, 1, False), (1, 2, True), (5, 6, True)],
    ids=["current-only", "one-window-point", "window"],
)
def test_line_points_count_the_window_and_the_current_flow(flow_count, points, surge_judged):
    history = HistoryDigest(arc_stats=(ESTABLISHED,), window_series=(_window(3, flow_count),))

    state = assess_elements(_graph(), _observed(), history, NOW)[E1]

    assert state.line_points == points
    assert (state.surge_line() is not None) is surge_judged


def test_line_points_ignore_samples_outside_the_surge_window():
    history = HistoryDigest(
        window_series=(
            ArcWindowSeries(edge_id=E1, flow_samples=((NOW - timedelta(minutes=45), 10.0),)),
        )
    )

    state = assess_elements(_graph(), _observed(), history, NOW)[E1]

    assert state.line_points == 1


@pytest.mark.parametrize(
    "flag", [ConfidenceFlag.HOLD, ConfidenceFlag.INVALID], ids=["hold", "invalid"]
)
def test_frozen_or_invalid_values_are_not_judged(flag):
    history = HistoryDigest(arc_stats=(ESTABLISHED,), window_series=(_window(3, 5),))

    state = assess_elements(_graph(), _observed(flag), history, NOW)[E1]

    assert state.surge_line() is None
    assert state.stagnation_basis() is None
