"""Tests for detect() wiring

detect() 結線テスト

通常トリガー（急増・高停滞）、手動トリガー（危険フラグ）、クールタイム判定を結線した検知エントリポイントの結合挙動を検証
"""

from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import DetectionResult, detect
from flow_control.detection.state import (
    ArcWatchState,
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
        cooldown_duration_min=cooldown_min,
        queue_score_threshold=score_threshold,
        queue_diversity_threshold=diversity_threshold,
    )


def _surge_inputs(
    edge_id: EdgeID, base_time: datetime, make_linear_series
) -> tuple[HistoryDigest, Observations]:
    """slope=10/min, mean=50 → 20 %/min"""
    window, scalar_flow = make_linear_series(
        edge_id,
        observed_at=base_time,
        sample_count=11,
        start_value=0.0,
        slope_per_min=10.0,
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(observed_at=base_time, arc_scalar_flows=(scalar_flow,))
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
    make_flat_series,
):
    window, scalar_flow = make_flat_series(
        edge_id, observed_at=base_time, sample_count=11, value=100.0
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(observed_at=base_time, arc_scalar_flows=(scalar_flow,))

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


def test_surge_fires_and_starts_cooldown(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_linear_series,
):
    history, observations = _surge_inputs(edge_id, base_time, make_linear_series)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=DetectionState(),
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
    make_linear_series,
):
    # TRIGGERED 時、new_state は発火副作用を反映するが abort_state は除外する
    history, observations = _surge_inputs(edge_id, base_time, make_linear_series)
    previous = DetectionState(
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=2),)
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
    make_flat_series,
):
    # 通常トリガーは発火しない平坦な系列
    # 危険フラグのみで発火
    window, scalar_flow = make_flat_series(
        edge_id, observed_at=base_time, sample_count=11, value=100.0
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(observed_at=base_time, arc_scalar_flows=(scalar_flow,))

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


def test_surge_in_cooldown_is_queued(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_linear_series,
):
    history, observations = _surge_inputs(edge_id, base_time, make_linear_series)
    cooldown_until = base_time + timedelta(minutes=30)
    previous = DetectionState(cooldown_until=cooldown_until)

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
    assert entry.kind == QueuedTriggerKind.SURGE


def test_queued_trigger_carries_observation_snapshot_ref(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_linear_series,
):
    # observations.snapshot_ref がキューエントリの snapshot_ref へ伝播
    window, scalar_flow = make_linear_series(
        edge_id,
        observed_at=base_time,
        sample_count=11,
        start_value=0.0,
        slope_per_min=10.0,
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(
        observed_at=base_time,
        snapshot_ref="snap-42",
        arc_scalar_flows=(scalar_flow,),
    )
    previous = DetectionState(cooldown_until=base_time + timedelta(minutes=30))

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
    make_flat_series,
):
    window, scalar_flow = make_flat_series(
        edge_id, observed_at=base_time, sample_count=11, value=100.0
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(observed_at=base_time, arc_scalar_flows=(scalar_flow,))
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
    make_flat_series,
):
    window, scalar_flow = make_flat_series(
        edge_id, observed_at=base_time, sample_count=11, value=100.0
    )
    history = HistoryDigest(window_series=(window,))
    observations = Observations(observed_at=base_time, arc_scalar_flows=(scalar_flow,))
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
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # 両条件を M 分継続している警戒状態から高停滞で発火する
    history = make_history_with_arc_stats((edge_id, 5.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=edge_id,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=6),
            ),
        )
    )
    config = _config(surge_threshold=1_000.0)  # 急増は発火させない

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=config,
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (edge_id,)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)
