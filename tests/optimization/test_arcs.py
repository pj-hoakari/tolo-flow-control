"""有向アークモデル構築のユニットテスト"""

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
from flow_control.optimization.arcs import build_arc_model, fixed_directions


def _edge(eid, a, b, constraint, current=CurrentDirection.BIDIRECTIONAL):
    return Edge(
        EdgeID(eid), a, b, constraint, current, enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _node(nid, enabled=True):
    return Node(NodeID(nid), NodeKind.GOAL, is_boundary=False, enabled=enabled)


def test_prior_allows_both_directions_no_legal_fix():
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", n1, n2, DirectionConstraint.ONEWAY_A_TO_B_PRIOR),),
    )
    arc_model = build_arc_model(graph)
    assert arc_model.alpha["e1|A_TO_B"] == 1
    assert arc_model.alpha["e1|B_TO_A"] == 1
    assert arc_model.beta["e1|A_TO_B"] == 0
    assert arc_model.beta["e1|B_TO_A"] == 0


def test_legal_fixed_a_to_b_disables_reverse_and_fixes_both():
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", n1, n2, DirectionConstraint.LEGAL_FIXED_A_TO_B),),
    )
    arc_model = build_arc_model(graph)
    assert arc_model.alpha["e1|A_TO_B"] == 1
    assert arc_model.alpha["e1|B_TO_A"] == 0
    assert arc_model.beta["e1|A_TO_B"] == 1
    assert arc_model.beta["e1|B_TO_A"] == 1


def test_incidence_and_active_sets():
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", n1, n2, DirectionConstraint.BIDIRECTIONAL_PRIOR),),
    )
    arc_model = build_arc_model(graph)
    assert len(arc_model.arcs) == 2
    out_n1 = arc_model.arcs_out(n1)
    in_n1 = arc_model.arcs_in(n1)
    assert {a.head for a in out_n1} == {n2}
    assert {a.tail for a in in_n1} == {n2}


def test_disabled_endpoint_edge_excluded():
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(
        nodes=(_node("n1"), _node("n2", enabled=False)),
        edges=(_edge("e1", n1, n2, DirectionConstraint.BIDIRECTIONAL_PRIOR),),
    )
    arc_model = build_arc_model(graph)
    assert arc_model.arcs == ()
    assert arc_model.active_edges == ()


def test_fixed_directions_per_current_direction():
    n1, n2 = NodeID("n1"), NodeID("n2")
    e_ab = _edge("e1", n1, n2, DirectionConstraint.BIDIRECTIONAL_PRIOR, CurrentDirection.A_TO_B)
    assert fixed_directions(e_ab) == {"e1|A_TO_B": 1, "e1|B_TO_A": 0}

    e_bi = _edge("e1", n1, n2, DirectionConstraint.BIDIRECTIONAL_PRIOR, CurrentDirection.BIDIRECTIONAL)
    assert fixed_directions(e_bi) == {"e1|A_TO_B": 1, "e1|B_TO_A": 1}
