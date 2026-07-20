"""機能2 の残留評価と Detour 不足ゲート（純関数）"""

import pytest

from flow_control.domain import EdgeID
from flow_control.optimization.model import MilpInputs
from flow_control.optimization.restriction import (
    assess_residual,
    close_preserves_connectivity,
    compute_limit_value,
    evaluate_detour_gate,
    select_feeder_candidates,
)

_E_HOT = EdgeID("e_hot")
_E_SCALAR = EdgeID("e_scalar")
_E_D1 = EdgeID("e_d1")
_E_D2 = EdgeID("e_d2")

_ARC_KEYS = {
    _E_HOT: ("e_hot|A_TO_B",),
    _E_SCALAR: ("e_scalar|A_TO_B",),
    _E_D1: ("e_d1|A_TO_B",),
    _E_D2: ("e_d2|A_TO_B",),
}


def _inputs(**overrides) -> MilpInputs:
    base = dict(
        s_obs={_E_HOT: 30.0, _E_D1: 10.0, _E_D2: 10.0},
        s_bar={_E_HOT: 10.0, _E_D1: 10.0, _E_D2: 10.0},
        eta={_E_HOT: 0.5, _E_D1: 0.5, _E_D2: 0.5},
        c_e={},
        capacity_hint={_E_SCALAR: 50.0},
        sigma={_E_SCALAR: 10.0},
        scalar_edges=frozenset({_E_SCALAR}),
        edge_danger_capacity={},
        node_danger_capacity={},
        big_m=1000.0,
        epsilon=1e-3,
        epsilon_0=1e-6,
    )
    base.update(overrides)
    return MilpInputs(**base)


def test_residual_fires_on_tau_exceeded():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=3.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.tau_exceeded
    assert not got.puncture_residual and not got.undrainable_present


def test_residual_quiet_when_below_threshold():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=1.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.residual


def test_residual_fires_on_puncture_overflow():
    # スカラー上限 max(0, 50-10)=40 に対しフロー 45 → パンク残留
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_SCALAR}),
        tau_zone=0.0,
        flow={"e_scalar|A_TO_B": 45.0},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.puncture_residual
    assert got.puncture_edges == (_E_SCALAR,)


def test_residual_ignores_puncture_within_limit():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_SCALAR}),
        tau_zone=0.0,
        flow={"e_scalar|A_TO_B": 35.0},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.residual


def test_residual_fires_on_undrainable_in_zone():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=0.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset({_E_HOT}),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.undrainable_present
    assert got.undrainable_edges == (_E_HOT,)


