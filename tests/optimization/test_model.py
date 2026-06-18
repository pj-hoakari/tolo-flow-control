"""MILP 制約のユニットテスト（モデル層を直接呼んでフロー値を検証する）"""

from datetime import datetime, timezone

import pytest

from flow_control.domain import (
    ArcScalarFlow,
    ArcStagnation,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    ArcHistoryStat,
    HistoryDigest,
    Node,
    NodeID,
    NodeKind,
    Observations,
    ObservationType,
)
from flow_control.forecasting import ForecastResult, ODDemand
from flow_control.forecasting.sensitivity import ArcFlowSensitivity
from flow_control.forecasting.validation import NodeConfidence
from flow_control.optimization import ResolvedConfig, SolverStatus
from flow_control.optimization.arcs import build_arc_model
from flow_control.optimization.drainable import compute_drainable
from flow_control.optimization.model import build_model, solve_phase1
from flow_control.optimization.optimizer import _build_commodities, _build_inputs

_OBS_AT = datetime(2026, 6, 18, tzinfo=timezone.utc)


def _solve(graph, observations, forecast, history, config, *, is_open=True):
    arc_model = build_arc_model(graph)
    commodities = _build_commodities(forecast, set(arc_model.active_nodes), config.delta_min)
    inputs = _build_inputs(
        graph, observations, forecast, history, arc_model, commodities, config
    )
    od_pairs = tuple((k.origin, k.destination) for k in commodities)
    drain = compute_drainable(arc_model, od_pairs, frozenset(inputs.s_obs.keys()))
    built = build_model(arc_model, inputs, commodities, drain.drainable, is_open=is_open)
    return solve_phase1(built, 30.0, 1)


def _arc(sol, edge_value, direction):
    return sol.flow[f"{edge_value}|{direction}"]


def _edge_total(sol, edge_value):
    return _arc(sol, edge_value, "A_TO_B") + _arc(sol, edge_value, "B_TO_A")


def _mk(eid, a, b, *, obs=ObservationType.VECTOR, danger_cap=None, hint=None):
    return Edge(
        edge_id=EdgeID(eid),
        endpoint_a=a,
        endpoint_b=b,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=obs,
        danger_capacity=danger_cap,
        capacity_hint=hint,
    )


def _diamond(direct_edge: Edge, *, n3_danger_cap=None):
    """n1(境界) → {直行 e_d / 経由 e_a, e_b} → n2、中継 n3"""
    n1, n2, n3 = NodeID("n1"), NodeID("n2"), NodeID("n3")
    return Graph(
        nodes=(
            Node(n1, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(n2, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(
                n3,
                NodeKind.TRANSIT_ONLY,
                is_boundary=False,
                enabled=True,
                danger_flag=n3_danger_cap is not None,
                danger_capacity=n3_danger_cap,
            ),
        ),
        edges=(direct_edge, _mk("e_a", n1, n3), _mk("e_b", n3, n2)),
    )


def _demand_n1_n2(value: float) -> ForecastResult:
    return ForecastResult(
        od_matrix=(ODDemand(NodeID("n1"), NodeID("n2"), value),),
        node_confidence=(
            NodeConfidence(NodeID("n1"), 1.0),
            NodeConfidence(NodeID("n2"), 1.0),
            NodeConfidence(NodeID("n3"), 1.0),
        ),
        arc_flow_sensitivity=(
            ArcFlowSensitivity(EdgeID("e_d"), 1.0),
            ArcFlowSensitivity(EdgeID("e_a"), 1.0),
            ArcFlowSensitivity(EdgeID("e_b"), 1.0),
        ),
    )


def test_edge_danger_capacity_limits_flow():
    # 直行エッジを高停滞にして排出のため流したいが、危険フラグ容量で 3 に制限される
    graph = _diamond(_mk("e_d", NodeID("n1"), NodeID("n2"), danger_cap=3.0))
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(EdgeID("e_d"), 100.0),))
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e_d"), baseline_stagnation=1.0),))
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    assert p1.status == SolverStatus.OPTIMAL
    assert _arc(p1.solution, "e_d", "A_TO_B") == pytest.approx(3.0, abs=1e-6)


