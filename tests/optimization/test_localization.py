"""局所化（ゾーン抽出）の純関数テスト

線形グラフ b0 - n1 - n2 - n3 - n4 - n5 - b6（両端が入退出点）を主に使う。
"""

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
from flow_control.optimization.localization import build_trigger_zones


def _node(name: str, *, boundary: bool = False) -> Node:
    return Node(
        node_id=NodeID(name),
        kind=NodeKind.GOAL if boundary else NodeKind.TRANSIT_ONLY,
        is_boundary=boundary,
        enabled=True,
    )


def _edge(name: str, a: str, b: str) -> Edge:
    return Edge(
        edge_id=EdgeID(name),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _chain_graph(*, boundaries: bool = True) -> Graph:
    names = ["b0", "n1", "n2", "n3", "n4", "n5", "b6"]
    nodes = tuple(_node(n, boundary=boundaries and n in ("b0", "b6")) for n in names)
    edges = tuple(
        _edge(f"e{names[i][1]}{names[i + 1][1]}", names[i], names[i + 1])
        for i in range(len(names) - 1)
    )
    return Graph(nodes=nodes, edges=edges)


def _ids(items) -> list[str]:
    return [x.value for x in items]


def test_single_zone_includes_core_and_boundary_paths():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e23"),),
        (),
        local_radius_hops=1,
        max_trigger_zones=4,
    )
    assert not result.capped
    assert len(result.zones) == 1
    zone = result.zones[0]
    assert _ids(zone.seed_edges) == ["e23"]
    # 核 = 端点 n2,n3 の 1 ホップ近傍。境界最短経路で b0・b6 までの導線が加わる
    assert _ids(zone.nodes) == ["b0", "b6", "n1", "n2", "n3", "n4", "n5"]
    assert _ids(zone.edges) == ["e01", "e12", "e23", "e34", "e45", "e56"]


def test_overlapping_cores_merge_into_one_zone():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e12"), EdgeID("e23")),
        (),
        local_radius_hops=1,
        max_trigger_zones=4,
    )
    assert len(result.zones) == 1
    assert _ids(result.zones[0].seed_edges) == ["e12", "e23"]


def test_disjoint_cores_stay_separate_and_order_by_severity():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e01"), EdgeID("e45")),
        (),
        local_radius_hops=1,
        max_trigger_zones=4,
        edge_severity={EdgeID("e01"): 1.0, EdgeID("e45"): 2.0},
    )
    assert not result.capped
    assert len(result.zones) == 2
    # 重大度降順
    assert _ids(result.zones[0].seed_edges) == ["e45"]
    assert result.zones[0].severity == 2.0
    assert _ids(result.zones[1].seed_edges) == ["e01"]
    # 境界最短経路の付与はゾーンを併合させない（ゾーン間のノード重複は許容）
    assert "b6" in _ids(result.zones[1].nodes)


def test_cap_keeps_highest_severity_and_sets_flag():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e01"), EdgeID("e45")),
        (),
        local_radius_hops=1,
        max_trigger_zones=1,
        edge_severity={EdgeID("e01"): 1.0, EdgeID("e45"): 2.0},
    )
    assert result.capped
    assert len(result.zones) == 1
    assert _ids(result.zones[0].seed_edges) == ["e45"]


def test_severity_tie_breaks_by_min_edge_id():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e45"), EdgeID("e01")),
        (),
        local_radius_hops=1,
        max_trigger_zones=4,
    )
    # 重大度同値（未指定=0）なら最小エッジ ID 昇順
    assert _ids(result.zones[0].seed_edges) == ["e01"]


def test_node_trigger_builds_zone_around_node():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (),
        (NodeID("n3"),),
        local_radius_hops=1,
        max_trigger_zones=4,
        edge_severity={EdgeID("e23"): 3.0},
    )
    assert len(result.zones) == 1
    zone = result.zones[0]
    assert _ids(zone.seed_nodes) == ["n3"]
    # 核 = n3 の 1 ホップ近傍（n2, n4）
    assert {"n2", "n3", "n4"} <= set(_ids(zone.nodes))
    # 重大度は接続エッジの最大値で代表
    assert zone.severity == 3.0


def test_closed_mode_has_no_boundary_augmentation():
    arc_model = build_arc_model(_chain_graph(boundaries=False))
    result = build_trigger_zones(
        arc_model,
        (EdgeID("e23"),),
        (),
        local_radius_hops=1,
        max_trigger_zones=4,
    )
    zone = result.zones[0]
    assert _ids(zone.nodes) == ["n1", "n2", "n3", "n4"]
    assert _ids(zone.edges) == ["e12", "e23", "e34"]


def test_deterministic_across_calls():
    arc_model = build_arc_model(_chain_graph())
    args = (
        (EdgeID("e01"), EdgeID("e34"), EdgeID("e45")),
        (NodeID("n2"),),
    )
    first = build_trigger_zones(arc_model, *args, local_radius_hops=2, max_trigger_zones=2)
    second = build_trigger_zones(arc_model, *args, local_radius_hops=2, max_trigger_zones=2)
    assert first == second


def test_disabled_or_unknown_triggers_are_ignored():
    arc_model = build_arc_model(_chain_graph())
    result = build_trigger_zones(
        arc_model,
        (EdgeID("no-such-edge"),),
        (NodeID("no-such-node"),),
        local_radius_hops=1,
        max_trigger_zones=4,
    )
    assert result.zones == ()
    assert not result.capped