def test_gate_structural_shortage_when_k_small():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1}),
        k_effective=1,
        flow={"e_d1|A_TO_B": 20.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.structural_shortage


def test_gate_unused_when_detour_carries_no_flow():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={},  # どちらの迂回路も使われていない
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.unused
    assert got.used_ratio == pytest.approx(0.0)


def test_gate_sufficient_when_detour_used_and_safe():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        # 残留停滞 10-0.5*18=1 → 正規化 0.1 で閾値以下
        flow={"e_d1|A_TO_B": 18.0, "e_d2|A_TO_B": 18.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.insufficient
    assert got.used_ratio == pytest.approx(1.0)


def test_gate_endangered_when_detour_stagnates():
    # 迂回路は使われているが残留停滞が閾値超（10-0.5*2=9 → 0.9 ... 閾値 0.5 で超過）
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 2.0, "e_d2|A_TO_B": 2.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=0.5,
    )
    assert got.insufficient and got.detour_endangered
    assert set(got.endangered_edges) == {_E_D1, _E_D2}


def test_gate_endangered_when_detour_is_triggered_or_watched():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 18.0, "e_d2|A_TO_B": 18.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset({_E_D1}),
        watched_edges=frozenset({_E_D2}),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.detour_endangered
    assert set(got.endangered_edges) == {_E_D1, _E_D2}


def test_gate_skips_stagnation_term_without_observation():
    # 停滞観測のない迂回エッジは正規化停滞を評価しない（幻の停滞を作らない）
    inputs = _inputs(s_obs={_E_HOT: 30.0}, s_bar={_E_HOT: 10.0}, eta={_E_HOT: 0.5})
    got = evaluate_detour_gate(
        inputs,
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 5.0, "e_d2|A_TO_B": 5.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=0.1,
    )
    assert not got.detour_endangered
    assert not got.insufficient


# --- limit_value / 候補選定 / CLOSE 可否 -------------------------------------


def _chain_arc_model(*, oneway_middle: bool = False, boundaries: bool = True):
    """b0 - n1 - n2 - b3 の鎖（両端が入退出点）"""
    from flow_control.domain import (
        CurrentDirection,
        DirectionConstraint,
        Edge,
        Graph,
        Node,
        NodeKind,
    )
    from flow_control.domain import NodeID as NID
    from flow_control.domain import ObservationType
    from flow_control.optimization.arcs import build_arc_model

    names = ["b0", "n1", "n2", "b3"]
    nodes = tuple(
        Node(
            node_id=NID(n),
            kind=NodeKind.GOAL if (boundaries and n in ("b0", "b3")) else NodeKind.TRANSIT_ONLY,
            is_boundary=boundaries and n in ("b0", "b3"),
            enabled=True,
        )
        for n in names
    )
    edges = []
    for i in range(len(names) - 1):
        middle = i == 1
        edges.append(
            Edge(
                edge_id=EdgeID(f"e{i}"),
                endpoint_a=NID(names[i]),
                endpoint_b=NID(names[i + 1]),
                direction_constraint=(
                    DirectionConstraint.LEGAL_FIXED_A_TO_B
                    if (middle and oneway_middle)
                    else DirectionConstraint.BIDIRECTIONAL_PRIOR
                ),
                current_direction=(
                    CurrentDirection.A_TO_B
                    if (middle and oneway_middle)
                    else CurrentDirection.BIDIRECTIONAL
                ),
                enabled=True,
                observation_type=ObservationType.VECTOR,
            )
        )
    return build_arc_model(Graph(nodes=nodes, edges=tuple(edges)))


def _all_directions(arc_model) -> dict[str, int]:
    return {arc.key: 1 for arc in arc_model.arcs}


def test_limit_value_prefers_measured_outflow():
    got = compute_limit_value(_inputs(), _E_HOT, outflow_average=12.5)
    assert got.value == pytest.approx(12.5)
    assert got.confidence == 1.0
    assert not got.derived_from_drain_bound


def test_limit_value_falls_back_to_drain_bound_with_low_confidence():
    # ラインなし: s_obs/η = 30/0.5 = 60、低信頼
    got = compute_limit_value(_inputs(), _E_HOT, outflow_average=None)
    assert got.value == pytest.approx(60.0)
    assert got.confidence < 1.0
    assert got.derived_from_drain_bound


def test_limit_value_none_when_no_basis():
    got = compute_limit_value(
        _inputs(s_obs={}, eta={}), _E_HOT, outflow_average=None
    )
    assert got.value is None


def test_feeder_candidates_ranked_by_contribution_then_importance():
    arc_model = _chain_arc_model()
    # e1 が危険。上流は n1（e0 の head）
    flow = {"e0|A_TO_B": 20.0, "e1|A_TO_B": 20.0, "e2|A_TO_B": 20.0}
    got = select_feeder_candidates(
        arc_model,
        danger_edges=frozenset({EdgeID("e1")}),
        flow=flow,
        importance={EdgeID("e0"): 0.2},
        zone_edges=frozenset({EdgeID("e0"), EdgeID("e1"), EdgeID("e2")}),
    )
    # 上流フィーダは e0（危険エッジ自身と下流 e2 は除外）
    assert got == (EdgeID("e0"),)


def test_close_rejected_when_it_breaks_boundary_reachability():
    arc_model = _chain_arc_model()
    # 鎖の中央 e1 を閉じると b0 側と b3 側が分断される
    assert not close_preserves_connectivity(
        arc_model,
        closed_edge=EdgeID("e1"),
        direction=_all_directions(arc_model),
        is_open=True,
    )


def test_close_rejected_in_closed_mode_when_component_splits():
    arc_model = _chain_arc_model(boundaries=False)
    assert not close_preserves_connectivity(
        arc_model,
        closed_edge=EdgeID("e1"),
        direction=_all_directions(arc_model),
        is_open=False,
    )


def test_close_allowed_when_parallel_route_remains():
    """並行ルートがあり、閉鎖してもどのノードも孤立しないなら CLOSE 可。"""
    from flow_control.domain import (
        CurrentDirection,
        DirectionConstraint,
        Edge,
        Graph,
        Node,
        NodeKind,
        ObservationType,
    )
    from flow_control.domain import NodeID as NID
    from flow_control.optimization.arcs import build_arc_model

    # b0 と b2 を結ぶ 2 本の並行エッジ（多重辺）
    nodes = (
        Node(NID("b0"), NodeKind.GOAL, is_boundary=True, enabled=True),
        Node(NID("b2"), NodeKind.GOAL, is_boundary=True, enabled=True),
    )

    def edge(eid, a, b):
        return Edge(
            edge_id=EdgeID(eid),
            endpoint_a=NID(a),
            endpoint_b=NID(b),
            direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
            current_direction=CurrentDirection.BIDIRECTIONAL,
            enabled=True,
            observation_type=ObservationType.VECTOR,
        )

    graph = Graph(nodes=nodes, edges=(edge("e0", "b0", "b2"), edge("e1", "b0", "b2")))
    arc_model = build_arc_model(graph)
    # e0 を閉じても e1 が残るため連結性は保たれる
    assert close_preserves_connectivity(
        arc_model,
        closed_edge=EdgeID("e0"),
        direction=_all_directions(arc_model),
        is_open=True,
    )
    # 両方は閉じられない（e1 も閉じる想定なら不可）
    assert not close_preserves_connectivity(
        arc_model,
        closed_edge=EdgeID("e0"),
        direction={
            key: (0 if key.startswith("e1|") else value)
            for key, value in _all_directions(arc_model).items()
        },
        is_open=True,
    )