def test_no_cap_routes_all_through_congested_edge():
    # 容量制限が無ければ需要 10 すべてを高停滞の直行エッジに流して排出する
    graph = _diamond(_mk("e_d", NodeID("n1"), NodeID("n2")))
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(EdgeID("e_d"), 100.0),))
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e_d"), baseline_stagnation=1.0),))
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    assert _arc(p1.solution, "e_d", "A_TO_B") == pytest.approx(10.0, abs=1e-6)


def test_capacity_hint_limits_edge_flow():
    graph = _diamond(_mk("e_d", NodeID("n1"), NodeID("n2"), hint=3.0))
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(EdgeID("e_d"), 100.0),))
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e_d"), baseline_stagnation=1.0),))
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    assert _edge_total(p1.solution, "e_d") == pytest.approx(3.0, abs=1e-6)


def test_scalar_puncture_constraint():
    # スカラー型エッジは f_e <= max(0, C_e - σ_e)。C_e=10, σ_e=7 → 上限 3
    graph = _diamond(
        _mk("e_d", NodeID("n1"), NodeID("n2"), obs=ObservationType.SCALAR, hint=10.0)
    )
    obs = Observations(
        observed_at=_OBS_AT,
        arc_stagnations=(ArcStagnation(EdgeID("e_d"), 100.0),),
        arc_scalar_flows=(ArcScalarFlow(EdgeID("e_d"), 7.0),),
    )
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e_d"), baseline_stagnation=1.0),))
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    assert _edge_total(p1.solution, "e_d") == pytest.approx(3.0, abs=1e-6)


def test_drainage_upper_bound_limits_flow():
    # η_e·f_e <= s_obs（線形近似の妥当域）。s_obs=4, η=1 → f_e <= 4
    graph = _diamond(_mk("e_d", NodeID("n1"), NodeID("n2")))
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(EdgeID("e_d"), 4.0),))
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e_d"), baseline_stagnation=1.0),))
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    assert _edge_total(p1.solution, "e_d") <= 4.0 + 1e-6


def test_node_danger_capacity_limits_throughput():
    # n3 通過量上限 6。経由路（e_a,e_b）を高停滞にして流したいが流入が 6 に制限される
    graph = _diamond(_mk("e_d", NodeID("n1"), NodeID("n2")), n3_danger_cap=6.0)
    obs = Observations(
        observed_at=_OBS_AT,
        arc_stagnations=(
            ArcStagnation(EdgeID("e_a"), 100.0),
            ArcStagnation(EdgeID("e_b"), 100.0),
        ),
    )
    history = HistoryDigest(
        arc_stats=(
            ArcHistoryStat(EdgeID("e_a"), baseline_stagnation=1.0),
            ArcHistoryStat(EdgeID("e_b"), baseline_stagnation=1.0),
        )
    )
    p1 = _solve(graph, obs, _demand_n1_n2(10.0), history, ResolvedConfig())
    inflow_n3 = _arc(p1.solution, "e_a", "A_TO_B") + _arc(p1.solution, "e_b", "B_TO_A")
    assert inflow_n3 == pytest.approx(6.0, abs=1e-6)


@pytest.mark.parametrize(
    "confidence,expected_tau", [(1.0, 3.0), (0.0, 1.5)]
)
def test_confidence_weight_floor_scales_tau(confidence, expected_tau):
    # η=0 でフローが τ に効かない単一エッジ。τ = c_e·s_obs/s̄。
    # 信頼度 0 でも c_e は下限 0.5 でクリップされ τ=1.5（3.0 の半分）になる
    n1, n2 = NodeID("n1"), NodeID("n2")
    graph = Graph(
        nodes=(
            Node(n1, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(n2, NodeKind.GOAL, is_boundary=False, enabled=True),
        ),
        edges=(_mk("e1", n1, n2),),
    )
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(EdgeID("e1"), 30.0),))
    history = HistoryDigest(arc_stats=(ArcHistoryStat(EdgeID("e1"), baseline_stagnation=10.0),))
    forecast = ForecastResult(
        od_matrix=(ODDemand(n1, n2, 5.0),),
        node_confidence=(NodeConfidence(n1, confidence), NodeConfidence(n2, confidence)),
        arc_flow_sensitivity=(ArcFlowSensitivity(EdgeID("e1"), 0.0),),
    )
    p1 = _solve(graph, obs, forecast, history, ResolvedConfig())
    assert p1.solution is not None
    assert p1.solution.tau == pytest.approx(expected_tau, abs=1e-3)
