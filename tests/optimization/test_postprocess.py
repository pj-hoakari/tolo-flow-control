"""迂回候補加重・採用迂回パス導出の後処理単体テスト"""

import pytest

from flow_control.detour_routing import DetourPath, DetourResult, DetourSet
from flow_control.domain.enums import (
    CurrentDirection,
    DirectionConstraint,
    ObservationType,
)
from flow_control.domain.graph import Edge, EdgeID, Graph, Node, NodeID
from flow_control.domain.enums import NodeKind
from flow_control.optimization.arcs import build_arc_model
from flow_control.optimization.model import ArcSolution
from flow_control.optimization.postprocess import (
    compute_detour_emphasis,
    compute_detour_path_proposals,
    compute_route_importance,
)


_N1, _N2, _N3, _N4 = NodeID("n1"), NodeID("n2"), NodeID("n3"), NodeID("n4")
_E_MAIN = EdgeID("e_main")  # n1-n2（トリガー起点）
_E_UP = EdgeID("e_up")  # n1-n3
_E_DOWN = EdgeID("e_down")  # n3-n2
_E_ALT1 = EdgeID("e_alt1")  # n1-n4
_E_ALT2 = EdgeID("e_alt2")  # n4-n2


def _node(nid: NodeID) -> Node:
    return Node(node_id=nid, kind=NodeKind.TRANSIT_ONLY, is_boundary=False, enabled=True)


def _edge(eid: EdgeID, a: NodeID, b: NodeID, capacity_hint: float | None = None) -> Edge:
    return Edge(
        edge_id=eid,
        endpoint_a=a,
        endpoint_b=b,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
        capacity_hint=capacity_hint,
    )


@pytest.fixture
def diamond_graph() -> Graph:
    # n1→n2 の直行 e_main と、n3 経由・n4 経由の 2 迂回路
    return Graph(
        nodes=(_node(_N1), _node(_N2), _node(_N3), _node(_N4)),
        edges=(
            _edge(_E_MAIN, _N1, _N2),
            _edge(_E_UP, _N1, _N3),
            _edge(_E_DOWN, _N3, _N2),
            _edge(_E_ALT1, _N1, _N4),
            _edge(_E_ALT2, _N4, _N2),
        ),
    )


def _detour_result(paths: tuple[DetourPath, ...]) -> DetourResult:
    origin = DetourPath(edge_ids=(_E_MAIN,), total_length=1.0, contains_trigger=True)
    return DetourResult(
        detour_sets=(
            DetourSet(
                origin_edge=_E_MAIN,
                endpoint_pair=(_N1, _N2),
                paths=(origin,) + paths,
                k_effective=len(paths),
            ),
        )
    )


def _all_open_direction(arc_model) -> dict[str, int]:
    return {arc.key: 1 for arc in arc_model.arcs}


def _solution(arc_model, flow: dict[str, float]) -> ArcSolution:
    return ArcSolution(flow=flow, direction=_all_open_direction(arc_model), tau=0.0)


def test_emphasis_distributes_by_inverse_length(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    detour = _detour_result(
        (
            DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),
            DetourPath(
                edge_ids=(_E_ALT1, _E_ALT2), total_length=4.0, contains_trigger=False
            ),
        )
    )
    solution = _solution(arc_model, {"e_main|A_TO_B": 12.0})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    # 逆距離重み 1/2 : 1/4 → 8 : 4
    assert emphasis.arc_bonus["e_up|A_TO_B"] == pytest.approx(8.0)
    assert emphasis.arc_bonus["e_down|A_TO_B"] == pytest.approx(8.0)
    assert emphasis.arc_bonus["e_alt1|A_TO_B"] == pytest.approx(4.0)
    assert emphasis.arc_bonus["e_alt2|A_TO_B"] == pytest.approx(4.0)
    assert len(emphasis.assigned_paths) == 2


def test_emphasis_uses_observed_flow_when_solution_has_none(diamond_graph):
    # OD 帰属の盲点（解フロー 0）でも観測フローがあれば強調する
    arc_model = build_arc_model(diamond_graph)
    detour = _detour_result(
        (DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),)
    )
    solution = _solution(arc_model, {})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={_E_MAIN: 10.0},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    assert emphasis.arc_bonus["e_up|A_TO_B"] == pytest.approx(10.0)


def test_emphasis_excludes_path_through_other_trigger(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    detour = _detour_result(
        (
            DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),
            DetourPath(
                edge_ids=(_E_ALT1, _E_ALT2), total_length=2.0, contains_trigger=False
            ),
        )
    )
    solution = _solution(arc_model, {"e_main|A_TO_B": 10.0})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
        triggered_edges=frozenset({_E_ALT1}),
    )
    # e_alt1 は別トリガー → その経路は除外され、全量が n3 経由へ
    assert "e_alt1|A_TO_B" not in emphasis.arc_bonus
    assert emphasis.arc_bonus["e_up|A_TO_B"] == pytest.approx(10.0)


