"""Tests for trigger evidences and consecutive_skip_count

診断情報テスト

- 検出した各トリガーの TriggerEvidence を収集する
  （SURGE / HIGH_STAGNATION / DANGER / QUEUE_SCORE / QUEUE_DIVERSITY）
- consecutive_skip_count は Detection では一切変更しない（リセット／加算は finalize 責務）
"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TypeVar

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import detect
from flow_control.detection.diagnostics import (
    DangerEvidence,
    HighStagnationEvidence,
    QueueDiversityEvidence,
    QueueScoreEvidence,
    SurgeEvidence,
    TriggerEvidence,
)
from flow_control.detection.state import (
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import (
    Event,
    EventKind,
    FiredTrigger,
    VerdictHint,
    evaluate_cooldown,
)
from flow_control.domain import EdgeID, Graph, NodeID
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import Observations


def _config(
    *,
    surge_threshold: float = 10.0,
    cooldown_min: float = 60.0,
    score_threshold: float = 5.0,
    diversity_threshold: int = 3,
) -> ResolvedConfig:
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=surge_threshold,
        high_stagnation_duration_min=5.0,
        beta=1.0,
        cooldown_duration_min=cooldown_min,
        queue_score_threshold=score_threshold,
        queue_diversity_threshold=diversity_threshold,
    )


def _quiet_inputs(
    edge_id: EdgeID, base_time: datetime, make_flat_line_history
) -> tuple[HistoryDigest, Observations]:
    """平坦ライン・停滞観測なし → 通常トリガーが発火しない静穏入力"""
    history = make_flat_line_history(edge_id, base_time)
    observations = Observations(observed_at=base_time)
    return history, observations


_E = TypeVar("_E")


def _evidences_of[E](evidences: tuple[TriggerEvidence, ...], evidence_type: type[E]) -> list[E]:
    return [e for e in evidences if isinstance(e, evidence_type)]


def _queued(edge: str, at: datetime, *, score: float) -> QueuedTrigger:
    return QueuedTrigger(
        kind=QueuedTriggerKind.SURGE,
        first_fired_at=at,
        last_fired_at=at,
        accumulated_score=score,
        origin_edge_id=EdgeID(edge),
    )


# ---------------------------------------------------------------------------
# TriggerEvidence: 通常トリガー / 危険フラグ（detect 結線）
# ---------------------------------------------------------------------------


def test_surge_evidence(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # 組合せ発火（停滞 established ＋ ライン急増）で急増根拠が付与される
    history, observations, previous = make_combined_firing(edge_id, base_time)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(surge_threshold=10.0),
        server_time=base_time,
    )

    surge = _evidences_of(result.evidences, SurgeEvidence)
    assert len(surge) == 1
    assert surge[0].edge_id == edge_id
    assert surge[0].threshold_percent_per_min == 10.0
    assert surge[0].rate_percent_per_min > 10.0
    assert surge[0].occurred_at == base_time


def test_high_stagnation_evidence(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # 組合せ発火時に停滞根拠（p90 あり）が付与される
    history, observations, previous = make_combined_firing(edge_id, base_time)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(surge_threshold=10.0),
        server_time=base_time,
    )

    stag = _evidences_of(result.evidences, HighStagnationEvidence)
    assert len(stag) == 1
    assert stag[0].edge_id == edge_id
    assert stag[0].stagnation == 15.0
    assert stag[0].percentile_threshold == 5.0
    assert stag[0].duration_min == 5.0


def test_danger_evidence_for_node(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=DetectionState(),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="node:n1",
                occurred_at=base_time,
            ),
        ),
        config=_config(),
        server_time=base_time,
    )

    danger = _evidences_of(result.evidences, DangerEvidence)
    assert len(danger) == 1
    assert danger[0].node_id == NodeID("n1")
    assert danger[0].edge_id is None


def test_no_evidence_when_no_trigger(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=DetectionState(),
        events=(),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    assert result.evidences == ()


# ---------------------------------------------------------------------------
# TriggerEvidence: キュー発火（evaluate_cooldown 単体）
# ---------------------------------------------------------------------------


def test_queue_score_fire_emits_evidence(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(
        cooldown_until=cooldown_until,
        trigger_queue=(_queued("e1", base_time - timedelta(minutes=5), score=2.0),),
    )
    config = _config(score_threshold=2.5, diversity_threshold=10)
    fired = (
        FiredTrigger(
            kind=QueuedTriggerKind.SURGE,
            fired_at=base_time,
            origin_edge_id=EdgeID("e1"),
            score=1.0,
        ),
    )

    decision = evaluate_cooldown(state, fired, base_time, config)

    assert decision.verdict == VerdictHint.TRIGGERED
    score = _evidences_of(decision.evidences, QueueScoreEvidence)
    assert len(score) == 1
    assert score[0].accumulated_score == 3.0  # 2.0 + 1.0
    assert score[0].score_threshold == 2.5
    # スコアのみ超過、多様性は超過しない
    assert _evidences_of(decision.evidences, QueueDiversityEvidence) == []


def test_queue_diversity_fire_emits_evidence(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(
        cooldown_until=cooldown_until,
        trigger_queue=(_queued("e1", base_time - timedelta(minutes=5), score=1.0),),
    )
    config = _config(score_threshold=100.0, diversity_threshold=1)
    fired = (
        FiredTrigger(
            kind=QueuedTriggerKind.SURGE,
            fired_at=base_time,
            origin_edge_id=EdgeID("e2"),
            score=1.0,
        ),
    )

    decision = evaluate_cooldown(state, fired, base_time, config)

    assert decision.verdict == VerdictHint.TRIGGERED
    diversity = _evidences_of(decision.evidences, QueueDiversityEvidence)
    assert len(diversity) == 1
    assert diversity[0].distinct_origin_count == 2  # 異なる起点アーク e1, e2
    assert diversity[0].diversity_threshold == 1
    assert _evidences_of(decision.evidences, QueueScoreEvidence) == []


# ---------------------------------------------------------------------------
# consecutive_skip_count
# ---------------------------------------------------------------------------


def test_consecutive_skip_count_untouched_on_trigger(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # Detection は consecutive_skip_count に触れない
    # （発火時の 0 リセットは finalize の責務）
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(fire_state, consecutive_skip_count=5)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.new_state.consecutive_skip_count == 5


def test_consecutive_skip_count_preserved_when_no_trigger(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    previous = DetectionState(consecutive_skip_count=5)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    # Detection モジュールではインクリメントしない
    assert result.new_state.consecutive_skip_count == 5


def test_consecutive_skip_count_preserved_when_queued(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(
        fire_state,
        cooldown_until=base_time + timedelta(minutes=30),
        consecutive_skip_count=5,
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(score_threshold=5.0, diversity_threshold=3),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.QUEUED
    assert result.new_state.consecutive_skip_count == 5
