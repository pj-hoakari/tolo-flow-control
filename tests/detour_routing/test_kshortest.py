# k_shortest_paths（NetworkX shortest_simple_paths）のテスト
# 距離昇順・k 上限・到達不能・並行エッジ集約・決定性を検証

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
from flow_control.detour_routing.kshortest import WeightedPath, k_shortest_paths
from flow_control.detour_routing.traversal import build_adjacency


def _node(node_id: str) -> Node:
    return Node(
        node_id=NodeID(node_id), kind=NodeKind.GOAL, is_boundary=False, enabled=True
    )


def _edge(edge_id: str, a: str, b: str) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _keys(paths: list[WeightedPath]) -> list[tuple[str, ...]]:
    return [tuple(e.value for e in p.edge_ids) for p in paths]


# s, a, b, t を結ぶダイヤモンド型 + 直行 e_st
# 単純路は e_st(1) / e_sa,e_at(2) / e_sb,e_bt(2) の 3 本
_DIAMOND = Graph(
    nodes=(_node("s"), _node("a"), _node("b"), _node("t")),
    edges=(
        _edge("e_st", "s", "t"),
        _edge("e_sa", "s", "a"),
        _edge("e_at", "a", "t"),
        _edge("e_sb", "s", "b"),
        _edge("e_bt", "b", "t"),
    ),
)


def test_single_path():
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e1", "n1", "n2"),))
    paths = k_shortest_paths(build_adjacency(graph), NodeID("n1"), NodeID("n2"), 3)
    assert _keys(paths) == [("e1",)]
    assert paths[0].total_length == 1.0


def test_orders_by_length_then_lexicographic():
    paths = k_shortest_paths(build_adjacency(_DIAMOND), NodeID("s"), NodeID("t"), 3)
    assert _keys(paths) == [("e_st",), ("e_sa", "e_at"), ("e_sb", "e_bt")]
    assert [p.total_length for p in paths] == [1.0, 2.0, 2.0]


def test_k_caps_returned_count():
    paths = k_shortest_paths(build_adjacency(_DIAMOND), NodeID("s"), NodeID("t"), 2)
    assert _keys(paths) == [("e_st",), ("e_sa", "e_at")]


def test_k_larger_than_available_returns_all():
    # 単純路は 3 本のみ。k=10 でも 3 本
    paths = k_shortest_paths(build_adjacency(_DIAMOND), NodeID("s"), NodeID("t"), 10)
    assert len(paths) == 3


def test_unreachable_returns_empty():
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=())
    paths = k_shortest_paths(build_adjacency(graph), NodeID("n1"), NodeID("n2"), 3)
    assert paths == []


def test_same_source_and_target_returns_empty():
    paths = k_shortest_paths(build_adjacency(_DIAMOND), NodeID("s"), NodeID("s"), 3)
    assert paths == []


def test_non_positive_k_returns_empty():
    adjacency = build_adjacency(_DIAMOND)
    assert k_shortest_paths(adjacency, NodeID("s"), NodeID("t"), 0) == []
    assert k_shortest_paths(adjacency, NodeID("s"), NodeID("t"), -1) == []


def test_parallel_edges_collapse_to_min_edge():
    # n1-n2 間の並行エッジ e1/e2 は，最小 (weight, edge_id) の 1 本へ集約される
    # （NetworkX shortest_simple_paths はノード列ベース。同重みは edge_id 辞書順で e1）
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e2", "n1", "n2"), _edge("e1", "n1", "n2")),
    )
    paths = k_shortest_paths(build_adjacency(graph), NodeID("n1"), NodeID("n2"), 3)
    assert _keys(paths) == [("e1",)]


def test_deterministic_across_runs():
    adjacency = build_adjacency(_DIAMOND)
    first = _keys(k_shortest_paths(adjacency, NodeID("s"), NodeID("t"), 3))
    second = _keys(k_shortest_paths(adjacency, NodeID("s"), NodeID("t"), 3))
    assert first == second