def test_emphasis_excludes_direction_disabled_path(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    detour = _detour_result(
        (
            DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),
            DetourPath(
                edge_ids=(_E_ALT1, _E_ALT2), total_length=2.0, contains_trigger=False
            ),
        )
    )
    solution = _solution(arc_model, {"e_main|A_TO_B": 10.0})
    adopted = _all_open_direction(arc_model)
    adopted["e_alt2|A_TO_B"] = 0  # 採用方向が n4→n2 を無効化（n2→n4 の一方通行化）
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=adopted,
    )
    assert "e_alt1|A_TO_B" not in emphasis.arc_bonus
    assert emphasis.arc_bonus["e_up|A_TO_B"] == pytest.approx(10.0)


def test_emphasis_clips_by_capacity(diamond_graph):
    graph = Graph(
        nodes=diamond_graph.nodes,
        edges=tuple(
            _edge(e.edge_id, e.endpoint_a, e.endpoint_b, capacity_hint=4.0)
            if e.edge_id == _E_DOWN
            else e
            for e in diamond_graph.edges
        ),
    )
    arc_model = build_arc_model(graph)
    detour = _detour_result(
        (DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),)
    )
    solution = _solution(arc_model, {"e_main|A_TO_B": 10.0})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    # e_down の残容量 4 でクリップされる
    assert emphasis.arc_bonus["e_up|A_TO_B"] == pytest.approx(4.0)
    assert emphasis.arc_bonus["e_down|A_TO_B"] == pytest.approx(4.0)


def test_emphasis_disabled_with_zero_weight(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    detour = _detour_result(
        (DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False),)
    )
    solution = _solution(arc_model, {"e_main|A_TO_B": 10.0})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=0.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    assert emphasis.arc_bonus == {}
    assert emphasis.assigned_paths == ()


def test_detour_path_proposals_from_emphasis_and_flow(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    up_path = DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False)
    alt_path = DetourPath(
        edge_ids=(_E_ALT1, _E_ALT2), total_length=2.0, contains_trigger=False
    )
    detour = _detour_result((up_path, alt_path))
    # n4 経由にはフローが乗っている。n3 経由はフローゼロだが加重割当あり
    solution = _solution(
        arc_model,
        {"e_main|A_TO_B": 10.0, "e_alt1|A_TO_B": 3.0, "e_alt2|A_TO_B": 3.0},
    )
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    proposals = compute_detour_path_proposals(
        arc_model,
        detour,
        solution,
        emphasis,
        edge_confidence={_E_UP: 0.8, _E_DOWN: 0.6},
    )
    by_edges = {p.edge_ids: p for p in proposals}
    assert set(by_edges) == {(_E_UP, _E_DOWN), (_E_ALT1, _E_ALT2)}
    assert by_edges[(_E_UP, _E_DOWN)].origin_edge_id == _E_MAIN
    assert by_edges[(_E_UP, _E_DOWN)].confidence == pytest.approx(0.6)
    assert by_edges[(_E_ALT1, _E_ALT2)].confidence == pytest.approx(1.0)


def test_detour_path_proposals_empty_without_flow_or_emphasis(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    up_path = DetourPath(edge_ids=(_E_UP, _E_DOWN), total_length=2.0, contains_trigger=False)
    detour = _detour_result((up_path,))
    solution = _solution(arc_model, {})
    emphasis = compute_detour_emphasis(
        arc_model,
        detour,
        observed_edge_flow={},
        solution=solution,
        weight=1.0,
        adopted_direction=_all_open_direction(arc_model),
    )
    proposals = compute_detour_path_proposals(
        arc_model, detour, solution, emphasis, edge_confidence={}
    )
    assert proposals == ()


def test_importance_blends_emphasis(diamond_graph):
    arc_model = build_arc_model(diamond_graph)
    solution = _solution(arc_model, {"e_main|A_TO_B": 10.0})
    importance = compute_route_importance(
        arc_model,
        solution,
        epsilon_0=1e-6,
        detour_emphasis={"e_up|A_TO_B": 10.0, "e_down|A_TO_B": 10.0},
    )
    by_edge = {ri.edge_id: ri for ri in importance}
    assert by_edge[_E_MAIN].importance == pytest.approx(1.0, abs=1e-3)
    assert by_edge[_E_UP].importance == pytest.approx(1.0, abs=1e-3)
    assert by_edge[_E_ALT1].importance == pytest.approx(0.0, abs=1e-9)
