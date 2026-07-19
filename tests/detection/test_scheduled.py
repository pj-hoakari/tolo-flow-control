"""Tests for scheduled event application

スケジュールイベント適用テスト

- SCHEDULED_INFLOW / SCHEDULED_ATTR_CHANGE はクールタイムをリセットする
- リセット時点ではキューを保持する（発火副作用なし）
- 状態変化そのものはトリガー発火扱いとしない
- リセット後に通常トリガーが重複した場合は即時発火しクールタイムを計時し直す
- リセットでクールタイム解除後は、保持キューが鮮度ガードを満たせば統合発火する
"""

from dataclasses import replace
from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import detect
from flow_control.detection.state import (
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import (
    Event,
    EventKind,
    VerdictHint,
    apply_scheduled_events,
)
from flow_control.domain import EdgeID, Graph
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import Observations


def _config(
    *, surge_threshold: float = 10.0, cooldown_min: float = 60.0
) -> ResolvedConfig:
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=surge_threshold,
        high_stagnation_duration_min=5.0,
        beta=1.0,
        cooldown_duration_min=cooldown_min,
    )


def _quiet_inputs(
    edge_id: EdgeID, base_time: datetime, make_flat_line_history
) -> tuple[HistoryDigest, Observations]:
    """平坦ライン・停滞観測なし → 通常トリガーが発火しない静穏入力"""
    history = make_flat_line_history(edge_id, base_time)
    observations = Observations(observed_at=base_time)
    return history, observations


def _scheduled(target_id: str, at: datetime) -> Event:
    return Event(kind=EventKind.SCHEDULED_INFLOW, target_id=target_id, occurred_at=at)


def _queued(edge: str, at: datetime, *, score: float = 1.0) -> QueuedTrigger:
    return QueuedTrigger(
        kind=QueuedTriggerKind.SURGE,
        first_fired_at=at,
        last_fired_at=at,
        accumulated_score=score,
        origin_edge_id=EdgeID(edge),
    )


# ---------------------------------------------------------------------------
# apply_scheduled_events
# ---------------------------------------------------------------------------


def test_scheduled_event_resets_cooldown(base_time: datetime):
    state = DetectionState(cooldown_until=base_time + timedelta(minutes=30))

    result = apply_scheduled_events(state, (_scheduled("node:n1", base_time),))

    assert result.cooldown_until is None


def test_scheduled_attr_change_resets_cooldown(base_time: datetime):
    state = DetectionState(cooldown_until=base_time + timedelta(minutes=30))
    event = Event(
        kind=EventKind.SCHEDULED_ATTR_CHANGE,
        target_id="edge:e1",
        occurred_at=base_time,
    )

    result = apply_scheduled_events(state, (event,))

    assert result.cooldown_until is None


def test_scheduled_event_preserves_queue(base_time: datetime):
    queued = _queued("e1", base_time - timedelta(minutes=5))
    state = DetectionState(
        cooldown_until=base_time + timedelta(minutes=30),
        trigger_queue=(queued,),
    )

    result = apply_scheduled_events(state, (_scheduled("node:n1", base_time),))

    assert result.cooldown_until is None
    assert result.trigger_queue == (queued,)


def test_non_scheduled_events_do_not_reset_cooldown(base_time: datetime):
    cooldown_until = base_time + timedelta(minutes=30)
    state = DetectionState(cooldown_until=cooldown_until)
    events = (
        Event(
            kind=EventKind.DANGER_FLAG_UP, target_id="edge:e1", occurred_at=base_time
        ),
        Event(kind=EventKind.ENABLE, target_id="edge:e2", occurred_at=base_time),
        Event(kind=EventKind.DISABLE, target_id="edge:e3", occurred_at=base_time),
    )

    result = apply_scheduled_events(state, events)

    assert result is state


def test_returns_same_state_when_no_cooldown(base_time: datetime):
    state = DetectionState()

    result = apply_scheduled_events(state, (_scheduled("node:n1", base_time),))

    assert result is state


# ---------------------------------------------------------------------------
# detect() 結線
# ---------------------------------------------------------------------------


def test_detect_scheduled_only_clears_cooldown_without_firing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # スケジュールイベントのみ（トリガーなし）→ 発火扱いせずクールタイムを解除
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    previous = DetectionState(cooldown_until=base_time + timedelta(minutes=30))

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_scheduled("node:n1", base_time),),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    assert result.triggered_edges == ()
    assert result.new_state.cooldown_until is None


def test_detect_scheduled_reset_consolidates_fresh_queue(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # スケジュールでクールタイムを解除した後、保持された新鮮なキュー
    # （直近発火 5 分前 <= 鮮度ガード 30 分）は新規トリガーが無くても統合発火する
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    queued = _queued("e1", base_time - timedelta(minutes=5))
    previous = DetectionState(
        cooldown_until=base_time + timedelta(minutes=30),
        trigger_queue=(queued,),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_scheduled("node:n1", base_time),),
        config=_config(cooldown_min=60.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.new_state.trigger_queue == ()
    # 統合発火でクールタイムを計時し直す
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_detect_scheduled_reset_drops_stale_queue_as_expired(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # クールタイム解除後、保持キューが鮮度切れ（直近発火 40 分前 > 30 分）かつ
    # 警戒条件も満たさない → QUEUE_EXPIRED で破棄し未検出
    history, observations = _quiet_inputs(edge_id, base_time, make_flat_line_history)
    queued = _queued("e1", base_time - timedelta(minutes=40))
    previous = DetectionState(
        cooldown_until=base_time + timedelta(minutes=30),
        trigger_queue=(queued,),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_scheduled("node:n1", base_time),),
        config=_config(cooldown_min=60.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    assert result.new_state.cooldown_until is None
    assert result.new_state.trigger_queue == ()


def test_detect_scheduled_reset_lets_concurrent_surge_fire_immediately(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # クールタイム中でも、スケジュールイベントでリセットされた直後に重複した
    # 通常トリガーは即時発火し、クールタイムを計時し直す
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(fire_state, cooldown_until=base_time + timedelta(minutes=30))

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_scheduled("node:n1", base_time),),
        config=_config(cooldown_min=60.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (edge_id,)
    assert result.new_state.cooldown_until == base_time + timedelta(minutes=60.0)


def test_detect_scheduled_reset_integrates_preserved_queue_on_fire(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # リセットで保持されたキュー（e2）は、今回の通常トリガー（e1）発火時に統合される
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    queued = _queued("e2", base_time - timedelta(minutes=5))
    previous = replace(
        fire_state,
        cooldown_until=base_time + timedelta(minutes=30),
        trigger_queue=(queued,),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_scheduled("node:n1", base_time),),
        config=_config(),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    # 保持キュー起点 e2 を先に統合し、今回発火の e1 を続ける
    assert result.triggered_edges == (EdgeID("e2"), edge_id)
    assert result.new_state.trigger_queue == ()
