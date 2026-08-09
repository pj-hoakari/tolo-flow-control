"""Tests for the manual trigger detection

手動トリガー判定テスト

``DANGER_FLAG_UP`` イベントを即時トリガーとして抽出する
``target_id`` の prefix 規約（"edge:<id>" / "node:<id>"）に従い対象を判別する
``DANGER_FLAG_UP`` 以外の ``Event.kind`` は本判定では発火扱いしない
"""

from datetime import datetime

from flow_control.detection.triggers import (
    Event,
    EventKind,
    detect_manual_triggers,
)
from flow_control.domain import EdgeID, NodeID


def _danger_up(target_id: str, occurred_at: datetime) -> Event:
    return Event(
        kind=EventKind.DANGER_FLAG_UP,
        target_id=target_id,
        occurred_at=occurred_at,
    )


def test_no_triggers_when_events_empty():
    result = detect_manual_triggers(events=())

    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()


def test_danger_flag_up_for_edge_fires(base_time: datetime):
    result = detect_manual_triggers(events=(_danger_up("edge:e1", base_time),))

    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.triggered_nodes == ()


def test_danger_flag_up_for_node_fires(base_time: datetime):
    result = detect_manual_triggers(events=(_danger_up("node:n1", base_time),))

    assert result.triggered_edges == ()
    assert result.triggered_nodes == (NodeID("n1"),)


def test_danger_flag_down_does_not_fire(base_time: datetime):
    # DANGER_FLAG_DOWN は容量上限解除のための入力であり、本判定では発火扱いしない
    event = Event(
        kind=EventKind.DANGER_FLAG_DOWN,
        target_id="edge:e1",
        occurred_at=base_time,
    )

    result = detect_manual_triggers(events=(event,))

    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()


def test_non_danger_kinds_do_not_fire(base_time: datetime):
    # 危険フラグ立ち上げ以外のイベント種別はすべて手動トリガーとして扱わない
    other_kinds = (
        EventKind.DANGER_FLAG_DOWN,
        EventKind.DIRECTION_SWITCH,
        EventKind.ADD_EDGE,
        EventKind.ADD_NODE,
        EventKind.DISABLE,
        EventKind.ENABLE,
        EventKind.SCHEDULED_INFLOW,
        EventKind.SCHEDULED_ATTR_CHANGE,
    )
    events = tuple(
        Event(kind=kind, target_id="edge:e1", occurred_at=base_time) for kind in other_kinds
    )

    result = detect_manual_triggers(events=events)

    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()


def test_only_danger_flag_up_is_extracted_from_mixed_events(base_time: datetime):
    events = (
        _danger_up("edge:e1", base_time),
        Event(kind=EventKind.DANGER_FLAG_DOWN, target_id="edge:e2", occurred_at=base_time),
        Event(kind=EventKind.ENABLE, target_id="edge:e3", occurred_at=base_time),
        Event(kind=EventKind.SCHEDULED_INFLOW, target_id="node:n1", occurred_at=base_time),
    )

    result = detect_manual_triggers(events=events)

    assert result.triggered_edges == (EdgeID("e1"),)
    assert result.triggered_nodes == ()


def test_multiple_danger_flag_up_across_edges_and_nodes(base_time: datetime):
    events = (
        _danger_up("edge:e1", base_time),
        _danger_up("node:n1", base_time),
        _danger_up("edge:e2", base_time),
        _danger_up("node:n2", base_time),
    )

    result = detect_manual_triggers(events=events)

    assert result.triggered_edges == (EdgeID("e1"), EdgeID("e2"))
    assert result.triggered_nodes == (NodeID("n1"), NodeID("n2"))


def test_duplicate_danger_flag_up_dedupes_preserving_first_order(base_time: datetime):
    # 同一対象に対する DANGER_FLAG_UP が複数回現れても、最初の出現順を保持して
    # 重複は除外する
    events = (
        _danger_up("edge:e2", base_time),
        _danger_up("edge:e1", base_time),
        _danger_up("edge:e2", base_time),
        _danger_up("node:n1", base_time),
        _danger_up("node:n1", base_time),
    )

    result = detect_manual_triggers(events=events)

    assert result.triggered_edges == (EdgeID("e2"), EdgeID("e1"))
    assert result.triggered_nodes == (NodeID("n1"),)


def test_target_id_without_known_prefix_is_ignored(base_time: datetime):
    # prefix 規約に従わない target_id は対象種別が判別できないため発火しない
    events = (
        _danger_up("e1", base_time),
        _danger_up("other:foo", base_time),
        _danger_up("", base_time),
    )

    result = detect_manual_triggers(events=events)

    assert result.triggered_edges == ()
    assert result.triggered_nodes == ()
