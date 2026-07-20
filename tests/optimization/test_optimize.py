"""統合・ゴールデンテスト（手計算例の再現含む）"""

import pytest

from flow_control.detour_routing import DetourResult
from flow_control.domain import Mode
from flow_control.optimization import (
    ImportanceDirection,
    Phase2Status,
    ProposedDirection,
    SolverStatus,
    OptimizationMode,
    ResolvedConfig,
    optimize,
)


def _importance_of(opt_result, edge_value):
    for ri in opt_result.route_importance:
        if ri.edge_id.value == edge_value:
            return ri
    raise AssertionError(f"no importance for {edge_value}")


def test_worked_example_reproduces_golden_values(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
    config,
):
    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=config,
        seed=1,
        time_limit=30.0,
    )
    opt = result.optimization_result

    assert opt.solver_status == SolverStatus.OPTIMAL
    assert result.solver_stats.phase2_status == Phase2Status.OPTIMAL
    # τ* = (30 - 0.5*12) / (10 + ε0) ≈ 2.4、スループット = f_e12 + f_e23 + f_e13 = 24
    # （正規化の分母にゼロ除算回避の ε0 を含むため厳密には 2.4 のわずか下）
    assert opt.objective_values.tau_star == pytest.approx(2.4, abs=1e-3)
    assert opt.objective_values.throughput == pytest.approx(24.0, abs=1e-6)

    # 重要度: 混雑エッジ e12 とその下流 e23 が最大、直行 e13 は 0
    assert _importance_of(opt, "e12").importance == pytest.approx(1.0, abs=1e-3)
    assert _importance_of(opt, "e23").importance == pytest.approx(1.0, abs=1e-3)
    assert _importance_of(opt, "e13").importance == pytest.approx(0.0, abs=1e-6)
    assert _importance_of(opt, "e12").direction == ImportanceDirection.A_TO_B
    assert _importance_of(opt, "e13").direction == ImportanceDirection.NONE

    # 方向提案は全エッジ双方向のまま
    for dp in opt.direction_proposal:
        assert dp.proposed_direction == ProposedDirection.BIDIRECTIONAL
        assert dp.confidence == 1.0

    assert result.constraint_report.local_reachability_satisfied
    assert result.constraint_report.boundary_reachability_satisfied
    assert not result.constraint_report.fallback_to_previous
    assert opt.solved_at == worked_example_observations.observed_at
    assert opt.seed == 1


def test_big_m_factor_does_not_change_solution(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
):
    # 非循環制約により、Big-M を大きくしても解は循環で膨張しない
    # （Big-M は厳密モード MILP の z 制約でのみ使われる。基本モードの配分 LP は
    #   バイナリゼロで Big-M 自体を持たない）
    from flow_control.optimization import OptimizationMode, ResolvedConfig

    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=ResolvedConfig(
            optimization_mode=OptimizationMode.STRICT, big_m_factor=100.0
        ),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.objective_values.tau_star == pytest.approx(
        2.4, abs=1e-3
    )
    assert result.optimization_result.objective_values.throughput == pytest.approx(
        24.0, abs=1e-6
    )


def test_lightweight_residual_tau_is_conservative(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
):
    """基本モードの近似残留 τ は厳密最小値（2.4）以上＝循環による人工解が出ない。

    配分 LP はバイナリゼロの min-cost 透過配分なので、τ を直接最小化する厳密
    モードより残留 τ は大きくなりうるが、下回る（フローを循環で水増しして
    停滞を見かけ上排出する）ことはない。
    """
    from flow_control.optimization import ResolvedConfig

    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
    )
    assert result.optimization_result.solver_status == SolverStatus.LIGHTWEIGHT
    assert result.optimization_result.objective_values.tau_star >= 2.4 - 1e-3


def test_phase2_skipped_when_no_throughput_targets(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_history,
    config,
):
    # 迂回路・オペレータ指定ルートが無ければ Phase 2 はスキップされる
    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        DetourResult(),  # P = ∅
        worked_example_history,
        previous_result=None,
        config=config,
        seed=1,
        time_limit=30.0,
    )
    assert result.solver_stats.phase2_status == Phase2Status.SKIPPED
    # Phase 1 単独でも τ* は変わらない
    assert result.optimization_result.objective_values.tau_star == pytest.approx(
        2.4, abs=1e-3
    )


def test_deterministic_across_runs(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
    config,
):
    results = [
        optimize(
            worked_example_graph,
            worked_example_observations,
            worked_example_forecast,
            worked_example_detour,
            worked_example_history,
            previous_result=None,
            config=config,
            seed=7,
            time_limit=30.0,
        ).optimization_result
        for _ in range(3)
    ]
    assert results[0] == results[1] == results[2]


