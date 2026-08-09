"""INFEASIBLE 時の二段フォールバック（方向固定 LP → 前回結果コピー）"""

from datetime import UTC, datetime

from flow_control.detour_routing import DetourResult
from flow_control.domain import (
    ArcHistoryStat,
    ArcStagnation,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
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
from flow_control.optimization import (
    DirectionProposal,
    ImportanceDirection,
    ObjectiveValues,
    OptimizationMode,
    OptimizationResult,
    ProposedDirection,
    ResolvedConfig,
    RouteImportance,
    SolverStatus,
    optimize,
)

_OBS_AT = datetime(2026, 6, 18, tzinfo=UTC)
_N1, _N2 = NodeID("n1"), NodeID("n2")
_E1 = EdgeID("e1")


def _graph_oneway() -> Graph:
    # 2 境界ノードを一方通行で結ぶ。n2→n1 が存在せず境界連結性を満たせない
    return Graph(
        nodes=(
            Node(_N1, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(_N2, NodeKind.GOAL, is_boundary=True, enabled=True),
        ),
        edges=(
            Edge(
                _E1,
                _N1,
                _N2,
                DirectionConstraint.LEGAL_FIXED_A_TO_B,
                CurrentDirection.A_TO_B,
                enabled=True,
                observation_type=ObservationType.VECTOR,
            ),
        ),
    )


def _forecast(origin: NodeID, destination: NodeID) -> ForecastResult:
    return ForecastResult(
        od_matrix=(ODDemand(origin, destination, 5.0),),
        node_confidence=(NodeConfidence(_N1, 1.0), NodeConfidence(_N2, 1.0)),
        arc_flow_sensitivity=(ArcFlowSensitivity(_E1, 0.5),),
    )


def _history() -> HistoryDigest:
    return HistoryDigest(arc_stats=(ArcHistoryStat(_E1, baseline_stagnation=10.0),))


def _previous() -> OptimizationResult:
    return OptimizationResult(
        route_importance=(RouteImportance(_E1, ImportanceDirection.A_TO_B, 0.7),),
        direction_proposal=(DirectionProposal(_E1, ProposedDirection.A_TO_B),),
        objective_values=ObjectiveValues(tau_star=1.0, throughput=5.0),
        solver_status=SolverStatus.OPTIMAL,
    )


def test_infeasible_then_lp_relaxation_keeps_current_directions():
    # 境界連結性で MILP は INFEASIBLE。方向固定 LP は需要 n1→n2 を流せて可解
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    previous = _previous()
    result = optimize(
        _graph_oneway(),
        obs,
        _forecast(_N1, _N2),
        DetourResult(),
        _history(),
        previous_result=previous,
        config=ResolvedConfig(optimization_mode=OptimizationMode.STRICT),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    # 劣化経路の新提案であり、前回結果への差し戻しではない
    assert result.constraint_report.degraded_mode
    assert not result.constraint_report.fallback_to_previous
    # 方向変更は提案しない＝現状維持（KEEP のみ）を明示出力する
    proposals = result.optimization_result.direction_proposal
    assert proposals
    assert all(p.change_type.value == "KEEP" for p in proposals)
    assert len(result.optimization_result.route_importance) == 1


def test_infeasible_lp_also_infeasible_copies_previous():
    # 需要 n2→n1 は一方通行のため固定 LP でも流せず、前回結果を全体コピーする
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    previous = _previous()
    result = optimize(
        _graph_oneway(),
        obs,
        _forecast(_N2, _N1),
        DetourResult(),
        _history(),
        previous_result=previous,
        config=ResolvedConfig(optimization_mode=OptimizationMode.STRICT),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    # 前回結果への差し戻し（劣化モードかつ差し戻しの両方が立つ）
    assert result.constraint_report.fallback_to_previous
    assert result.constraint_report.degraded_mode
    # 前回の重要度・方向提案がそのままコピーされる
    assert result.optimization_result.route_importance == previous.route_importance
    assert result.optimization_result.direction_proposal == previous.direction_proposal


def test_infeasible_no_previous_returns_empty_proposals():
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    result = optimize(
        _graph_oneway(),
        obs,
        _forecast(_N2, _N1),
        DetourResult(),
        _history(),
        previous_result=None,
        config=ResolvedConfig(optimization_mode=OptimizationMode.STRICT),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    assert result.optimization_result.route_importance == ()
    assert result.optimization_result.direction_proposal == ()


def _graph_narrow_corridor(capacity: float) -> Graph:
    # n1(境界) --e1(低容量)--> n2(境界)。双方向だが e1 の容量が需要に足りない
    return Graph(
        nodes=(
            Node(_N1, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(_N2, NodeKind.GOAL, is_boundary=True, enabled=True),
        ),
        edges=(
            Edge(
                _E1,
                _N1,
                _N2,
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                CurrentDirection.BIDIRECTIONAL,
                enabled=True,
                observation_type=ObservationType.VECTOR,
                capacity_hint=capacity,
            ),
        ),
    )


def test_capacity_overflow_falls_back_with_slack_not_empty():
    """需要が容量を構造的に超えても、スラック化 LP が非空の提案を返す。

    容量ヒント 5 に対し需要 50。従来は配分・フォールバックとも INFEASIBLE となり
    提案が空になっていた（過密という最も提案が欲しい局面での空振り）。
    """
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    result = optimize(
        _graph_narrow_corridor(capacity=5.0),
        obs,
        ForecastResult(
            od_matrix=(ODDemand(_N1, _N2, 50.0),),
            node_confidence=(NodeConfidence(_N1, 1.0), NodeConfidence(_N2, 1.0)),
            arc_flow_sensitivity=(ArcFlowSensitivity(_E1, 0.5),),
        ),
        DetourResult(),
        _history(),
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
        triggered_edges=(_E1,),
    )
    opt = result.optimization_result
    # 容量を守れないため通常解は得られず劣化経路へ入る（差し戻しではない）
    assert result.constraint_report.degraded_mode
    assert not result.constraint_report.fallback_to_previous
    # スラック化により配分が得られ、重要度が出る（空提案にならない）
    assert opt.route_importance
    assert any(ri.importance > 0.0 for ri in opt.route_importance)
    # 残留 τ も評価される（フローが 0 のままなら s_obs がそのまま残り τ は大きい）
    assert opt.objective_values.tau_star < 1.0


def test_capacity_overflow_proposes_overload_limit_when_enabled():
    """機能2 有効時、容量を構造的に超過したエッジへ LIMIT（持続可能レート）を提案する。"""
    from flow_control.optimization import RestrictionAction, RestrictionReason

    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    result = optimize(
        _graph_narrow_corridor(capacity=5.0),
        obs,
        ForecastResult(
            od_matrix=(ODDemand(_N1, _N2, 50.0),),
            node_confidence=(NodeConfidence(_N1, 1.0), NodeConfidence(_N2, 1.0)),
            arc_flow_sensitivity=(ArcFlowSensitivity(_E1, 0.5),),
        ),
        DetourResult(),
        _history(),
        previous_result=None,
        config=ResolvedConfig(restriction_proposal_enabled=True),
        seed=1,
        time_limit=30.0,
        triggered_edges=(_E1,),
    )
    rp = result.optimization_result.restriction_proposal
    assert any(
        p.edge_id == _E1
        and p.action == RestrictionAction.LIMIT
        and p.reason == RestrictionReason.OVERLOAD
        and p.limit_value == 5.0
        for p in rp
    )


def test_capacity_overflow_no_limit_when_restriction_disabled():
    """機能2 が無効なら過需要でも LIMIT は出ない（ノーハーム既定の維持）。"""
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    result = optimize(
        _graph_narrow_corridor(capacity=5.0),
        obs,
        ForecastResult(
            od_matrix=(ODDemand(_N1, _N2, 50.0),),
            node_confidence=(NodeConfidence(_N1, 1.0), NodeConfidence(_N2, 1.0)),
            arc_flow_sensitivity=(ArcFlowSensitivity(_E1, 0.5),),
        ),
        DetourResult(),
        _history(),
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
        triggered_edges=(_E1,),
    )
    assert result.optimization_result.restriction_proposal == ()


def test_capacity_slack_not_used_when_feasible():
    """容量内に収まる需要ではスラックが立たず、通常解（LIGHTWEIGHT）で返る。"""
    obs = Observations(observed_at=_OBS_AT, arc_stagnations=(ArcStagnation(_E1, 30.0),))
    result = optimize(
        _graph_narrow_corridor(capacity=100.0),
        obs,
        ForecastResult(
            od_matrix=(ODDemand(_N1, _N2, 50.0),),
            node_confidence=(NodeConfidence(_N1, 1.0), NodeConfidence(_N2, 1.0)),
            arc_flow_sensitivity=(ArcFlowSensitivity(_E1, 0.5),),
        ),
        DetourResult(),
        _history(),
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
        triggered_edges=(_E1,),
    )
    assert result.optimization_result.solver_status == SolverStatus.LIGHTWEIGHT
    assert not result.constraint_report.fallback_to_previous
