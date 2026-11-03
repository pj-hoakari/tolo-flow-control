from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import PunctureEvidence, SkippedJudgements
from flow_control.detection.state import DetectionState, QueuedTriggerKind
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import EdgeID, FlowDirection, Graph
from flow_control.domain.element_state import Judgement, assess_elements
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from flow_control.domain.observations import ArcFlow, ArcStagnation, ConfidenceFlag, Observations

FLOWS = (40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 100.0, 100.0, 100.0, 100.0)
STAGNATIONS = (10.0, 10.0, 11.0, 12.0, 14.0, 17.0, 20.0, 30.0, 40.0, 50.0, 60.0)
FLOW_P90 = 90.0
FREE_FLOW_DWELL_MIN = 0.25

ENABLED = ResolvedConfig(
    surge_rate_threshold_percent_per_min=1_000.0, puncture_trigger_enabled=True
)


def _stat(edge_id: EdgeID, gain: float = 1.0) -> ArcHistoryStat:
    return ArcHistoryStat(
        edge_id,
        p90_stagnation=50.0 * gain,
        baseline_stagnation=10.0 * gain,
        flow_p90=FLOW_P90 * gain,
        free_flow_dwell_min=FREE_FLOW_DWELL_MIN,
    )


def _detect(
    graph: Graph,
    edge_id: EdgeID,
    now: datetime,
    *,
    flows: tuple[float, ...] = FLOWS,
    stagnations: tuple[float, ...] = STAGNATIONS,
    stat: ArcHistoryStat | None = None,
    flag: ConfidenceFlag = ConfidenceFlag.OK,
    observed_ago_min: int = 0,
    config: ResolvedConfig = ENABLED,
):
    times = [now - timedelta(minutes=len(flows) - 1 - i) for i in range(len(flows))]
    history = HistoryDigest(
        arc_stats=(stat if stat is not None else _stat(edge_id),),
        window_series=(
            ArcWindowSeries(
                edge_id,
                flow_samples=tuple(zip(times[:-1], flows[:-1], strict=True)),
                stagnation_samples=tuple(zip(times[:-1], stagnations[:-1], strict=True)),
            ),
        ),
    )
    observations = Observations(
        observed_at=now - timedelta(minutes=observed_ago_min),
        arc_flows=(ArcFlow(edge_id, FlowDirection.A_TO_B, flows[-1], confidence_flag=flag),),
        arc_stagnations=(ArcStagnation(edge_id, stagnations[-1], confidence_flag=flag),),
    )
    return detect_metric_triggers(
        graph=graph,
        observations=observations,
        element_states=assess_elements(graph, observations, history, now),
        previous_state=DetectionState(),
        server_time=now,
        config=config,
    )


def _skipped(result) -> set[Judgement]:
    return {j for item in result.skipped for j in item.judgements}


@pytest.mark.parametrize("gain", [0.5, 1.0, 2.0])
def test_fires_when_flow_reaches_its_p90_and_dwell_stretches_at_any_common_gain(
    base_time: datetime, basic_graph: Graph, edge_id: EdgeID, gain: float
):
    result = _detect(
        basic_graph,
        edge_id,
        base_time,
        flows=tuple(gain * q for q in FLOWS),
        stagnations=tuple(gain * s for s in STAGNATIONS),
        stat=_stat(edge_id, gain),
    )

    assert result.triggered_edges == (edge_id,)
    (trigger,) = result.fired_triggers
    assert trigger.kind is QueuedTriggerKind.PUNCTURE
    assert trigger.score == pytest.approx(1.8 / 1.5)
    (evidence,) = result.evidences
    assert isinstance(evidence, PunctureEvidence)
    assert (evidence.edge_id, evidence.flow_p90, evidence.dwell_ratio_threshold) == (
        edge_id,
        FLOW_P90 * gain,
        1.5,
    )
    assert (evidence.flow, evidence.dwell_ratio) == pytest.approx((100.0 * gain, 1.8))
    assert result.skipped == ()


def test_dwell_at_low_flow_is_not_a_puncture(
    base_time: datetime, basic_graph: Graph, edge_id: EdgeID
):
    result = _detect(
        basic_graph,
        edge_id,
        base_time,
        flows=(10.0,) * len(FLOWS),
        stagnations=(20.0,) * len(STAGNATIONS),
    )

    assert result.fired_triggers == ()
    assert result.skipped == ()


def test_zero_flow_is_not_a_puncture(base_time: datetime, basic_graph: Graph, edge_id: EdgeID):
    result = _detect(
        basic_graph,
        edge_id,
        base_time,
        flows=(0.0,) * len(FLOWS),
        stat=replace(_stat(edge_id), flow_p90=0.0),
    )

    assert result.fired_triggers == ()
    assert Judgement.PUNCTURE not in _skipped(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"flow_p90": None},
        {"free_flow_dwell_min": None},
        {"available_span_hours": 2.0},
    ],
    ids=["no-flow-p90", "no-free-flow-dwell", "history-short"],
)
def test_puncture_is_undeterminable_without_established_history_fields(
    base_time: datetime, basic_graph: Graph, edge_id: EdgeID, overrides: dict[str, float | None]
):
    result = _detect(basic_graph, edge_id, base_time, stat=replace(_stat(edge_id), **overrides))

    assert result.fired_triggers == ()
    assert result.skipped == (SkippedJudgements(edge_id, frozenset({Judgement.PUNCTURE})),)


@pytest.mark.parametrize(
    ("flag", "observed_ago_min"),
    [(ConfidenceFlag.HOLD, 0), (ConfidenceFlag.OK, 10)],
    ids=["hold", "stale"],
)
def test_puncture_is_undeterminable_when_the_observation_is_frozen_or_old(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    flag: ConfidenceFlag,
    observed_ago_min: int,
):
    result = _detect(
        basic_graph,
        edge_id,
        base_time,
        flag=flag,
        observed_ago_min=observed_ago_min,
    )

    assert result.fired_triggers == ()
    assert Judgement.PUNCTURE in _skipped(result)


def test_puncture_is_disabled_by_default(base_time: datetime, basic_graph: Graph, edge_id: EdgeID):
    result = _detect(
        basic_graph,
        edge_id,
        base_time,
        config=ResolvedConfig(surge_rate_threshold_percent_per_min=1_000.0),
    )

    assert result.fired_triggers == ()
    assert result.skipped == ()
