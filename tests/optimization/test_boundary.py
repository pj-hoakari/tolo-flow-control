"""境界制御提案の生成規則ユニットテスト（需要方向ベース）"""

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
from flow_control.optimization.boundary import compute_boundary_control
from flow_control.optimization.model import Commodity
from flow_control.optimization.results import (
    BoundaryAction,
    BoundaryControl,
    OptimizationResult,
)

_N1, _N2, _N3 = NodeID("n1"), NodeID("n2"), NodeID("n3")
_E1, _E2 = EdgeID("e1"), EdgeID("e2")


def _edge(edge_id, a, b, *, danger=False):
    return Edge(
        edge_id,
        a,
        b,
        DirectionConstraint.BIDIRECTIONAL_PRIOR,
        CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
        danger_flag=danger,
    )


def _graph(*, danger_edge=False, danger_node=False, second_boundary=False):
    """n1(境界) --e1--> n2。second_boundary で n3(境界) --e2-- n2 を追加"""
    nodes = [
        Node(
            _N1,
            NodeKind.GOAL,
            is_boundary=True,
            enabled=True,
            danger_flag=danger_node,
        ),
        Node(_N2, NodeKind.GOAL_TRANSIT_MIXED, is_boundary=False, enabled=True),
    ]
    edges = [_edge(_E1, _N1, _N2, danger=danger_edge)]
    if second_boundary:
        nodes.append(Node(_N3, NodeKind.GOAL, is_boundary=True, enabled=True))
        edges.append(_edge(_E2, _N3, _N2))
    return Graph(nodes=tuple(nodes), edges=tuple(edges))


def _k(index, origin, destination, demand=10.0):
    return Commodity(index=index, origin=origin, destination=destination, demand=demand)


def _actions(controls):
    return {(c.node_id, c.action) for c in controls}


def test_inbound_demand_pauses_ingress_only():
    # n1 起点の流入需要のみ → 新規入場の停止だけを提案し、退出は塞がない
    controls = compute_boundary_control(
        _graph(danger_edge=True),
        is_open=True,
        previous_result=None,
        commodities=(_k(0, _N1, _N2),),
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_INGRESS)}


def test_outbound_demand_with_alternate_exit_pauses_egress():
    # n1 終点の流出需要＋代替境界 n3 あり → 退出を他出口へ転回させる停止を提案
    controls = compute_boundary_control(
        _graph(danger_edge=True, second_boundary=True),
        is_open=True,
        previous_result=None,
        commodities=(_k(0, _N2, _N1),),
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_EGRESS)}


def test_outbound_demand_without_alternate_exit_keeps_drainage():
    # 唯一の排出口は塞がない（流出需要があっても提案なし）
    controls = compute_boundary_control(
        _graph(danger_edge=True),
        is_open=True,
        previous_result=None,
        commodities=(_k(0, _N2, _N1),),
    )
    assert controls == ()


def test_no_demand_precautionary_ingress_only():
    # 需要情報が無ければ予防的な入場停止のみ
    controls = compute_boundary_control(
        _graph(danger_edge=True), is_open=True, previous_result=None
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_INGRESS)}
    (control,) = controls
    assert "precautionary" in control.reason


def test_reason_mentions_demand_direction_and_target():
    controls = compute_boundary_control(
        _graph(danger_edge=True),
        is_open=True,
        previous_result=None,
        commodities=(_k(0, _N1, _N2),),
    )
    (control,) = controls
    assert "inbound demand" in control.reason
    assert "e1" in control.reason


def test_danger_node_on_boundary_follows_demand_rules():
    # 境界ノード自身が危険でも無条件の両停止はせず、需要方向に従う
    controls = compute_boundary_control(
        _graph(danger_node=True),
        is_open=True,
        previous_result=None,
        commodities=(_k(0, _N1, _N2),),
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_INGRESS)}


def test_resume_proposed_after_danger_cleared():
    # 前回 PAUSE した境界ノードに、危険が消えた今回 RESUME を出す
    previous = OptimizationResult(
        boundary_control=(
            BoundaryControl(_N1, BoundaryAction.PAUSE_INGRESS, "prev"),
        )
    )
    controls = compute_boundary_control(
        _graph(danger_edge=False),
        is_open=True,
        previous_result=previous,
        commodities=(_k(0, _N1, _N2),),
    )
    assert _actions(controls) == {(_N1, BoundaryAction.RESUME)}


def test_closed_mode_emits_nothing():
    controls = compute_boundary_control(
        _graph(danger_edge=True),
        is_open=False,
        previous_result=None,
        commodities=(_k(0, _N1, _N2),),
    )
    assert controls == ()
