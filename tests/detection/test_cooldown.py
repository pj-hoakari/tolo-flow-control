"""Tests for the cooldown gate

クールタイム判定テスト

- 危険フラグ（``DANGER``）はクールタイムを無視して即時発火する
- クールタイム中の通常トリガーはキューに蓄積し、蓄積スコア超過または
  起点アークの多様性超過で即時発火する
- 発火時はクールタイムを計時し直し、キュー事象を統合して単一トリガーとする
- クールタイム外でトリガーが無ければ未検出（``NO_TRIGGER``）
"""

from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import EvidenceSource, QueueExpiredEvidence
from flow_control.detection.state import (
    ArcWatchState,
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import (
    FiredTrigger,
    VerdictHint,
    evaluate_cooldown,
)
from flow_control.domain import EdgeID, NodeID


def _config(
    *,
    cooldown_min: float = 60.0,
    score_threshold: float = 5.0,
    diversity_threshold: int = 3,
) -> ResolvedConfig:
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=10.0,
        cooldown_duration_min=cooldown_min,
        queue_score_threshold=score_threshold,
        queue_diversity_threshold=diversity_threshold,
    )


def _surge(
    edge: str, at: datetime, *, score: float = 1.0, snapshot_ref: str | None = None
) -> FiredTrigger:
    return FiredTrigger(
        kind=QueuedTriggerKind.SURGE,
        fired_at=at,
        origin_edge_id=EdgeID(edge),
        score=score,
        snapshot_ref=snapshot_ref,
    )


def _danger_edge(edge: str, at: datetime) -> FiredTrigger:
    return FiredTrigger(
        kind=QueuedTriggerKind.DANGER,
        fired_at=at,
        origin_edge_id=EdgeID(edge),
    )


def _danger_node(node: str, at: datetime) -> FiredTrigger:
    return FiredTrigger(
        kind=QueuedTriggerKind.DANGER,
        fired_at=at,
        origin_node_id=NodeID(node),
    )


def _queued(edge: str, at: datetime, *, score: float) -> QueuedTrigger:
    return QueuedTrigger(
        kind=QueuedTriggerKind.SURGE,
        first_fired_at=at,
        last_fired_at=at,
        accumulated_score=score,
        origin_edge_id=EdgeID(edge),
    )


# ---------------------------------------------------------------------------
# クールタイム外
# ---------------------------------------------------------------------------


def test_no_trigger_when_not_in_cooldown_and_no_fire(base_time: datetime):
    state = DetectionState()

    result = evaluate_cooldown(state, (), base_time, _config())

    assert result.verdict == VerdictHint.NO_TRIGGER
    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()
    assert result.new_state.cooldown_until is None
    assert result.new_state.trigger_queue == ()


def test_normal_trigger_fires_and_starts_cooldown(base_time: datetime):
    state = DetectionState()

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.triggered_nodes == ()
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
    assert result.new_state.trigger_queue == ()


