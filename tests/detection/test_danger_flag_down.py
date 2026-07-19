"""Tests for danger flag down

危険フラグ立ち下げテスト

- DANGER_FLAG_DOWN を受けたアークの再発火カウントをリセット
- 立ち下げ自体はトリガー発火扱いとせず、クールタイムリセットも行わない
- ノード対象や未登録アークには影響しない
"""

from dataclasses import replace
from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import detect
from flow_control.detection.state import DetectionState, RetriggerEntry
from flow_control.detection.triggers import (
    Event,
    EventKind,
    VerdictHint,
    apply_danger_flag_down,
)
from flow_control.domain import EdgeID, Graph
from flow_control.domain.observations import Observations


def _down(target_id: str, at: datetime) -> Event:
    return Event(kind=EventKind.DANGER_FLAG_DOWN, target_id=target_id, occurred_at=at)


def _state(*entries: RetriggerEntry) -> DetectionState:
    return DetectionState(arc_retrigger_counts=entries)


def _entry_of(state: DetectionState, edge: str) -> RetriggerEntry | None:
    return state.retrigger_entry_of(EdgeID(edge))


# ---------------------------------------------------------------------------
# apply_danger_flag_down 単体
# ---------------------------------------------------------------------------


def test_zeroes_count_for_cleared_edge(base_time: datetime):
    state = _state(
        RetriggerEntry(
            edge_id=EdgeID("e1"),
            count=3,
            quiet_cycles=1,
            last_fired_at=base_time - timedelta(minutes=5),
        ),
    )

    result = apply_danger_flag_down(state, (_down("edge:e1", base_time),))

    entry = _entry_of(result, "e1")
    assert entry is not None
    assert entry.count == 0
    assert entry.quiet_cycles == 0
    # last_fired_at は保持する
    assert entry.last_fired_at == base_time - timedelta(minutes=5)


def test_only_clears_targeted_edge(base_time: datetime):
    state = _state(
        RetriggerEntry(edge_id=EdgeID("e1"), count=3),
        RetriggerEntry(edge_id=EdgeID("e2"), count=2),
    )

    result = apply_danger_flag_down(state, (_down("edge:e1", base_time),))

    e1 = _entry_of(result, "e1")
    e2 = _entry_of(result, "e2")
    assert e1 is not None and e1.count == 0
    assert e2 is not None and e2.count == 2


def test_no_danger_down_returns_same_state(base_time: datetime):
    state = _state(RetriggerEntry(edge_id=EdgeID("e1"), count=3))

    result = apply_danger_flag_down(
        state,
        (Event(kind=EventKind.ENABLE, target_id="edge:e1", occurred_at=base_time),),
    )

    assert result is state


def test_node_target_does_not_affect_counts(base_time: datetime):
    state = _state(RetriggerEntry(edge_id=EdgeID("e1"), count=3))

    result = apply_danger_flag_down(state, (_down("node:n1", base_time),))

    assert result is state


def test_unregistered_edge_does_not_create_entry(base_time: datetime):
    state = _state(RetriggerEntry(edge_id=EdgeID("e1"), count=3))

    result = apply_danger_flag_down(state, (_down("edge:e9", base_time),))

    # e9 のエントリは作られず、既存も不変
    assert result is state
    assert _entry_of(result, "e9") is None


def test_already_zero_entry_is_unchanged(base_time: datetime):
    state = _state(RetriggerEntry(edge_id=EdgeID("e1"), count=0, quiet_cycles=0))

    result = apply_danger_flag_down(state, (_down("edge:e1", base_time),))

    assert result is state


# ---------------------------------------------------------------------------
# detect() 結線
# ---------------------------------------------------------------------------


def test_detect_danger_down_zeroes_count_without_firing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # 立ち下げのみ（通常トリガーなし）→ 発火せず、e1 のカウントをリセット
    history = make_flat_line_history(edge_id, base_time)
    observations = Observations(observed_at=base_time)
    previous = DetectionState(
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=3),),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_down("edge:e1", base_time),),
        config=ResolvedConfig(surge_rate_threshold_percent_per_min=10.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.NO_TRIGGER
    assert result.triggered_edges == ()
    entry = result.new_state.retrigger_entry_of(edge_id)
    assert entry is not None
    assert entry.count == 0


def test_detect_danger_down_does_not_reset_cooldown(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # クールタイム中に立ち下げを受けてもクールタイムは維持される
    history = make_flat_line_history(edge_id, base_time)
    observations = Observations(observed_at=base_time)
    cooldown_until = base_time + timedelta(minutes=30)
    previous = DetectionState(
        cooldown_until=cooldown_until,
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=2),),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_down("edge:e1", base_time),),
        config=ResolvedConfig(surge_rate_threshold_percent_per_min=10.0),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.SKIPPED_COOLDOWN
    assert result.new_state.cooldown_until == cooldown_until
    entry = result.new_state.retrigger_entry_of(edge_id)
    assert entry is not None
    assert entry.count == 0


def test_detect_concurrent_surge_recounts_after_flag_down(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # 立ち下げで既存カウントを消した上で、同一サイクルの組合せ発火は新規に count=1 から数える
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(
        fire_state,
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=3),),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(_down("edge:e1", base_time),),
        config=ResolvedConfig(
            surge_rate_threshold_percent_per_min=10.0,
            high_stagnation_duration_min=5.0,
            beta=1.0,
        ),
        server_time=base_time,
    )

    assert result.verdict_hint == VerdictHint.TRIGGERED
    assert result.triggered_edges == (edge_id,)
    entry = result.new_state.retrigger_entry_of(edge_id)
    assert entry is not None
    assert entry.count == 1
