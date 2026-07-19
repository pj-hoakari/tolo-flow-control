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
from .model import (
    ArcSolution,
    Commodity,
    MilpInputs,
    build_model,
    solve_phase1,
    solve_phase2,
)
from .postprocess import compute_direction_proposals, compute_route_importance
from .boundary import compute_boundary_control
from .results import (
    ConstraintReport,
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

    if config.optimization_mode == OptimizationMode.LIGHTWEIGHT:
        return _optimize_lightweight(
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
        )

    built = build_model(
        arc_model, inputs, commodities, drain.drainable, is_open=is_open
    )
    t0 = time.perf_counter()
    p1 = solve_phase1(built, time_limit, seed, config.mip_rel_gap)
    phase1_ms = int((time.perf_counter() - t0) * 1000)

    if p1.status == SolverStatus.INFEASIBLE:
        return _fallback(
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
        )

    if p1.solution is None:
        # タイムアウト等でインカンベントが無い。最小結果を返し、再キューは呼出し側に委ねる
        return _empty_result(p1.status, solved_at, seed, phase1_ms)

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
    return OptimizeResult(opt_result, stats, report)


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
) -> OptimizeResult:
    """基本モードの全体ベースライン配分。

    方向を current に固定して配分するため、探索空間は連続フローだけとなる。
    方向変更の貪欲探索は、トリガーゾーンをこの結果で評価する後続段として
    拡張可能な形で統計へ明示する。安全性は固定方向と到達性検査で保つ。
    """
    fixed_x: dict[str, int] = {}
    for edge in arc_model.active_edges:
        fixed_x.update(fixed_directions(edge))
    built = build_model(
        arc_model, inputs, commodities, drainable, is_open=is_open, fixed_x=fixed_x
    )
    t0 = time.perf_counter()
    assignment = solve_phase1(built, time_limit, seed)
    assign_lp_ms = int((time.perf_counter() - t0) * 1000)
    zones = _zone_count(graph, triggered_edges, triggered_nodes, config.max_trigger_zones)

    solution = assignment.solution
    greedy_iterations = 0
    best_tau = assignment.objective if solution is not None else float("inf")
    # 方向候補はトリガー起点に限定し、edge_id 順で評価する。各候補は current
    # 以外の片方向化／解除を固定方向 LP で再配分し、Open の境界到達性と
    # ローカル可達性を満たすものだけを採用する。
    candidate_ids = sorted(
        {edge_id for edge_id in triggered_edges if edge_id in arc_model.arcs_of_edge},
        key=lambda edge_id: edge_id.value,
    )
    for edge_id in candidate_ids:
        current_direction = solution.direction if solution is not None else fixed_x
        for candidate_x in _direction_candidates(arc_model, edge_id, current_direction):
            greedy_iterations += 1
            candidate_built = build_model(
                arc_model,
                inputs,
                commodities,
                drainable,
                is_open=is_open,
                fixed_x=candidate_x,
            )
            candidate = solve_phase1(candidate_built, time_limit, seed)
            if candidate.solution is None or candidate.status == SolverStatus.INFEASIBLE:
                continue
            if not _local_reachability_ok(arc_model, candidate.solution):
                continue
            if is_open and not _boundary_reachability_ok(arc_model, candidate.solution):
                continue
            if solution is None or candidate.objective <= best_tau - config.greedy_improve_margin:
                solution = candidate.solution
                best_tau = candidate.objective

    # current 方向が不可解、または全候補を試しても安全な解が得られない場合は、
    # 不安全な結果を返さず設計 v0 §7.6 の保持フォールバックへ移行する。
    if solution is None or not _local_reachability_ok(arc_model, solution) or (
        is_open and not _boundary_reachability_ok(arc_model, solution)
    ):
        return _fallback(
            arc_model, inputs, commodities, drainable, graph, previous_result, config,
            seed, time_limit, solved_at, is_open, throughput_arcs, assign_lp_ms,
        )

    importance = compute_route_importance(arc_model, solution, config.epsilon_0)
    direction = compute_direction_proposals(arc_model, solution)
    boundary = compute_boundary_control(graph, is_open, previous_result)
    throughput = sum(solution.flow.get(arc.key, 0.0) for arc in throughput_arcs)
    boundary_ok = _boundary_reachability_ok(arc_model, solution) if is_open else True

    opt_result = OptimizationResult(
        route_importance=importance,
        direction_proposal=direction,
        boundary_control=boundary,
        objective_values=ObjectiveValues(tau_star=best_tau, throughput=throughput),
        solver_status=SolverStatus.LIGHTWEIGHT,
        solved_at=solved_at,
        seed=seed,
    )
    stats = SolverStats(
        solver_name="highs",
        phase1_status=SolverStatus.LIGHTWEIGHT,
        phase2_status=Phase2Status.LIGHTWEIGHT,
        phase1_ms=assign_lp_ms,
        phase2_ms=0,
        tau_star=best_tau,
        throughput=throughput,
        assign_lp_ms=assign_lp_ms,
        greedy_iterations=greedy_iterations,
        zones_processed=zones,
        tau_residual=best_tau,
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


def _zone_count(
    graph: Graph,
    triggered_edges: tuple[EdgeID, ...],
    triggered_nodes: tuple[NodeID, ...],
    maximum: int,
) -> int:
    """トリガー起点の連結ゾーン数（上限適用後）を決定的に数える。"""
    seeds = set(triggered_nodes)
    for edge_id in triggered_edges:
        edge = graph.edge_of(edge_id)
        if edge is not None and edge.enabled:
            seeds.update((edge.endpoint_a, edge.endpoint_b))
    if not seeds:
        return 0
    adjacency: dict[NodeID, set[NodeID]] = {}
    for edge in graph.enabled_edges():
        adjacency.setdefault(edge.endpoint_a, set()).add(edge.endpoint_b)
        adjacency.setdefault(edge.endpoint_b, set()).add(edge.endpoint_a)
    components: set[frozenset[NodeID]] = set()
    for seed_node in seeds:
        seen = {seed_node}
        todo = [seed_node]
        while todo:
            current = todo.pop()
            for neighbour in adjacency.get(current, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    todo.append(neighbour)
        components.add(frozenset(seen & seeds))
    return min(len(components), maximum)


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
    # 第 1 段: 方向を current_direction に固定した LP（可達性制約は除外）
    fixed_x: dict[str, int] = {}
    for edge in arc_model.active_edges:
        fixed_x.update(fixed_directions(edge))
    built_lp = build_model(
        arc_model, inputs, commodities, drainable, is_open=is_open, fixed_x=fixed_x
    )
    t0 = time.perf_counter()
    lp = solve_phase1(built_lp, time_limit, seed)
    lp_ms = int((time.perf_counter() - t0) * 1000)

    boundary = compute_boundary_control(graph, is_open, previous_result)

    if lp.solution is not None and lp.status in (
        SolverStatus.OPTIMAL,
        SolverStatus.FEASIBLE,
    ):
        importance = compute_route_importance(arc_model, lp.solution, config.epsilon_0)
        # 方向属性提案は出さず、前回提案を維持
        direction = previous_result.direction_proposal if previous_result else ()
        throughput = sum(lp.solution.flow.get(a.key, 0.0) for a in throughput_arcs)
        opt_result = OptimizationResult(
            route_importance=importance,
            direction_proposal=direction,
            boundary_control=boundary,
            objective_values=ObjectiveValues(tau_star=lp.objective, throughput=throughput),
            solver_status=SolverStatus.INFEASIBLE,
            solved_at=solved_at,
            seed=seed,
        )
        stats = SolverStats(
            solver_name="highs",
            phase1_status=SolverStatus.INFEASIBLE,
            phase2_status=Phase2Status.SKIPPED,
            phase1_ms=phase1_ms + lp_ms,
            phase2_ms=0,
            tau_star=lp.objective,
            throughput=throughput,
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
        phase1_ms=phase1_ms + lp_ms,
        phase2_ms=0,
        tau_star=opt_result.objective_values.tau_star,
        throughput=opt_result.objective_values.throughput,
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
