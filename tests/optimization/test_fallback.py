"""INFEASIBLE 時の二段フォールバック（方向固定 LP → 前回結果コピー）"""

from datetime import datetime, timezone

from flow_control.domain import (
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
from flow_control.detour_routing import DetourResult
from flow_control.forecasting import ForecastResult, ODDemand
from flow_control.forecasting.sensitivity import ArcFlowSensitivity
from flow_control.forecasting.validation import NodeConfidence
from flow_control.optimization import (
    DirectionProposal,
    ImportanceDirection,
    ObjectiveValues,
    OptimizationResult,
    ProposedDirection,
    ResolvedConfig,
    RouteImportance,
    SolverStatus,
    optimize,
)

_OBS_AT = datetime(2026, 6, 18, tzinfo=timezone.utc)
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


def test_infeasible_then_lp_relaxation_holds_previous_direction():
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
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    assert result.constraint_report.fallback_to_previous
    # 方向提案は出さず前回提案を維持、重要度は LP 解から再計算
    assert result.optimization_result.direction_proposal == previous.direction_proposal
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
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    assert result.constraint_report.fallback_to_previous
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
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.INFEASIBLE
    assert result.optimization_result.route_importance == ()
    assert result.optimization_result.direction_proposal == ()
