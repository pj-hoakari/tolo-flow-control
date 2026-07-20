"""Optimization Step のオーケストレーション

2 段階辞書式 MILP（最大停滞量の最小化 → 特定ルートのスループット最大化）を解き、
重要度スコア・方向属性提案・境界制御提案を返す。INFEASIBLE 時は
方向固定 LP → 前回結果コピーの二段フォールバックを行う
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

from ..domain.enums import Mode, ObservationType
from ..domain.graph import EdgeID, Graph, NodeID
from ..domain.history import HistoryDigest
from ..domain.observations import ConfidenceFlag, Observations
from .arcs import Arc, ArcModel, build_arc_model, fixed_directions
from .config import OptimizationMode, ResolvedConfig
from .drainable import compute_drainable, reachable_forward
from .localization import TriggerZone, build_trigger_zones
from .model import (
    ArcSolution,
    Commodity,
    MilpInputs,
    build_assignment_lp,
    build_model,
    build_zone_lp,
    evaluate_residual_tau,
    solve_assignment,
    solve_phase1,
    solve_phase2,
    solve_zone_lp,
)
from .postprocess import compute_direction_proposals, compute_route_importance
from .restriction import (
    assess_residual,
    build_restriction_proposals,
    build_resume_proposals,
    evaluate_detour_gate,
)
from .boundary import compute_boundary_control
from .results import (
    ConstraintReport,
    RestrictionProposal,
    RouteImportance,
    ObjectiveValues,
    OptimizationResult,
    OptimizeResult,
    Phase2Status,
    SolverStats,
    SolverStatus,
)

# フォワード参照のため ForecastResult / DetourResult は型注釈のみで取り込む
from ..forecasting import ForecastResult
from ..detour_routing import DetourResult

# 予算枯渇後もベースライン配分・フォールバックには最低限渡す求解時間（秒）。
# 空の結果よりは僅かに超過してでも解を返す方が安全側のため
_MIN_SOLVE_SEC = 1.0


def optimize(
    graph: Graph,
    observations: Observations,
    forecast_result: ForecastResult,
    detour_result: DetourResult,
    history_digest: HistoryDigest,
    previous_result: OptimizationResult | None,
    config: ResolvedConfig,
    seed: int,
    time_limit: float,
    mode: Mode | None = None,
    *,
    triggered_edges: tuple[EdgeID, ...] = (),
    triggered_nodes: tuple[NodeID, ...] = (),
) -> OptimizeResult:
    is_open = (mode == Mode.OPEN) if mode is not None else (
        len(graph.boundary_nodes()) > 0
    )
    arc_model = build_arc_model(graph)
    active_node_set = set(arc_model.active_nodes)
    active_edge_ids = {e.edge_id for e in arc_model.active_edges}
    solved_at = observations.observed_at

    commodities = _build_commodities(forecast_result, active_node_set, config.delta_min)
    inputs = _build_inputs(
        graph, observations, forecast_result, history_digest, arc_model, commodities, config
    )

    od_pairs = tuple((k.origin, k.destination) for k in commodities)
    stagnation_edges = frozenset(inputs.s_obs.keys())
    drain = compute_drainable(arc_model, od_pairs, stagnation_edges)

    # スループット最大化対象 P = トリガー起点迂回路 ∪ オペレータ指定
    p_edges = (set(detour_result.trigger_edge_set()) | set(config.throughput_target_edges))
    p_edges &= active_edge_ids
    throughput_arcs = _throughput_arcs(arc_model, p_edges)

    # 需要カット診断: 「OD はあるのに delta_min で全カット→空提案」を統計へ顕在化する
    od_pairs_input = len(forecast_result.od_matrix)
    commodities_used = len(commodities)

    if config.optimization_mode == OptimizationMode.LIGHTWEIGHT:
        return _with_demand_diagnostics(
            _optimize_lightweight(
                arc_model,
                inputs,
                commodities,
                drain.drainable,
                graph,
                previous_result,
                config,
                seed,
                min(time_limit, config.lightweight_opt_budget_sec),
                solved_at,
                is_open,
                throughput_arcs,
                triggered_edges,
                triggered_nodes,
                detour_result,
                _outflow_averages(history_digest, graph),
                drain.undrainable,
            ),
            od_pairs_input,
            commodities_used,
        )

    built = build_model(
        arc_model, inputs, commodities, drain.drainable, is_open=is_open
    )
    t0 = time.perf_counter()
    p1 = solve_phase1(built, time_limit, seed, config.mip_rel_gap)
    phase1_ms = int((time.perf_counter() - t0) * 1000)

    if p1.status == SolverStatus.INFEASIBLE:
        return _with_demand_diagnostics(
            _fallback(
                arc_model,
                inputs,
                commodities,
                drain.drainable,
                graph,
                previous_result,
                config,
                seed,
                time_limit,
                solved_at,
                is_open,
                throughput_arcs,
                phase1_ms,
            ),
            od_pairs_input,
            commodities_used,
        )

    if p1.solution is None:
        # タイムアウト等でインカンベントが無い。最小結果を返し、再キューは呼出し側に委ねる
        return _with_demand_diagnostics(
            _empty_result(p1.status, solved_at, seed, phase1_ms),
            od_pairs_input,
            commodities_used,
        )

    final_solution: ArcSolution = p1.solution
    phase2_status = Phase2Status.SKIPPED
    phase2_ms = 0
    throughput = sum(final_solution.flow.get(a.key, 0.0) for a in throughput_arcs)

    run_phase2 = bool(throughput_arcs) and p1.status in (
        SolverStatus.OPTIMAL,
        SolverStatus.FEASIBLE,
    )
    if run_phase2:
        t1 = time.perf_counter()
        p2 = solve_phase2(
            built,
            p1.objective,
            throughput_arcs,
            config.epsilon,
            time_limit,
            seed,
            config.mip_rel_gap,
        )
        phase2_ms = int((time.perf_counter() - t1) * 1000)
        if p2.solution is not None and p2.status in (
            SolverStatus.OPTIMAL,
            SolverStatus.FEASIBLE,
        ):
            final_solution = p2.solution
            phase2_status = (
                Phase2Status.OPTIMAL
                if p2.status == SolverStatus.OPTIMAL
                else Phase2Status.FEASIBLE
            )
            throughput = p2.objective
        elif p2.status == SolverStatus.TIMEOUT:
            phase2_status = Phase2Status.SKIPPED
        elif p2.status == SolverStatus.INFEASIBLE:
            phase2_status = Phase2Status.INFEASIBLE

    importance = compute_route_importance(arc_model, final_solution, config.epsilon_0)
    direction = compute_direction_proposals(arc_model, final_solution)
    boundary = compute_boundary_control(graph, is_open, previous_result)

    opt_result = OptimizationResult(
        route_importance=importance,
        direction_proposal=direction,
        boundary_control=boundary,
        objective_values=ObjectiveValues(tau_star=p1.objective, throughput=throughput),
        solver_status=p1.status,
        solved_at=solved_at,
        seed=seed,
    )
    stats = SolverStats(
        solver_name="highs",
        phase1_status=p1.status,
        phase2_status=phase2_status,
        phase1_ms=phase1_ms,
        phase2_ms=phase2_ms,
        tau_star=p1.objective,
        throughput=throughput,
    )
    report = ConstraintReport(
        local_reachability_satisfied=_local_reachability_ok(arc_model, final_solution),
        boundary_reachability_satisfied=(
            _boundary_reachability_ok(arc_model, final_solution) if is_open else True
        ),
        legal_fixed_violations=_legal_violations(arc_model, final_solution),
        fallback_to_previous=False,
    )
    return _with_demand_diagnostics(
        OptimizeResult(opt_result, stats, report), od_pairs_input, commodities_used
    )


def _with_demand_diagnostics(
    result: OptimizeResult, od_pairs_input: int, commodities_used: int
) -> OptimizeResult:
    stats = replace(
        result.solver_stats,
        od_pairs_input=od_pairs_input,
        commodities_used=commodities_used,
        demand_all_cut=od_pairs_input > 0 and commodities_used == 0,
    )
    return replace(result, solver_stats=stats)


def _optimize_lightweight(
    arc_model: ArcModel,
    inputs: MilpInputs,
    commodities: tuple[Commodity, ...],
    drainable: frozenset[EdgeID],
    graph: Graph,
    previous_result: OptimizationResult | None,
    config: ResolvedConfig,
    seed: int,
    time_limit: float,
    solved_at: datetime,
    is_open: bool,
    throughput_arcs: tuple[Arc, ...],
    triggered_edges: tuple[EdgeID, ...],
    triggered_nodes: tuple[NodeID, ...],
    detour_result: DetourResult,
    outflow_averages: dict[EdgeID, float],
    undrainable: frozenset[EdgeID],
) -> OptimizeResult:
    """基本モードの局所化つき配分。

    (i) 方向を current に固定した全体配分 LP（バイナリゼロの min-cost 透過配分）を
    1 回解き、全有効エッジの重要度と近似残留 τ の基準を得る。
    (ii) トリガー近傍のゾーンごとに、方向候補をゾーン限定 LP で再評価する。
    ゾーン外の方向・フローは current・ベースライン値に固定し、ゾーン横断アークの
    固定フローを純供給へ畳み込んで所与の流入出条件とする。ゾーン τ の改善が
    マージン超の候補だけを採用する。重要度は (i) の全体配分から、方向提案・
    残留 τ は採用後の合成解から出す。
    ベースラインが不可解の場合はゾーン純供給を構成できないため、全体 LP で
    候補を評価する縮退経路で解の救済を試みる（例: 逆向き固定レーンの解除）。

    時間予算 ``time_limit`` はモデル構築込みの deadline として持ち回り、
    各求解には残時間のみを渡す。残時間が尽きたら貪欲探索を打ち切る
    （``greedy_truncated``）。ベースライン配分だけは床値を保証して必ず試みる。
    """
    deadline = time.perf_counter() + time_limit
    fixed_x: dict[str, int] = {}
    for edge in arc_model.active_edges:
        fixed_x.update(fixed_directions(edge))
    t0 = time.perf_counter()
    built = build_assignment_lp(arc_model, inputs, commodities, fixed_x=fixed_x)
    build_sec = time.perf_counter() - t0
    t0 = time.perf_counter()
    assignment = solve_assignment(
        built, max(_MIN_SOLVE_SEC, deadline - time.perf_counter()), seed
    )
    assign_sec = time.perf_counter() - t0
    assign_lp_ms = int(assign_sec * 1000)

    baseline = assignment.solution
    if baseline is not None:
        baseline = replace(
            baseline,
            tau=evaluate_residual_tau(arc_model, inputs, drainable, baseline.flow),
        )

    # ゾーン抽出。重大度はゾーン τ と同じ正規化停滞ストレスで代表する
    severity = {
        eid: inputs.c_e.get(eid, 1.0)
        * s_obs
        / (inputs.s_bar.get(eid, 0.0) + inputs.epsilon_0)
        for eid, s_obs in inputs.s_obs.items()
    }
    localization = build_trigger_zones(
        arc_model,
        triggered_edges,
        triggered_nodes,
        local_radius_hops=config.local_radius_hops,
        max_trigger_zones=config.max_trigger_zones,
        edge_severity=severity,
    )

    solution = baseline
    greedy_iterations = 0
    greedy_truncated = False
    zones_processed = 0
    greedy_started = time.perf_counter()

    if baseline is None:
        # 縮退経路: 全体 LP で候補を評価（トリガーエッジ・ID 昇順）
        candidate_ids = sorted(
            {e for e in triggered_edges if e in arc_model.arcs_of_edge},
            key=lambda e: e.value,
        )
        for edge_id in candidate_ids:
            if greedy_truncated:
                break
            current_direction = (
                solution.direction if solution is not None else fixed_x
            )
            for candidate_x in _direction_candidates(
                arc_model, edge_id, current_direction
            ):
                remaining = deadline - time.perf_counter()
                if remaining <= 0.0:
                    greedy_truncated = True
                    break
                greedy_iterations += 1
                t0 = time.perf_counter()
                candidate_built = build_assignment_lp(
                    arc_model, inputs, commodities, fixed_x=candidate_x
                )
                build_sec += time.perf_counter() - t0
                t0 = time.perf_counter()
                candidate = solve_assignment(
                    candidate_built,
                    max(_MIN_SOLVE_SEC, deadline - time.perf_counter()),
                    seed,
                )
                assign_sec += time.perf_counter() - t0
                assign_lp_ms = int(assign_sec * 1000)
                if (
                    candidate.solution is None
                    or candidate.status == SolverStatus.INFEASIBLE
                ):
                    continue
                if not _local_reachability_ok(arc_model, candidate.solution):
                    continue
                if is_open and not _boundary_reachability_ok(
                    arc_model, candidate.solution
                ):
                    continue
                candidate_tau = evaluate_residual_tau(
                    arc_model, inputs, drainable, candidate.solution.flow
                )
                if solution is None or candidate_tau <= solution.tau - config.greedy_improve_margin:
                    solution = replace(candidate.solution, tau=candidate_tau)
    else:
        # ゾーン別貪欲: 各ゾーンをゾーン限定 LP で独立に評価する
        adopted_x = dict(fixed_x)
        composed_flow = dict(baseline.flow)
        for zone in localization.zones:
            if greedy_truncated:
                break
            zones_processed += 1
            zone_edge_set = frozenset(zone.edges)
            zone_node_set = frozenset(zone.nodes)
            zone_drainable = drainable & zone_edge_set
            net_supply = _zone_net_supply(
                arc_model, commodities, zone_edge_set, zone_node_set, composed_flow
            )
            zone_tau = evaluate_residual_tau(
                arc_model, inputs, zone_drainable, composed_flow
            )
            candidates = sorted(
                (e for e in zone.seed_edges if e in arc_model.arcs_of_edge),
                key=lambda e: (-severity.get(e, 0.0), e.value),
            )
            for edge_id in candidates:
                if greedy_truncated:
                    break
                for candidate_x in _direction_candidates(
                    arc_model, edge_id, adopted_x
                ):
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0.0:
                        greedy_truncated = True
                        break
                    greedy_iterations += 1
                    t0 = time.perf_counter()
                    built_zone = build_zone_lp(
                        arc_model,
                        inputs,
                        zone_edges=zone_edge_set,
                        zone_nodes=zone_node_set,
                        fixed_x=candidate_x,
                        net_supply=net_supply,
                    )
                    build_sec += time.perf_counter() - t0
                    t0 = time.perf_counter()
                    status, zone_flows = solve_zone_lp(
                        built_zone,
                        max(_MIN_SOLVE_SEC, deadline - time.perf_counter()),
                        seed,
                    )
                    assign_sec += time.perf_counter() - t0
                    assign_lp_ms = int(assign_sec * 1000)
                    if zone_flows is None or status == SolverStatus.INFEASIBLE:
                        continue
                    probe = ArcSolution(flow={}, direction=candidate_x, tau=0.0)
                    if not _local_reachability_ok(arc_model, probe):
                        continue
                    if is_open and not _boundary_reachability_ok(arc_model, probe):
                        continue
                    cand_flow = dict(composed_flow)
                    for eid in zone_edge_set:
                        for arc in arc_model.arcs_of_edge.get(eid, ()):
                            cand_flow[arc.key] = zone_flows.get(arc.key, 0.0)
                    cand_tau = evaluate_residual_tau(
                        arc_model, inputs, zone_drainable, cand_flow
                    )
                    if cand_tau <= zone_tau - config.greedy_improve_margin:
                        adopted_x = candidate_x
                        composed_flow = cand_flow
                        zone_tau = cand_tau
        solution = ArcSolution(
            flow=composed_flow,
            direction=adopted_x,
            tau=evaluate_residual_tau(arc_model, inputs, drainable, composed_flow),
        )
    greedy_sec = time.perf_counter() - greedy_started
    best_tau = solution.tau if solution is not None else float("inf")

    # current 方向が不可解、または全候補を試しても安全な解が得られない場合は、
    # 不安全な結果を返さず設計 v0 §7.6 の保持フォールバックへ移行する。
    if solution is None or not _local_reachability_ok(arc_model, solution) or (
        is_open and not _boundary_reachability_ok(arc_model, solution)
    ):
        return _fallback(
            arc_model, inputs, commodities, drainable, graph, previous_result, config,
            seed, max(_MIN_SOLVE_SEC, deadline - time.perf_counter()), solved_at,
            is_open, throughput_arcs, int((build_sec + assign_sec) * 1000),
        )

    # 分散段: τ を保ったまま等コストの並列ルートへ配分を散らす（混雑逓増）。
    # τ 最小化が第一目的なので、τ 維持制約を課したうえで事後検査して採用する
    spread_solution: ArcSolution | None = None
    if config.congestion_increment > 0.0:
        t0 = time.perf_counter()
        built_spread = build_assignment_lp(
            arc_model,
            inputs,
            commodities,
            fixed_x=solution.direction,
            congestion_increment=config.congestion_increment,
            tau_cap=best_tau + config.epsilon,
            drainable=drainable,
        )
        build_sec += time.perf_counter() - t0
        t0 = time.perf_counter()
        spread = solve_assignment(
            built_spread, max(_MIN_SOLVE_SEC, deadline - time.perf_counter()), seed
        )
        assign_sec += time.perf_counter() - t0
        assign_lp_ms = int(assign_sec * 1000)
        if spread.solution is not None and spread.status != SolverStatus.INFEASIBLE:
            spread_tau = evaluate_residual_tau(
                arc_model, inputs, drainable, spread.solution.flow
            )
            if spread_tau <= best_tau + config.epsilon:
                spread_solution = replace(spread.solution, tau=spread_tau)
                solution = spread_solution
                best_tau = min(best_tau, spread_tau)

    # 重要度は配分結果から出す。分散段が成立していればその解（並列路の利用が
    # 反映される）、なければ全体ベースライン配分（(i)）。救済時のみ救済解。
    if spread_solution is not None:
        importance_source = spread_solution
    else:
        importance_source = baseline if baseline is not None else solution
    importance = compute_route_importance(arc_model, importance_source, config.epsilon_0)
    direction = compute_direction_proposals(arc_model, solution)
    boundary = compute_boundary_control(graph, is_open, previous_result)
    throughput = sum(solution.flow.get(arc.key, 0.0) for arc in throughput_arcs)
    boundary_ok = _boundary_reachability_ok(arc_model, solution) if is_open else True

    restrictions = _compute_restrictions(
        arc_model,
        inputs,
        config,
        localization.zones,
        solution=solution,
        drainable=drainable,
        undrainable=undrainable,
        detour_result=detour_result,
        triggered_edges=triggered_edges,
        importance=importance,
        outflow_averages=outflow_averages,
        previous_result=previous_result,
        is_open=is_open,
    )

    opt_result = OptimizationResult(
        route_importance=importance,
        direction_proposal=direction,
        restriction_proposal=restrictions,
        boundary_control=boundary,
        objective_values=ObjectiveValues(tau_star=best_tau, throughput=throughput),
        solver_status=SolverStatus.LIGHTWEIGHT,
        solved_at=solved_at,
        seed=seed,
    )
    build_ms = int(build_sec * 1000)
    stats = SolverStats(
        solver_name="highs",
        phase1_status=SolverStatus.LIGHTWEIGHT,
        phase2_status=Phase2Status.LIGHTWEIGHT,
        phase1_ms=build_ms + assign_lp_ms,
        phase2_ms=0,
        tau_star=best_tau,
        throughput=throughput,
        assign_lp_ms=assign_lp_ms,
        greedy_iterations=greedy_iterations,
        zones_processed=zones_processed,
        tau_residual=best_tau,
        build_ms=build_ms,
        greedy_ms=int(greedy_sec * 1000),
        greedy_truncated=greedy_truncated,
        localization_capped=localization.capped,
    )
    report = ConstraintReport(
        local_reachability_satisfied=_local_reachability_ok(arc_model, solution),
        boundary_reachability_satisfied=boundary_ok,
        legal_fixed_violations=_legal_violations(arc_model, solution),
        fallback_to_previous=False,
    )
    return OptimizeResult(opt_result, stats, report)


def _direction_candidates(
    arc_model: ArcModel, edge_id: EdgeID, current: dict[str, int]
) -> tuple[dict[str, int], ...]:
    """軽量貪欲で評価する、事前制約に適合した 1 エッジ変更候補。"""
    arcs = arc_model.arcs_of_edge[edge_id]
    edge = next(edge for edge in arc_model.active_edges if edge.edge_id == edge_id)
    candidates: list[dict[str, int]] = []
    for enabled in ((1, 0), (0, 1), (1, 1)):
        proposal = dict(current)
        valid = True
        for arc, value in zip(arcs, enabled, strict=True):
            if value > arc_model.alpha[arc.key]:
                valid = False
                break
            if arc_model.beta[arc.key] and value != arc_model.alpha[arc.key]:
                valid = False
                break
            proposal[arc.key] = value
        if not valid or proposal == current:
            continue
        # 解除は BIDIRECTIONAL_PRIOR のみ許可する。
        if enabled == (1, 1) and edge.direction_constraint.name != "BIDIRECTIONAL_PRIOR":
            continue
        candidates.append(proposal)
    return tuple(candidates)


def _outflow_averages(
    history_digest: HistoryDigest, graph: Graph
) -> dict[EdgeID, float]:
    """各エッジの排出実績 μ̂_e（方向別ライン通過の直近平均）を集める

    ラインなし（directional_flow_samples が None）のエッジは含めない。
    limit_value 算定で「実測の直接量」を第一候補にするための入力。
    """
    averages: dict[EdgeID, float] = {}
    for edge in graph.enabled_edges():
        window = history_digest.window_series_of(edge.edge_id)
        if window is None or window.directional_flow_samples is None:
            continue
        values = [
            value
            for _, samples in window.directional_flow_samples
            for _, value in samples
        ]
        if values:
            averages[edge.edge_id] = sum(values) / len(values)
    return averages


def _compute_restrictions(
    arc_model: ArcModel,
    inputs: MilpInputs,
    config: ResolvedConfig,
    zones: tuple[TriggerZone, ...],
    *,
    solution: ArcSolution,
    drainable: frozenset[EdgeID],
    undrainable: frozenset[EdgeID],
    detour_result: DetourResult,
    triggered_edges: tuple[EdgeID, ...],
    importance: tuple[RouteImportance, ...],
    outflow_averages: dict[EdgeID, float],
    previous_result: OptimizationResult | None,
    is_open: bool,
) -> tuple[RestrictionProposal, ...]:
    """機能2（通行制限提案）: ゾーンごとに残留＋Detour ゲートを評価して提案を組む

    ``restriction_proposal_enabled`` が False、または ``tau_danger_threshold`` が
    None なら機能2 は無効（提案なし）。既存 RESUME は無効時も評価しない
    （機能自体が切られている状態で解除だけ出すのは一貫しないため）。
    """
    theta = config.tau_danger_threshold
    if not config.restriction_proposal_enabled or theta is None:
        return ()

    arc_keys_of_edge = {
        edge.edge_id: tuple(
            arc.key for arc in arc_model.arcs_of_edge.get(edge.edge_id, ())
        )
        for edge in arc_model.active_edges
    }
    importance_map = {ri.edge_id: ri.importance for ri in importance}
    triggered_set = frozenset(triggered_edges)

    proposals: list[RestrictionProposal] = []
    for zone in zones:
        zone_edges = frozenset(zone.edges)
        zone_triggers = frozenset(zone.seed_edges) & zone_edges
        if not zone_triggers:
            continue
        zone_tau = evaluate_residual_tau(
            arc_model, inputs, drainable & zone_edges, solution.flow
        )
        residual = assess_residual(
            inputs,
            zone_edges=zone_edges,
            tau_zone=zone_tau,
            flow=solution.flow,
            arc_keys_of_edge=arc_keys_of_edge,
            undrainable=undrainable,
            tau_danger_threshold=theta,
        )
        if not residual.residual:
            continue

        detour_edges: set[EdgeID] = set()
        k_effective = 0
        for origin in sorted(zone_triggers, key=lambda e: e.value):
            detour_set = detour_result.detour_set_of(origin)
            if detour_set is None:
                continue
            k_effective = max(k_effective, detour_set.k_effective)
            detour_edges |= set(detour_set.edge_set())
        detour_edges -= zone_triggers

        gate = evaluate_detour_gate(
            inputs,
            detour_edges=frozenset(detour_edges),
            k_effective=k_effective,
            flow=solution.flow,
            arc_keys_of_edge=arc_keys_of_edge,
            triggered_edges=triggered_set,
            watched_edges=frozenset(),
            tau_danger_threshold=theta,
        )
        proposals.extend(
            build_restriction_proposals(
                arc_model,
                inputs,
                residual=residual,
                gate=gate,
                danger_edges=zone_triggers,
                zone_edges=zone_edges,
                flow=solution.flow,
                direction=solution.direction,
                importance=importance_map,
                outflow_averages=outflow_averages,
                is_open=is_open,
            )
        )

    restricted_now = frozenset(p.edge_id for p in proposals)
    proposals.extend(
        build_resume_proposals(previous_result, still_restricted=restricted_now)
    )
    return tuple(proposals)


def _zone_net_supply(
    arc_model: ArcModel,
    commodities: tuple[Commodity, ...],
    zone_edges: frozenset[EdgeID],
    zone_nodes: frozenset[NodeID],
    flow: dict[str, float],
) -> dict[NodeID, float]:
    """ゾーン限定 LP の純供給 b_v を組む

    b_v = （ゾーン内ノードの OD 需要の純供給）
          − Σ 横断流出アークの固定フロー ＋ Σ 横断流入アークの固定フロー。
    横断アーク（ゾーン誘導エッジに属さない接続アーク）はゾーン外扱いで
    ベースライン値に固定され、所与の流入出条件として畳み込まれる。
    """
    supply: dict[NodeID, float] = {v: 0.0 for v in zone_nodes}
    for k in commodities:
        if k.origin in supply:
            supply[k.origin] += k.demand
        if k.destination in supply:
            supply[k.destination] -= k.demand
    for v in zone_nodes:
        for arc in arc_model.arcs_out(v):
            if arc.edge_id not in zone_edges:
                supply[v] -= flow.get(arc.key, 0.0)
        for arc in arc_model.arcs_in(v):
            if arc.edge_id not in zone_edges:
                supply[v] += flow.get(arc.key, 0.0)
    return supply


def _build_commodities(
    forecast_result: ForecastResult, active_nodes: set[NodeID], delta_min: float
) -> tuple[Commodity, ...]:
    filtered = [
        od
        for od in forecast_result.od_matrix
        if od.demand > delta_min
        and od.origin in active_nodes
        and od.destination in active_nodes
    ]
    return tuple(
        Commodity(index=i, origin=od.origin, destination=od.destination, demand=od.demand)
        for i, od in enumerate(filtered)
    )


def _build_inputs(
    graph: Graph,
    observations: Observations,
    forecast_result: ForecastResult,
    history_digest: HistoryDigest,
    arc_model: ArcModel,
    commodities: tuple[Commodity, ...],
    config: ResolvedConfig,
) -> MilpInputs:
    active_edge_ids = {e.edge_id for e in arc_model.active_edges}

    s_obs: dict[EdgeID, float] = {}
    for st in observations.arc_stagnations:
        if st.confidence_flag == ConfidenceFlag.INVALID:
            continue
        if st.edge_id in active_edge_ids:
            s_obs[st.edge_id] = st.stagnation

    sigma: dict[EdgeID, float] = {}
    for sf in observations.arc_scalar_flows:
        if sf.confidence_flag == ConfidenceFlag.INVALID:
            continue
        if sf.edge_id in active_edge_ids:
            sigma[sf.edge_id] = sf.observed_count

    eta: dict[EdgeID, float] = {
        afs.edge_id: afs.eta for afs in forecast_result.arc_flow_sensitivity
    }
    conf: dict[NodeID, float] = {
        nc.node_id: nc.confidence for nc in forecast_result.node_confidence
    }

    s_bar: dict[EdgeID, float] = {}
    c_e: dict[EdgeID, float] = {}
    capacity_hint: dict[EdgeID, float] = {}
    edge_danger_capacity: dict[EdgeID, float] = {}
    scalar_edges: set[EdgeID] = set()
    for edge in arc_model.active_edges:
        stat = history_digest.stat_of(edge.edge_id)
        if stat is not None and stat.baseline_stagnation is not None:
            s_bar[edge.edge_id] = stat.baseline_stagnation
        else:
            s_bar[edge.edge_id] = config.fallback_baseline_stagnation

        conf_a = conf.get(edge.endpoint_a, 1.0)
        conf_b = conf.get(edge.endpoint_b, 1.0)
        c_e[edge.edge_id] = max(config.confidence_weight_floor, min(conf_a, conf_b))

        if edge.capacity_hint is not None:
            capacity_hint[edge.edge_id] = edge.capacity_hint
        if edge.danger_capacity is not None:
            edge_danger_capacity[edge.edge_id] = edge.danger_capacity
        if edge.observation_type == ObservationType.SCALAR:
            scalar_edges.add(edge.edge_id)

    node_danger_capacity: dict[NodeID, float] = {}
    for node in graph.enabled_nodes():
        if node.danger_flag and node.danger_capacity is not None:
            node_danger_capacity[node.node_id] = node.danger_capacity

    total_demand = sum(k.demand for k in commodities)
    finite_caps = (
        list(edge_danger_capacity.values())
        + list(node_danger_capacity.values())
        + list(capacity_hint.values())
    )
    max_cap = max(finite_caps) if finite_caps else 0.0
    big_m = (total_demand + max_cap + 1.0) * config.big_m_factor

    return MilpInputs(
        s_obs=s_obs,
        s_bar=s_bar,
        eta=eta,
        c_e=c_e,
        capacity_hint=capacity_hint,
        sigma=sigma,
        scalar_edges=frozenset(scalar_edges),
        edge_danger_capacity=edge_danger_capacity,
        node_danger_capacity=node_danger_capacity,
        big_m=big_m,
        epsilon=config.epsilon,
        epsilon_0=config.epsilon_0,
    )


def _throughput_arcs(arc_model: ArcModel, p_edges: set[EdgeID]) -> tuple[Arc, ...]:
    arcs: list[Arc] = []
    for edge in arc_model.active_edges:
        if edge.edge_id in p_edges:
            arcs.extend(arc_model.arcs_of_edge[edge.edge_id])
    return tuple(arcs)


def _local_reachability_ok(arc_model: ArcModel, solution: ArcSolution) -> bool:
    for v in arc_model.active_nodes:
        out_arcs = arc_model.arcs_out(v)
        in_arcs = arc_model.arcs_in(v)
        if out_arcs and not any(solution.direction.get(a.key, 0) == 1 for a in out_arcs):
            return False
        if in_arcs and not any(solution.direction.get(a.key, 0) == 1 for a in in_arcs):
            return False
    return True


def _boundary_reachability_ok(arc_model: ArcModel, solution: ArcSolution) -> bool:
    if not arc_model.entry_nodes:
        return True
    r = arc_model.entry_nodes[0]
    forward: dict[NodeID, list[NodeID]] = {}
    backward: dict[NodeID, list[NodeID]] = {}
    for arc in arc_model.arcs:
        if solution.direction.get(arc.key, 0) != 1:
            continue
        forward.setdefault(arc.tail, []).append(arc.head)
        backward.setdefault(arc.head, []).append(arc.tail)
    active = set(arc_model.active_nodes)
    return active <= reachable_forward(forward, r) and active <= reachable_forward(
        backward, r
    )


def _legal_violations(arc_model: ArcModel, solution: ArcSolution) -> tuple[EdgeID, ...]:
    bad: dict[str, EdgeID] = {}
    for arc in arc_model.arcs:
        if arc_model.beta.get(arc.key, 0) != 1:
            continue
        if solution.direction.get(arc.key, 0) != arc_model.alpha.get(arc.key, 0):
            bad[arc.edge_id.value] = arc.edge_id
    return tuple(bad[k] for k in sorted(bad))


def _fallback(
    arc_model: ArcModel,
    inputs: MilpInputs,
    commodities: tuple[Commodity, ...],
    drainable: frozenset[EdgeID],
    graph: Graph,
    previous_result: OptimizationResult | None,
    config: ResolvedConfig,
    seed: int,
    time_limit: float,
    solved_at: datetime,
    is_open: bool,
    throughput_arcs: tuple[Arc, ...],
    phase1_ms: int,
) -> OptimizeResult:
    # 第 1 段: 方向を current_direction に固定した配分 LP（可達性制約は除外）。
    # 容量超過はスラック化し、需要が容量を構造的に超える過密局面でも
    # 「最も違反の少ない配分」から重要度を返す（保存則は非緩和）
    fixed_x: dict[str, int] = {}
    for edge in arc_model.active_edges:
        fixed_x.update(fixed_directions(edge))
    t0 = time.perf_counter()
    built_lp = build_assignment_lp(
        arc_model, inputs, commodities, fixed_x=fixed_x, allow_capacity_slack=True
    )
    build_ms = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    lp = solve_assignment(built_lp, time_limit, seed)
    lp_ms = int((time.perf_counter() - t0) * 1000)

    boundary = compute_boundary_control(graph, is_open, previous_result)

    if lp.solution is not None and lp.status in (
        SolverStatus.OPTIMAL,
        SolverStatus.FEASIBLE,
    ):
        tau_val = evaluate_residual_tau(arc_model, inputs, drainable, lp.solution.flow)
        importance = compute_route_importance(arc_model, lp.solution, config.epsilon_0)
        # 方向属性提案は出さず、前回提案を維持
        direction = previous_result.direction_proposal if previous_result else ()
        throughput = sum(lp.solution.flow.get(a.key, 0.0) for a in throughput_arcs)
        opt_result = OptimizationResult(
            route_importance=importance,
            direction_proposal=direction,
            boundary_control=boundary,
            objective_values=ObjectiveValues(tau_star=tau_val, throughput=throughput),
            solver_status=SolverStatus.INFEASIBLE,
            solved_at=solved_at,
            seed=seed,
        )
        stats = SolverStats(
            solver_name="highs",
            phase1_status=SolverStatus.INFEASIBLE,
            phase2_status=Phase2Status.SKIPPED,
            phase1_ms=phase1_ms + build_ms + lp_ms,
            phase2_ms=0,
            tau_star=tau_val,
            throughput=throughput,
            assign_lp_ms=lp_ms,
            build_ms=build_ms,
        )
        report = ConstraintReport(
            local_reachability_satisfied=_local_reachability_ok(arc_model, lp.solution),
            boundary_reachability_satisfied=(
                _boundary_reachability_ok(arc_model, lp.solution) if is_open else True
            ),
            legal_fixed_violations=_legal_violations(arc_model, lp.solution),
            fallback_to_previous=True,
        )
        return OptimizeResult(opt_result, stats, report)

    # 第 2 段: LP も不可解 → 前回結果を全体コピー（無ければ提案なし）
    if previous_result is not None:
        opt_result = replace(
            previous_result,
            solver_status=SolverStatus.INFEASIBLE,
            solved_at=solved_at,
            seed=seed,
        )
    else:
        opt_result = OptimizationResult(
            solver_status=SolverStatus.INFEASIBLE, solved_at=solved_at, seed=seed
        )
    stats = SolverStats(
        solver_name="highs",
        phase1_status=SolverStatus.INFEASIBLE,
        phase2_status=Phase2Status.SKIPPED,
        phase1_ms=phase1_ms + build_ms + lp_ms,
        phase2_ms=0,
        tau_star=opt_result.objective_values.tau_star,
        throughput=opt_result.objective_values.throughput,
        assign_lp_ms=lp_ms,
        build_ms=build_ms,
    )
    report = ConstraintReport(
        local_reachability_satisfied=False,
        boundary_reachability_satisfied=False,
        legal_fixed_violations=(),
        fallback_to_previous=True,
    )
    return OptimizeResult(opt_result, stats, report)


def _empty_result(
    status: SolverStatus, solved_at: datetime, seed: int, phase1_ms: int
) -> OptimizeResult:
    opt_result = OptimizationResult(
        solver_status=status, solved_at=solved_at, seed=seed
    )
    stats = SolverStats(
        solver_name="highs",
        phase1_status=status,
        phase2_status=Phase2Status.SKIPPED,
        phase1_ms=phase1_ms,
        phase2_ms=0,
        tau_star=0.0,
        throughput=0.0,
    )
    report = ConstraintReport(
        local_reachability_satisfied=False,
        boundary_reachability_satisfied=False,
        legal_fixed_violations=(),
        fallback_to_previous=False,
    )
    return OptimizeResult(opt_result, stats, report)