def test_danger_node_fires_and_starts_cooldown(base_time: datetime):
    state = DetectionState()

    result = evaluate_cooldown(state, (_danger_node("n1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == ()
    assert result.triggered_nodes == (NodeID("n1"),)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_multiple_normal_triggers_fire_distinct_edges_in_order(base_time: datetime):
    state = DetectionState()
    triggers = (
        _surge("e1", base_time),
        _surge("e2", base_time),
        _surge("e1", base_time),
    )

    result = evaluate_cooldown(state, triggers, base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"), EdgeID("e2"))


def test_cooldown_boundary_is_exclusive(base_time: datetime):
    # server_time == cooldown_until はクールタイム外（< 判定）
    state = DetectionState(cooldown_until=base_time)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED


# ---------------------------------------------------------------------------
# クールタイム中
# ---------------------------------------------------------------------------


def test_skipped_cooldown_when_in_cooldown_and_no_fire(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until)

    result = evaluate_cooldown(state, (), base_time, _config())

    assert result.verdict == VerdictHint.SKIPPED_COOLDOWN
    assert result.triggered_edges == ()
    assert result.new_state.cooldown_until == cooldown_until
    assert result.new_state.trigger_queue == ()


def test_queues_trigger_when_in_cooldown_below_thresholds(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until)
    config = _config(score_threshold=5.0, diversity_threshold=3)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, config)

    assert result.verdict == VerdictHint.QUEUED
    assert result.triggered_edges == ()
    # クールタイムは延長されない
    assert result.new_state.cooldown_until == cooldown_until
    assert len(result.new_state.trigger_queue) == 1
    entry = result.new_state.trigger_queue[0]
    assert entry.origin_edge_id == EdgeID("e1")
    assert entry.kind == QueuedTriggerKind.SURGE
    assert entry.accumulated_score == 1.0


def test_same_route_merges_into_single_queue_entry(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    earlier = base_time - timedelta(minutes=5)
    existing = _queued("e1", earlier, score=1.0)
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(existing,))
    config = _config(score_threshold=10.0, diversity_threshold=10)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, config)

    assert result.verdict == VerdictHint.QUEUED
    assert len(result.new_state.trigger_queue) == 1
    entry = result.new_state.trigger_queue[0]
    assert entry.accumulated_score == 2.0
    assert entry.first_fired_at == earlier  # 初回発火時刻を保持
    assert entry.last_fired_at == base_time  # 最終発火時刻を更新


def test_score_accumulation_fires_when_threshold_exceeded(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    existing = _queued("e1", base_time - timedelta(minutes=5), score=2.0)
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(existing,))
    # 既存 2.0 + 新規 1.0 = 3.0 > 2.5 → 即時発火
    config = _config(score_threshold=2.5, diversity_threshold=10)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, config)

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.new_state.trigger_queue == ()
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_diversity_exceeded_fires_in_cooldown(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    existing = _queued("e1", base_time - timedelta(minutes=5), score=1.0)
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(existing,))
    # 異なる起点アーク数 2 > 1 → 即時発火。スコアでは発火しない高い閾値にする
    config = _config(score_threshold=100.0, diversity_threshold=1)

    result = evaluate_cooldown(state, (_surge("e2", base_time),), base_time, config)

    assert result.verdict == VerdictHint.TRIGGERED
    # キューの起点（e1）に続いて今回分（e2）を統合
    assert result.triggered_edges == (EdgeID("e1"), EdgeID("e2"))
    assert result.new_state.trigger_queue == ()
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_danger_fires_during_cooldown_and_integrates_queue(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    q_e2 = _queued("e2", base_time - timedelta(minutes=5), score=1.0)
    q_e3 = _queued("e3", base_time - timedelta(minutes=5), score=1.0)
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(q_e2, q_e3))

    result = evaluate_cooldown(state, (_danger_edge("e1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED
    # キュー起点（e2, e3）を先に統合し、今回の危険フラグ起点（e1）を続ける
    assert result.triggered_edges == (EdgeID("e2"), EdgeID("e3"), EdgeID("e1"))
    assert result.new_state.trigger_queue == ()
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


# ---------------------------------------------------------------------------
# クールタイム明けのキュー統合発火
# ---------------------------------------------------------------------------


def test_queue_consolidates_and_fires_when_fresh_after_cooldown(base_time: datetime):
    # クールタイム外・新規トリガーなし・キュー残あり
    # 直近発火が鮮度ガード X 分（cooldown 60 / 2 = 30 分）以内 → 統合発火
    recent = _queued("e1", base_time - timedelta(minutes=10), score=1.0)
    state = DetectionState(cooldown_until=None, trigger_queue=(recent,))

    result = evaluate_cooldown(state, (), base_time, _config(cooldown_min=60.0))

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.new_state.trigger_queue == ()
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_queue_dropped_as_expired_when_stale_after_cooldown(base_time: datetime):
    # 鮮度ガード X 分（30 分）を超過し、警戒条件も満たさない → QUEUE_EXPIRED で破棄
    stale = _queued("e1", base_time - timedelta(minutes=40), score=1.0)
    state = DetectionState(cooldown_until=None, trigger_queue=(stale,))

    result = evaluate_cooldown(state, (), base_time, _config(cooldown_min=60.0))

    assert result.verdict == VerdictHint.NO_TRIGGER
    assert result.triggered_edges == ()
    assert result.new_state.trigger_queue == ()
    assert len(result.evidences) == 1
    evidence = result.evidences[0]
    assert isinstance(evidence, QueueExpiredEvidence)
    assert evidence.dropped_count == 1


def test_stale_queue_still_fires_when_arc_in_watch_condition(base_time: datetime):
    # 鮮度ガード時間は超過しているが、キュー対象アークが現時点で警戒条件を満たす → 統合発火
    stale = _queued("e1", base_time - timedelta(minutes=40), score=1.0)
    state = DetectionState(cooldown_until=None, trigger_queue=(stale,))

    result = evaluate_cooldown(
        state,
        (),
        base_time,
        _config(cooldown_min=60.0),
        watched_edges=frozenset({EdgeID("e1")}),
    )

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.new_state.trigger_queue == ()


def test_queue_freshness_min_overrides_default(base_time: datetime):
    # queue_freshness_min を明示すると cooldown/2 ではなくその値で判定する
    entry = _queued("e1", base_time - timedelta(minutes=10), score=1.0)
    state = DetectionState(cooldown_until=None, trigger_queue=(entry,))
    config = ResolvedConfig(
        surge_rate_threshold_percent_per_min=10.0,
        cooldown_duration_min=60.0,
        queue_freshness_min=5.0,  # 5 分。直近発火は 10 分前 → 鮮度切れ
    )

    result = evaluate_cooldown(state, (), base_time, config)

    assert result.verdict == VerdictHint.NO_TRIGGER
    assert result.evidences[0].source == EvidenceSource.QUEUE_EXPIRED


# ---------------------------------------------------------------------------
# abort_state（発火副作用を含まない遷移候補）
# ---------------------------------------------------------------------------


def test_abort_state_keeps_cooldown_unset_on_fresh_fire(base_time: datetime):
    # クールタイム外の発火: new_state は計時し直すが abort_state は据え置き
    state = DetectionState()

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.TRIGGERED
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
    assert result.abort_state is not None
    assert result.abort_state.cooldown_until is None
    assert result.abort_state.trigger_queue == ()


def test_abort_state_excludes_fire_side_effects_on_queue_fire(base_time: datetime):
    # キュースコア超過による発火
    cooldown_until = base_time + timedelta(minutes=30)
    existing = _queued("e1", base_time - timedelta(minutes=5), score=2.0)
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(existing,))
    config = _config(score_threshold=2.5, diversity_threshold=10)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, config)

    assert result.verdict == VerdictHint.TRIGGERED
    # new_state: 発火副作用適用（cooldown 計時し直し・キュー消化）
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
    assert result.new_state.trigger_queue == ()
    # abort_state: 発火副作用なし（cooldown 据え置き・キューは統合済みだが消化しない）
    assert result.abort_state is not None
    assert result.abort_state.cooldown_until == cooldown_until
    assert len(result.abort_state.trigger_queue) == 1
    assert result.abort_state.trigger_queue[0].accumulated_score == 3.0


def test_abort_state_equals_new_state_when_queued(base_time: datetime):
    # 発火しない verdict では abort_state は new_state と等価
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until)
    config = _config(score_threshold=5.0, diversity_threshold=3)

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, config)

    assert result.verdict == VerdictHint.QUEUED
    assert result.abort_state == result.new_state