def test_closed_mode_has_no_boundary_control(
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
    config,
):
    # 境界ノードを持たないグラフ（Closed モード）では境界制御を出さない
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

    n1, n2, n3 = NodeID("n1"), NodeID("n2"), NodeID("n3")

    def mk(eid, a, b):
        return Edge(
            EdgeID(eid),
            a,
            b,
            DirectionConstraint.BIDIRECTIONAL_PRIOR,
            CurrentDirection.BIDIRECTIONAL,
            True,
            ObservationType.VECTOR,
        )

    closed_graph = Graph(
        nodes=(
            Node(n1, NodeKind.GOAL, is_boundary=False, enabled=True),
            Node(n2, NodeKind.TRANSIT_ONLY, is_boundary=False, enabled=True),
            Node(n3, NodeKind.GOAL, is_boundary=False, enabled=True),
        ),
        edges=(mk("e12", n1, n2), mk("e23", n2, n3), mk("e13", n1, n3)),
    )
    result = optimize(
        closed_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=config,
        seed=1,
        time_limit=30.0,
        mode=Mode.CLOSED,
    )
    assert result.optimization_result.boundary_control == ()
    # Closed モードでも τ 最適化は成立する
    assert result.optimization_result.solver_status == SolverStatus.OPTIMAL


def test_lightweight_is_default_and_reports_baseline_stats(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
):
    """設計 v0 の既定は current 方向を使う軽量配分である。"""
    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
        triggered_edges=(),
        triggered_nodes=(),
    )

    assert result.optimization_result.solver_status == SolverStatus.LIGHTWEIGHT
    assert result.solver_stats.phase1_status == SolverStatus.LIGHTWEIGHT
    assert result.solver_stats.assign_lp_ms >= 0
    assert result.solver_stats.greedy_iterations == 0
    assert result.solver_stats.zones_processed == 0
    # phase1_ms は互換フィールドとして「構築＋配分 LP 求解の合計」を格納する
    assert result.solver_stats.phase1_ms == (
        result.solver_stats.build_ms + result.solver_stats.assign_lp_ms
    )
    assert not result.solver_stats.greedy_truncated
    assert ResolvedConfig().optimization_mode == OptimizationMode.LIGHTWEIGHT


def test_lightweight_zone_greedy_processes_trigger_zone(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
):
    """トリガーがあればゾーンが構成され、候補はゾーン限定 LP で評価される。"""
    from flow_control.domain import EdgeID

    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        time_limit=30.0,
        triggered_edges=(EdgeID("e12"),),
        triggered_nodes=(),
    )

    assert result.optimization_result.solver_status == SolverStatus.LIGHTWEIGHT
    assert result.solver_stats.zones_processed == 1
    assert result.solver_stats.greedy_iterations > 0
    assert not result.solver_stats.localization_capped
    # 候補が採用されない場合はベースライン（近似残留 τ）に一致する
    assert result.optimization_result.objective_values.tau_star >= 0.0
    assert result.constraint_report.local_reachability_satisfied


def test_zone_net_supply_folds_crossing_flows():
    """横断アークの固定フローが純供給へ正しい符号で畳み込まれる。"""
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
    from flow_control.optimization.model import Commodity
    from flow_control.optimization.optimizer import _zone_net_supply

    def node(name, boundary=False):
        return Node(
            node_id=NodeID(name),
            kind=NodeKind.GOAL if boundary else NodeKind.TRANSIT_ONLY,
            is_boundary=boundary,
            enabled=True,
        )

    def edge(name, a, b):
        return Edge(
            edge_id=EdgeID(name),
            endpoint_a=NodeID(a),
            endpoint_b=NodeID(b),
            direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
            current_direction=CurrentDirection.BIDIRECTIONAL,
            enabled=True,
            observation_type=ObservationType.VECTOR,
        )

    # a - b - c の鎖。ゾーンは {b, c}（エッジ e_bc のみ）。e_ab は横断アーク
    graph = Graph(
        nodes=(node("a", boundary=True), node("b"), node("c", boundary=True)),
        edges=(edge("e_ab", "a", "b"), edge("e_bc", "b", "c")),
    )
    arc_model = build_arc_model(graph)
    commodities = (
        Commodity(index=0, origin=NodeID("b"), destination=NodeID("c"), demand=4.0),
    )
    # ベースライン: a→b に 3.0 流入（横断）
    flow = {"e_ab|A_TO_B": 3.0}
    supply = _zone_net_supply(
        arc_model,
        commodities,
        frozenset({EdgeID("e_bc")}),
        frozenset({NodeID("b"), NodeID("c")}),
        flow,
    )
    # b: OD 起点 +4.0、横断流入 +3.0 → 7.0。c: OD 終点 −4.0
    assert supply[NodeID("b")] == 7.0
    assert supply[NodeID("c")] == -4.0


def test_lightweight_budget_exhaustion_truncates_greedy(
    worked_example_graph,
    worked_example_observations,
    worked_example_forecast,
    worked_example_detour,
    worked_example_history,
):
    """予算が尽きたら貪欲探索を打ち切り、ベースライン解は床値で必ず返す。"""
    from flow_control.domain import EdgeID

    result = optimize(
        worked_example_graph,
        worked_example_observations,
        worked_example_forecast,
        worked_example_detour,
        worked_example_history,
        previous_result=None,
        config=ResolvedConfig(),
        seed=1,
        # ベースラインの構築＋求解だけで確実に使い切る極小予算
        time_limit=1e-6,
        triggered_edges=(EdgeID("e12"),),
        triggered_nodes=(),
    )

    assert result.optimization_result.solver_status == SolverStatus.LIGHTWEIGHT
    assert result.solver_stats.greedy_truncated
    assert result.solver_stats.greedy_iterations == 0
    # ベースライン配分は成立している（空の結果にならない）
    assert result.optimization_result.route_importance
