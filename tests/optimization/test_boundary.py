"""境界制御提案の生成規則ユニットテスト"""

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
from flow_control.optimization.results import (
    BoundaryAction,
    BoundaryControl,
    OptimizationResult,
)

_N1, _N2 = NodeID("n1"), NodeID("n2")
_E1 = EdgeID("e1")


def _graph(current_direction: CurrentDirection, *, danger_edge=False, danger_node=False):
    return Graph(
        nodes=(
            Node(
                _N1,
                NodeKind.GOAL,
                is_boundary=True,
                enabled=True,
                danger_flag=danger_node,
            ),
            Node(_N2, NodeKind.TRANSIT_ONLY, is_boundary=False, enabled=True),
        ),
        edges=(
            Edge(
                _E1,
                _N1,
                _N2,
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                current_direction,
                enabled=True,
                observation_type=ObservationType.VECTOR,
                danger_flag=danger_edge,
            ),
        ),
    )


def _actions(controls):
    return {(c.node_id, c.action) for c in controls}


def test_bidirectional_danger_edge_pauses_both():
    controls = compute_boundary_control(
        _graph(CurrentDirection.BIDIRECTIONAL, danger_edge=True), is_open=True, previous_result=None
    )
    assert _actions(controls) == {
        (_N1, BoundaryAction.PAUSE_INGRESS),
        (_N1, BoundaryAction.PAUSE_EGRESS),
    }


def test_inbound_danger_edge_pauses_ingress_only():
    # e1 が n1 へ流入する向き（A_TO_B、n1=endpoint_a なので n1 発 = 流出ではない）
    # current_direction B_TO_A は n2→n1、すなわち n1 への流入
    controls = compute_boundary_control(
        _graph(CurrentDirection.B_TO_A, danger_edge=True), is_open=True, previous_result=None
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_INGRESS)}


def test_outbound_danger_edge_pauses_egress_only():
    # current_direction A_TO_B は n1→n2、すなわち n1 からの流出
    controls = compute_boundary_control(
        _graph(CurrentDirection.A_TO_B, danger_edge=True), is_open=True, previous_result=None
    )
    assert _actions(controls) == {(_N1, BoundaryAction.PAUSE_EGRESS)}


def test_danger_node_on_boundary_pauses_both():
    controls = compute_boundary_control(
        _graph(CurrentDirection.A_TO_B, danger_node=True), is_open=True, previous_result=None
    )
    assert _actions(controls) == {
        (_N1, BoundaryAction.PAUSE_INGRESS),
        (_N1, BoundaryAction.PAUSE_EGRESS),
    }


def test_resume_proposed_after_danger_cleared():
    # 前回 PAUSE した境界ノードに、危険が消えた今回 RESUME を出す
    previous = OptimizationResult(
        boundary_control=(
            BoundaryControl(_N1, BoundaryAction.PAUSE_INGRESS, "prev"),
        )
    )
    controls = compute_boundary_control(
        _graph(CurrentDirection.A_TO_B, danger_edge=False),
        is_open=True,
        previous_result=previous,
    )
    assert _actions(controls) == {(_N1, BoundaryAction.RESUME)}


def test_closed_mode_emits_nothing():
    controls = compute_boundary_control(
        _graph(CurrentDirection.BIDIRECTIONAL, danger_edge=True),
        is_open=False,
        previous_result=None,
    )
    assert controls == ()
