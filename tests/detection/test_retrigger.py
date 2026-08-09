"""Tests for retrigger counts

再発火カウントテスト

- 同一アーク起点の連続発火で count を加算する
- 規則1: 別アーク起点発火で当該アークのカウントをリセット
- 規則2: 連続 retrigger_reset_quiet_cycles サイクル沈静化でリセット
- 規則3: グラフ削除／無効化でエントリ削除
- 規則4: 手動トリガーはカウント対象外
"""

from dataclasses import replace
from datetime import datetime, timedelta

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.detector import detect
from flow_control.detection.state import (
    ArcWatchState,
    DetectionState,
    RetriggerEntry,
)
from flow_control.detection.triggers import (
    Event,
    EventKind,
    update_retrigger_counts,
)
from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
)
from flow_control.domain.observations import Observations


def _config(*, quiet_cycles: int = 3, surge_threshold: float = 10.0) -> ResolvedConfig:
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=surge_threshold,
        retrigger_reset_quiet_cycles=quiet_cycles,
    )


def _edge(edge_id: EdgeID, *, enabled: bool = True) -> Edge:
    return Edge(
        edge_id=edge_id,
        endpoint_a=NodeID("a"),
        endpoint_b=NodeID("b"),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=enabled,
        observation_type=ObservationType.VECTOR,
    )


def _graph(*edges: Edge) -> Graph:
    nodes = (
        Node(node_id=NodeID("a"), kind=NodeKind.GOAL, is_boundary=True, enabled=True),
        Node(node_id=NodeID("b"), kind=NodeKind.GOAL, is_boundary=True, enabled=True),
    )
    return Graph(nodes=nodes, edges=edges)


def _run(
    *,
    counts: tuple[RetriggerEntry, ...],
    graph: Graph,
    fired: tuple[EdgeID, ...],
    watch_states: tuple[ArcWatchState, ...] = (),
    server_time: datetime,
    config: ResolvedConfig | None = None,
) -> tuple[RetriggerEntry, ...]:
    return update_retrigger_counts(
        previous_counts=counts,
        graph=graph,
        normal_trigger_edges=fired,
        watch_states=watch_states,
        server_time=server_time,
        config=config or _config(),
    )


def _entry_of(counts: tuple[RetriggerEntry, ...], edge: str) -> RetriggerEntry | None:
    for entry in counts:
        if entry.edge_id == EdgeID(edge):
            return entry
    return None


# ---------------------------------------------------------------------------
# update_retrigger_counts 単体
# ---------------------------------------------------------------------------


def test_first_fire_registers_count_one(base_time: datetime):
    graph = _graph(_edge(EdgeID("e1")))

    counts = _run(counts=(), graph=graph, fired=(EdgeID("e1"),), server_time=base_time)

    entry = _entry_of(counts, "e1")
    assert entry is not None
    assert entry.count == 1
    assert entry.quiet_cycles == 0
    assert entry.last_fired_at == base_time


def test_consecutive_fire_increments_count(base_time: datetime):
    graph = _graph(_edge(EdgeID("e1")))
    previous = (
        RetriggerEntry(
            edge_id=EdgeID("e1"),
            count=2,
            quiet_cycles=0,
            last_fired_at=base_time - timedelta(minutes=10),
        ),
    )

    counts = _run(counts=previous, graph=graph, fired=(EdgeID("e1"),), server_time=base_time)

    entry = _entry_of(counts, "e1")
    assert entry is not None
    assert entry.count == 3
    assert entry.last_fired_at == base_time


def test_rule1_different_origin_resets_other_arc(base_time: datetime):
    # e1 が積み上がっている状態で、別アーク e2 のみが発火 → e1 をリセット
    graph = _graph(_edge(EdgeID("e1")), _edge(EdgeID("e2")))
    previous = (RetriggerEntry(edge_id=EdgeID("e1"), count=2),)

    counts = _run(counts=previous, graph=graph, fired=(EdgeID("e2"),), server_time=base_time)

    e1 = _entry_of(counts, "e1")
    e2 = _entry_of(counts, "e2")
    assert e1 is not None
    assert e1.count == 0
    assert e1.quiet_cycles == 0
    assert e2 is not None
    assert e2.count == 1


def test_rule2_quiet_cycles_accumulate_then_reset(base_time: datetime):
    # 発火なし・警戒なしで quiet_cycles を加算。閾値到達でリセット
    graph = _graph(_edge(EdgeID("e1")))
    config = _config(quiet_cycles=3)

    # 1 サイクル目: count 維持、quiet 1
    step1 = _run(
        counts=(RetriggerEntry(edge_id=EdgeID("e1"), count=2, quiet_cycles=0),),
        graph=graph,
        fired=(),
        server_time=base_time,
        config=config,
    )
    e1 = _entry_of(step1, "e1")
    assert e1 is not None
    assert e1.count == 2
    assert e1.quiet_cycles == 1

    # quiet が閾値（3）に到達するとリセット
    step3 = _run(
        counts=(RetriggerEntry(edge_id=EdgeID("e1"), count=2, quiet_cycles=2),),
        graph=graph,
        fired=(),
        server_time=base_time,
        config=config,
    )
    e1 = _entry_of(step3, "e1")
    assert e1 is not None
    assert e1.count == 0
    assert e1.quiet_cycles == 0