# ---------------------------------------------------------------------------
# 状態の保全
# ---------------------------------------------------------------------------


def test_arc_watch_states_are_preserved_on_fire(base_time: datetime):
    watch = ArcWatchState(edge_id=EdgeID("e9"), percentile_breached=True)
    state = DetectionState(arc_watch_states=(watch,))

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, _config())

    assert result.new_state.arc_watch_states == (watch,)


def test_arc_watch_states_are_preserved_when_queued(base_time: datetime):
    watch = ArcWatchState(edge_id=EdgeID("e9"), delta_breached=True)
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until, arc_watch_states=(watch,))

    result = evaluate_cooldown(state, (_surge("e1", base_time),), base_time, _config())

    assert result.verdict == VerdictHint.QUEUED
    assert result.new_state.arc_watch_states == (watch,)


# ---------------------------------------------------------------------------
# snapshot_ref（キュー最終発火時点の参照）
# ---------------------------------------------------------------------------


def test_queued_trigger_records_snapshot_ref(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until)
    config = _config(score_threshold=5.0, diversity_threshold=3)

    result = evaluate_cooldown(
        state, (_surge("e1", base_time, snapshot_ref="snap-1"),), base_time, config
    )

    assert result.verdict == VerdictHint.QUEUED
    assert result.new_state.trigger_queue[0].snapshot_ref == "snap-1"


def test_same_route_merge_updates_snapshot_ref_to_latest(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    existing = QueuedTrigger(
        kind=QueuedTriggerKind.SURGE,
        first_fired_at=base_time - timedelta(minutes=5),
        last_fired_at=base_time - timedelta(minutes=5),
        accumulated_score=1.0,
        origin_edge_id=EdgeID("e1"),
        snapshot_ref="snap-old",
    )
    state = DetectionState(cooldown_until=cooldown_until, trigger_queue=(existing,))
    config = _config(score_threshold=10.0, diversity_threshold=10)

    result = evaluate_cooldown(
        state, (_surge("e1", base_time, snapshot_ref="snap-new"),), base_time, config
    )

    assert result.verdict == VerdictHint.QUEUED
    entry = result.new_state.trigger_queue[0]
    # 最終発火時刻の更新に合わせて snapshot_ref も最新へ
    assert entry.last_fired_at == base_time
    assert entry.snapshot_ref == "snap-new"
