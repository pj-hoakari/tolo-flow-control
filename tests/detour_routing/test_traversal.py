# build_adjacency / feasible_directions のテスト
# 方向制約（PRIOR は両方向・LEGAL_FIXED は当該方向のみ）・無効要素除外・起点アーク除去を検証

from flow_control.detour_routing.traversal import (
    DirectedArc,
    build_adjacency,
    feasible_directions,
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


def _node(node_id: str, *, enabled: bool = True) -> Node:
    return Node(
        node_id=NodeID(node_id),
        kind=NodeKind.GOAL,
        is_boundary=False,
        enabled=enabled,
    )


def _edge(
    edge_id: str,
    a: str,
    b: str,
    *,
    constraint: DirectionConstraint = DirectionConstraint.BIDIRECTIONAL_PRIOR,
    enabled: bool = True,
) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=constraint,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=enabled,
        observation_type=ObservationType.VECTOR,
    )


def _targets(arcs: tuple[DirectedArc, ...]) -> set[str]:
    return {arc.to_node.value for arc in arcs}


def test_feasible_directions_prior_allows_both():
    # PRIOR 系は最適化が方向を変更しうるため両方向可
    for constraint in (
        DirectionConstraint.BIDIRECTIONAL_PRIOR,
        DirectionConstraint.ONEWAY_A_TO_B_PRIOR,
        DirectionConstraint.ONEWAY_B_TO_A_PRIOR,
        DirectionConstraint.LEGAL_FIXED_BIDIRECTIONAL,
    ):
        assert feasible_directions(constraint) == (True, True)


def test_feasible_directions_legal_fixed_restricts():
    assert feasible_directions(DirectionConstraint.LEGAL_FIXED_A_TO_B) == (True, False)
    assert feasible_directions(DirectionConstraint.LEGAL_FIXED_B_TO_A) == (False, True)


def test_build_adjacency_bidirectional_arcs():
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e1", "n1", "n2"),))
    adjacency = build_adjacency(graph)
    assert _targets(adjacency[NodeID("n1")]) == {"n2"}
    assert _targets(adjacency[NodeID("n2")]) == {"n1"}
    assert adjacency[NodeID("n1")][0].weight == 1.0


def test_build_adjacency_legal_fixed_one_direction_only():
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", "n1", "n2", constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B),),
    )
    adjacency = build_adjacency(graph)
    assert _targets(adjacency[NodeID("n1")]) == {"n2"}
    # B→A 方向は実行不能のため n2 からの出弧なし
    assert NodeID("n2") not in adjacency


def test_build_adjacency_excludes_disabled_edge_and_node():
    graph = Graph(
        nodes=(_node("n1"), _node("n2"), _node("n3", enabled=False)),
        edges=(
            _edge("e1", "n1", "n2", enabled=False),
            _edge("e2", "n1", "n3"),  # n3 が無効 → 除外
        ),
    )
    adjacency = build_adjacency(graph)
    assert adjacency == {}


def test_build_adjacency_excluded_edges_removed():
    # 起点アーク a* の一時除去（G\{a*}）
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", "n1", "n2"), _edge("e2", "n1", "n2")),
    )
    adjacency = build_adjacency(graph, excluded_edges=frozenset({EdgeID("e1")}))
    n1_edges = {arc.edge_id.value for arc in adjacency[NodeID("n1")]}
    assert n1_edges == {"e2"}
