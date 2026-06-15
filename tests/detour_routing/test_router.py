# route_detour のテスト
# 起点直行路の同梱・k_effective・P_trigger 和集合・方向制約・複数トリガーを検証

from flow_control.detour_routing.config import ResolvedConfig
from flow_control.detour_routing.router import route_detour
from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    Mode,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
)


def _node(node_id: str) -> Node:
    return Node(
        node_id=NodeID(node_id), kind=NodeKind.GOAL, is_boundary=False, enabled=True
    )


def _edge(
    edge_id: str,
    a: str,
    b: str,
    *,
    constraint: DirectionConstraint = DirectionConstraint.BIDIRECTIONAL_PRIOR,
) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=constraint,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _values(edge_ids: frozenset[EdgeID]) -> set[str]:
    return {edge_id.value for edge_id in edge_ids}


# 数理 §27.4 の 3 ノード・3 エッジ三角グラフ
_TRIANGLE = Graph(
    nodes=(_node("n1"), _node("n2"), _node("n3")),
    edges=(
        _edge("e12", "n1", "n2"),
        _edge("e23", "n2", "n3"),
        _edge("e13", "n1", "n3"),
    ),
)


def test_worked_example_27_4():
    # 起点 e12 の両端 (n1, n2)。G\{e12} 上の迂回路は n1→n3→n2 の 1 本のみ
    result = route_detour(_TRIANGLE, (EdgeID("e12"),), None, ResolvedConfig())

    detour_set = result.detour_set_of(EdgeID("e12"))
    assert detour_set is not None
    assert detour_set.origin_edge == EdgeID("e12")
    assert detour_set.endpoint_pair == (NodeID("n1"), NodeID("n2"))
    assert detour_set.k_effective == 1

    # 起点直行路 1 本 + 迂回路 1 本
    assert len(detour_set.paths) == 2
    origin_path = detour_set.paths[0]
    assert origin_path.contains_trigger is True
    assert origin_path.edge_ids == (EdgeID("e12"),)

    detour_path = detour_set.paths[1]
    assert detour_path.contains_trigger is False
    assert tuple(e.value for e in detour_path.edge_ids) == ("e13", "e23")
    assert detour_path.total_length == 2.0

    # P_trigger = {e12, e13, e23}
    assert _values(detour_set.edge_set()) == {"e12", "e13", "e23"}


def test_exactly_one_path_contains_trigger():
    result = route_detour(_TRIANGLE, (EdgeID("e12"),), None, ResolvedConfig())
    detour_set = result.detour_set_of(EdgeID("e12"))
    assert detour_set is not None
    trigger_paths = [p for p in detour_set.paths if p.contains_trigger]
    assert len(trigger_paths) == 1


def test_bridge_has_no_detour_but_keeps_origin_path():
    # 唯一の橋：迂回路なし（§5.3）。起点直行路は必ず 1 本残る
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e1", "n1", "n2"),))
    result = route_detour(graph, (EdgeID("e1"),), None, ResolvedConfig())

    detour_set = result.detour_set_of(EdgeID("e1"))
    assert detour_set is not None
    assert detour_set.k_effective == 0
    assert len(detour_set.paths) == 1
    assert detour_set.paths[0].contains_trigger is True
    assert _values(detour_set.edge_set()) == {"e1"}


def test_legal_fixed_blocks_detour_direction():
    # e32 は n2→n3 のみ通行可（LEGAL_FIXED_B_TO_A，endpoint_a=n3, endpoint_b=n2）
    # → 迂回 n1→n3→n2 に必要な n3→n2 が不能となり迂回路なし
    graph = Graph(
        nodes=(_node("n1"), _node("n2"), _node("n3")),
        edges=(
            _edge("e12", "n1", "n2"),
            _edge("e13", "n1", "n3"),
            _edge("e32", "n3", "n2", constraint=DirectionConstraint.LEGAL_FIXED_B_TO_A),
        ),
    )
    result = route_detour(graph, (EdgeID("e12"),), None, ResolvedConfig())
    detour_set = result.detour_set_of(EdgeID("e12"))
    assert detour_set is not None
    assert detour_set.k_effective == 0


def test_legal_fixed_allows_detour_direction():
    # e32 は n3→n2 通行可（LEGAL_FIXED_A_TO_B）→ 迂回 n1→n3→n2 が成立
    graph = Graph(
        nodes=(_node("n1"), _node("n2"), _node("n3")),
        edges=(
            _edge("e12", "n1", "n2"),
            _edge("e13", "n1", "n3"),
            _edge("e32", "n3", "n2", constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B),
        ),
    )
    result = route_detour(graph, (EdgeID("e12"),), None, ResolvedConfig())
    detour_set = result.detour_set_of(EdgeID("e12"))
    assert detour_set is not None
    assert detour_set.k_effective == 1
    assert tuple(e.value for e in detour_set.paths[1].edge_ids) == ("e13", "e32")


def test_respects_k_shortest_config():
    # ダイヤモンド：e_st 起点の迂回路は 2 本。k=1 で 1 本に制限
    diamond = Graph(
        nodes=(_node("s"), _node("a"), _node("b"), _node("t")),
        edges=(
            _edge("e_st", "s", "t"),
            _edge("e_sa", "s", "a"),
            _edge("e_at", "a", "t"),
            _edge("e_sb", "s", "b"),
            _edge("e_bt", "b", "t"),
        ),
    )
    result = route_detour(
        diamond, (EdgeID("e_st"),), None, ResolvedConfig(k_shortest=1)
    )
    detour_set = result.detour_set_of(EdgeID("e_st"))
    assert detour_set is not None
    assert detour_set.k_effective == 1


def test_multiple_triggers_preserve_order_and_union():
    result = route_detour(
        _TRIANGLE, (EdgeID("e23"), EdgeID("e13")), None, ResolvedConfig()
    )
    # detour_sets は入力順（決定的）
    assert tuple(ds.origin_edge.value for ds in result.detour_sets) == ("e23", "e13")
    # 各起点で全エッジが P_trigger に入り，和集合は全 3 エッジ
    assert _values(result.trigger_edge_set()) == {"e12", "e23", "e13"}


def test_unknown_triggered_edge_is_skipped():
    result = route_detour(_TRIANGLE, (EdgeID("missing"),), None, ResolvedConfig())
    assert result.detour_sets == ()
    assert result.detour_set_of(EdgeID("missing")) is None


def test_forecast_result_and_mode_do_not_affect_v0_result():
    # v0 では forecast_result / mode は結果に影響しない
    baseline = route_detour(_TRIANGLE, (EdgeID("e12"),), None, ResolvedConfig())
    with_mode = route_detour(
        _TRIANGLE, (EdgeID("e12"),), None, ResolvedConfig(), mode=Mode.OPEN
    )
    assert baseline == with_mode