def test_rule2_does_not_increment_quiet_when_in_watch(base_time: datetime):
    # 発火していないが警戒状態にある間は quiet_cycles を増やさず据え置き
    graph = _graph(_edge(EdgeID("e1")))
    previous = (RetriggerEntry(edge_id=EdgeID("e1"), count=2, quiet_cycles=1),)
    watch = (ArcWatchState(edge_id=EdgeID("e1"), percentile_breached=True),)

    counts = _run(
        counts=previous,
        graph=graph,
        fired=(),
        watch_states=watch,
        server_time=base_time,
    )

    entry = _entry_of(counts, "e1")
    assert entry is not None
    assert entry.count == 2
    assert entry.quiet_cycles == 1


def test_rule3_disabled_edge_entry_is_removed(base_time: datetime):
    graph = _graph(_edge(EdgeID("e1"), enabled=False))
    previous = (RetriggerEntry(edge_id=EdgeID("e1"), count=2),)

    counts = _run(counts=previous, graph=graph, fired=(), server_time=base_time)

    assert _entry_of(counts, "e1") is None


def test_rule3_removed_edge_entry_is_removed(base_time: datetime):
    # グラフに存在しないアークのエントリは削除される
    graph = _graph(_edge(EdgeID("e2")))
    previous = (RetriggerEntry(edge_id=EdgeID("e1"), count=2),)

    counts = _run(counts=previous, graph=graph, fired=(), server_time=base_time)

    assert _entry_of(counts, "e1") is None


def test_both_arcs_fire_increment_independently(base_time: datetime):
    graph = _graph(_edge(EdgeID("e1")), _edge(EdgeID("e2")))
    previous = (RetriggerEntry(edge_id=EdgeID("e1"), count=1),)

    counts = _run(
        counts=previous,
        graph=graph,
        fired=(EdgeID("e1"), EdgeID("e2")),
        server_time=base_time,
    )

    e1 = _entry_of(counts, "e1")
    e2 = _entry_of(counts, "e2")
    assert e1 is not None
    assert e1.count == 2
    assert e2 is not None
    assert e2.count == 1


# ---------------------------------------------------------------------------
# detect() 結線（規則4: 危険フラグ由来はカウント対象外）
# ---------------------------------------------------------------------------


def test_detect_combined_trigger_increments_retrigger_count(
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
        config=ResolvedConfig(
            surge_rate_threshold_percent_per_min=10.0,
            high_stagnation_duration_min=5.0,
            beta=1.0,
        ),
        server_time=base_time,
    )

    entry = result.new_state.retrigger_entry_of(edge_id)
    assert entry is not None
    assert entry.count == 1


def test_detect_queued_trigger_does_not_count(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_combined_firing,
):
    # クールタイム中にメトリク条件が成立してもキュー行きで実発火しない
    # → 再発火カウントは加算されない（§4.9: queued は変更なし）
    history, observations, fire_state = make_combined_firing(edge_id, base_time)
    previous = replace(
        fire_state,
        cooldown_until=base_time + timedelta(minutes=30),
        arc_retrigger_counts=(RetriggerEntry(edge_id=edge_id, count=2),),
    )

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=previous,
        events=(),
        config=ResolvedConfig(
            surge_rate_threshold_percent_per_min=10.0,
            high_stagnation_duration_min=5.0,
            beta=1.0,
            queue_score_threshold=5.0,
            queue_diversity_threshold=3,
        ),
        server_time=base_time,
    )

    from flow_control.detection.triggers import VerdictHint

    assert result.verdict_hint == VerdictHint.QUEUED
    entry = result.new_state.retrigger_entry_of(edge_id)
    assert entry is not None
    assert entry.count == 2  # 変更なし


def test_detect_danger_flag_does_not_count(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_flat_line_history,
):
    # 危険フラグ立ち上げで発火しても再発火カウントは積まれない（規則4）
    history = make_flat_line_history(edge_id, base_time)
    observations = Observations(observed_at=base_time)

    result = detect(
        graph=basic_graph,
        observations=observations,
        history_digest=history,
        previous_state=DetectionState(),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e1",
                occurred_at=base_time,
            ),
        ),
        config=ResolvedConfig(surge_rate_threshold_percent_per_min=10.0),
        server_time=base_time,
    )

    assert result.new_state.retrigger_entry_of(edge_id) is None
