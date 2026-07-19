"""Tests for detect() wiring

detect() 結線テスト

通常トリガー（組合せ発火: established 停滞 AND 需要警戒）、手動トリガー（危険フラグ）、
クールタイム判定を結線した検知エントリポイントの結合挙動を検証する。
"""

from dataclasses import replace
from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import DetectionResult, detect
from flow_control.detection.state import (
    DetectionState,
    QueuedTriggerKind,
    RetriggerEntry,
)
from flow_control.detection.triggers import Event, EventKind, VerdictHint
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


def _danger_up(target_id: str, at: datetime) -> Event:
    return Event(kind=EventKind.DANGER_FLAG_UP, target_id=target_id, occurred_at=at)


# ---------------------------------------------------------------------------
# クールタイム外
# ---------------------------------------------------------------------------


def test_no_trigger_when_quiet(
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

    assert isinstance(result, DetectionResult)
    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()
    assert result.new_state.cooldown_until is None
    assert result.effective_snapshot is observations


def test_combined_trigger_fires_and_starts_cooldown(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    history, observations, previous = make_combined_firing(edge_id, base_time)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(cooldown_min=60.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (edge_id,)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
    assert result.new_state.trigger_queue == ()


def test_abort_state_excludes_fire_side_effects_on_trigger(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # TRIGGERED 時、new_state は発火副作用を反映するが abort_state は除外する
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(
        fire_state,
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=2),),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(cooldown_min=60.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    # new_state: cooldown 計時・再発火カウント加算
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
    new_entry = result.new_state.retrigger_entry_of(edge_id)
    assert new_entry is not None and new_entry.count == 3
    # abort_state: cooldown 据え置き・再発火カウント加算なし
    assert result.abort_state.cooldown_until is None
    abort_entry = result.abort_state.retrigger_entry_of(edge_id)
    assert abort_entry is not None and abort_entry.count == 2


def test_danger_flag_fires_for_node(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # 通常トリガーは発火しない静穏な入力。危険フラグのみで発火
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=DetectionState(),
        events=(_danger_up("node:n1", base_time),),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == ()
    assert result.triggered_nodes == (NodeID("n1"),)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


# ---------------------------------------------------------------------------
# クールタイム中
# ---------------------------------------------------------------------------


def test_trigger_in_cooldown_is_queued(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    cooldown_until = base_time + timedelta(minutes=30)
    previous = replace(fire_state, cooldown_until=cooldown_until)

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
    assert result.triggered_edges == ()
    # クールタイムは延長されない
    assert result.new_state.cooldown_until == cooldown_until
    assert len(result.new_state.trigger_queue) == 1
    entry = result.new_state.trigger_queue[0]
    assert entry.origin_edge_id == edge_id
    # 組合せ発火の kind は HIGH_STAGNATION
    assert entry.kind == QueuedTriggerKind.HIGH_STAGNATION


def test_queued_trigger_carries_observation_snapshot_ref(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # observations.snapshot_ref がキューエントリの snapshot_ref へ伝播
    history, observations, fire_state = make_combined_firing(
        edge_id, base_time, snapshot_ref="snap-42"
    )
    previous = replace(
        fire_state, cooldown_until=base_time + timedelta(minutes=30)
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
    assert result.new_state.trigger_queue[0].snapshot_ref == "snap-42"
    # effective_snapshot は当該リクエストの観測 = 最後の発火時点
    assert result.effective_snapshot is observations


def test_danger_in_cooldown_fires_immediately(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    cooldown_until = base_time + timedelta(minutes=30)
    previous = DetectionState(cooldown_until=cooldown_until)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_danger_up("edge:e1", base_time),),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (edge_id,)
    # 即時発火でクールタイムは計時し直される
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_skipped_cooldown_when_quiet_in_cooldown(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    cooldown_until = base_time + timedelta(minutes=30)
    previous = DetectionState(cooldown_until=cooldown_until)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.SKIPPED_COOLDOWN
    assert result.triggered_edges == ()
    assert result.new_state.cooldown_until == cooldown_until


def test_high_stagnation_fires_through_detect(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # established 停滞 ＋ ライン急増 の組合せ発火が detect を通して発火する
    history, observations, previous = make_combined_firing(edge_id, base_time)

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
    assert result.triggered_edges == (edge_id,)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
