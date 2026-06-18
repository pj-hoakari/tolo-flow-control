"""排出可能エッジ集合 E_drain の前処理ユニットテスト"""

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
from flow_control.optimization.arcs import build_arc_model
from flow_control.optimization.drainable import compute_drainable


def _edge(eid, a, b, constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR):
    return Edge(
        EdgeID(eid),
        a,
        b,
        constraint,
        CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _node(nid):
    return Node(NodeID(nid), NodeKind.GOAL, is_boundary=False, enabled=True)


def test_edge_on_od_path_is_drainable_and_disconnected_is_not():
    # n1-n2 は OD(n1,n2) パス上 → 排出可能。n3-n4 は無関係 → 排出不能
    n1, n2, n3, n4 = NodeID("n1"), NodeID("n2"), NodeID("n3"), NodeID("n4")
    graph = Graph(
        nodes=(_node("n1"), _node("n2"), _node("n3"), _node("n4")),
        edges=(_edge("e12", n1, n2), _edge("e34", n3, n4)),
    )
    arc_model = build_arc_model(graph)
    stagnation_edges = frozenset({EdgeID("e12"), EdgeID("e34")})
    result = compute_drainable(arc_model, ((n1, n2),), stagnation_edges)

    assert EdgeID("e12") in result.drainable
    assert EdgeID("e34") in result.undrainable
    assert EdgeID("e34") not in result.drainable


def test_legal_fixed_direction_excludes_reverse_only_edge():
    # OD(n1,n3) に対し、n2→n1 にしか向けない一方通行 e12 は s→t パスに乗らず排出不能
    n1, n2, n3 = NodeID("n1"), NodeID("n2"), NodeID("n3")
    graph = Graph(
        nodes=(_node("n1"), _node("n2"), _node("n3")),
        edges=(
            _edge("e12", n1, n2, DirectionConstraint.LEGAL_FIXED_B_TO_A),
            _edge("e13", n1, n3),
        ),
    )
    arc_model = build_arc_model(graph)
    stagnation_edges = frozenset({EdgeID("e12"), EdgeID("e13")})
    result = compute_drainable(arc_model, ((n1, n3),), stagnation_edges)

    assert EdgeID("e13") in result.drainable
    assert EdgeID("e12") in result.undrainable


def test_no_od_pairs_means_nothing_drainable():
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e12", n1, n2),))
    arc_model = build_arc_model(graph)
    result = compute_drainable(arc_model, (), frozenset({EdgeID("e12")}))
    assert result.drainable == frozenset()
    assert EdgeID("e12") in result.undrainable
