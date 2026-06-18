"""MILP モデルの構築・求解と固定方向 LP フォールバック（linopy + HiGHS）"""

# linopy / HiGHS は型スタブを提供せず、変数・式・ソルバー操作がすべて Any 型となる
# 本ファイルはソルバーとの境界であり、Any 由来の型警告のみを局所的に抑制する
# pyright: reportAny=false, reportExplicitAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import linopy

from ..domain.graph import EdgeID, NodeID
from .arcs import Arc, ArcModel
from .results import SolverStatus

_TIMEOUT_CONDITIONS = frozenset(
    {
        "time_limit",
        "terminated_by_limit",
        "iteration_limit",
        "resource_interrupt",
        "user_interrupt",
    }
)
_INFEASIBLE_CONDITIONS = frozenset(
    {"infeasible", "infeasible_or_unbounded", "unbounded"}
)
_FEASIBLE_CONDITIONS = frozenset({"suboptimal", "imprecise"})


@dataclass(frozen=True)
class Commodity:
    index: int
    origin: NodeID
    destination: NodeID
    demand: float


@dataclass(frozen=True)
class MilpInputs:
    s_obs: dict[EdgeID, float]  # 停滞観測（INVALID 除外済み）
    s_bar: dict[EdgeID, float]  # 基準停滞量（欠損は config 値で補完済み）
    eta: dict[EdgeID, float]  # フロー感度
    c_e: dict[EdgeID, float]  # 信頼度重み（下限クリップ済み）
    capacity_hint: dict[EdgeID, float]  # 容量ヒント（設定済みのみ）
    sigma: dict[EdgeID, float]  # スカラー観測人数
    scalar_edges: frozenset[EdgeID]
    edge_danger_capacity: dict[EdgeID, float]  # 危険フラグ由来のアーク容量上限
    node_danger_capacity: dict[NodeID, float]  # 危険フラグ由来のノード通過量上限
    big_m: float
    epsilon: float
    epsilon_0: float


@dataclass(frozen=True)
class ArcSolution:
    flow: dict[str, float]  # arc.key -> 総フロー f_a
    direction: dict[str, int]  # arc.key -> x_a（0/1）
    tau: float


@dataclass(frozen=True)
class PhaseResult:
    status: SolverStatus
    solution: ArcSolution | None
    objective: float


@dataclass
class _Built:
    model: Any
    x: dict[str, Any]
    f: dict[tuple[str, int], Any]
    tau: Any
    arc_model: ArcModel
    commodities: tuple[Commodity, ...]
    fixed_x: dict[str, int] | None
    infeasible: bool = False


def _vsum(terms: list[Any]) -> Any | None:
    if not terms:
        return None
    expr = terms[0]
    for term in terms[1:]:
        expr = expr + term
    return expr


def _balance(out_expr: Any | None, in_expr: Any | None) -> Any | None:
    """流出側 − 流入側 の差を返す

    両方空なら None（孤立節点）
    """
    if out_expr is not None and in_expr is not None:
        return out_expr - in_expr
    if out_expr is not None:
        return out_expr
    if in_expr is not None:
        return -in_expr
    return None


def _arc_flow_terms(built: _Built, arc: Arc) -> list[Any]:
    return [
        built.f[(arc.key, k.index)]
        for k in built.commodities
        if (arc.key, k.index) in built.f
    ]


def _edge_flow_terms(built: _Built, edge_id: EdgeID) -> list[Any]:
    terms: list[Any] = []
    for arc in built.arc_model.arcs_of_edge.get(edge_id, ()):
        terms.extend(_arc_flow_terms(built, arc))
    return terms


def build_model(
    arc_model: ArcModel,
    inputs: MilpInputs,
    commodities: tuple[Commodity, ...],
    drainable: frozenset[EdgeID],
    *,
    is_open: bool,
    fixed_x: dict[str, int] | None = None,
) -> _Built:
    """MILP（fixed_x=None）または固定方向 LP（fixed_x 指定）を構築

    fixed_x 指定時は方向変数 x を作らず、方向属性・可達性制約を除外した
    フロー保存＋容量のみの LP となる（INFEASIBLE 時のフォールバック用）
    """
    model = linopy.Model()
    is_milp = fixed_x is None

    # 方向変数 x（MILP のみ）。α=0 は無効に固定、β=1 は事前値に固定
    x: dict[str, Any] = {}
    if is_milp:
        for i, arc in enumerate(arc_model.arcs):
            alpha = arc_model.alpha.get(arc.key, 1)
            beta = arc_model.beta.get(arc.key, 0)
            if beta == 1:
                x[arc.key] = model.add_variables(
                    lower=alpha, upper=alpha, integer=True, name=f"x{i}"
                )
            elif alpha == 0:
                x[arc.key] = model.add_variables(
                    lower=0, upper=0, integer=True, name=f"x{i}"
                )
            else:
                x[arc.key] = model.add_variables(binary=True, name=f"x{i}")

    # コモディティ別フロー f[arc, k]
    f: dict[tuple[str, int], Any] = {}
    for ai, arc in enumerate(arc_model.arcs):
        for k in commodities:
            f[(arc.key, k.index)] = model.add_variables(
                lower=0, name=f"f{ai}_{k.index}"
            )

    tau = model.add_variables(lower=0, name="tau")

    built = _Built(
        model=model,
        x=x,
        f=f,
        tau=tau,
        arc_model=arc_model,
        commodities=commodities,
        fixed_x=fixed_x,
    )

    big_m = inputs.big_m
    eps0 = inputs.epsilon_0
    n_nodes = len(arc_model.active_nodes)
    node_index = {v: i for i, v in enumerate(arc_model.active_nodes)}
    big_phi = n_nodes + 1

    # 非循環フロー（コモディティ別）: 利用フラグ z と節点ポテンシャル p で有向閉路を禁止
    # 各アークは z=1 のときのみフローを流せ、利用時は p_head >= p_tail + 1 を課す
    # これにより需要を運ばない循環（往復・閉路）を構造的に排除し、フローが停滞を
    # 見かけ上「排出」するのを防ぐ
    potential: dict[tuple[NodeID, int], Any] = {}
    for k in commodities:
        for v in arc_model.active_nodes:
            potential[(v, k.index)] = model.add_variables(
                lower=0, upper=max(1, n_nodes), name=f"p{node_index[v]}_{k.index}"
            )
    for ai, arc in enumerate(arc_model.arcs):
        for k in commodities:
            z = model.add_variables(binary=True, name=f"z{ai}_{k.index}")
            fv = f[(arc.key, k.index)]
            # フローは利用フラグが立つアークにのみ流せる
            # 非循環下では単一コモディティの 1 アーク流量は需要 d_k を超えないため、
            # Big-M を d_k にタイト化する（global big_m より緩和が強く分枝が減る・同値変換）
            m_arc = k.demand if k.demand > 1e-9 else big_m
            model.add_constraints(fv - m_arc * z <= 0)
            # 有効な向き（MILP は x、フォールバックは固定方向）にのみ利用可能
            if is_milp:
                model.add_constraints(z - x[arc.key] <= 0)
            elif fixed_x.get(arc.key, 0) == 0:
                model.add_constraints(z <= 0)
            # 利用時はポテンシャルが増加する（閉路を禁止）
            ph = potential[(arc.head, k.index)]
            pt = potential[(arc.tail, k.index)]
            model.add_constraints(ph - pt - big_phi * z >= 1 - big_phi)

    # フロー保存
    for k in commodities:
        for v in arc_model.active_nodes:
            out_expr = _vsum([f[(a.key, k.index)] for a in arc_model.arcs_out(v)])
            in_expr = _vsum([f[(a.key, k.index)] for a in arc_model.arcs_in(v)])
            if v == k.origin:
                rhs = k.demand
            elif v == k.destination:
                rhs = -k.demand
            else:
                rhs = 0.0
            lhs = _balance(out_expr, in_expr)
            if lhs is None:
                if rhs != 0.0:
                    built.infeasible = True
                continue
            model.add_constraints(lhs == rhs)

    # 容量上限（危険フラグ由来のアーク容量）
    for edge in arc_model.active_edges:
        cap = inputs.edge_danger_capacity.get(edge.edge_id)
        if cap is None:
            continue
        for arc in arc_model.arcs_of_edge.get(edge.edge_id, ()):
            expr = _vsum(_arc_flow_terms(built, arc))
            if expr is not None:
                model.add_constraints(expr <= cap)

    # 容量ヒント上限・スカラー型パンク制約（エッジ総フロー）
    for edge in arc_model.active_edges:
        hint = inputs.capacity_hint.get(edge.edge_id)
        if hint is None:
            continue
        edge_expr = _vsum(_edge_flow_terms(built, edge.edge_id))
        if edge_expr is None:
            continue
        model.add_constraints(edge_expr <= hint)
        if edge.edge_id in inputs.scalar_edges:
            sigma = inputs.sigma.get(edge.edge_id, 0.0)
            model.add_constraints(edge_expr <= max(0.0, hint - sigma))

    # ノード通過量上限（ノード危険フラグ）
    for v, cap in inputs.node_danger_capacity.items():
        terms: list[Any] = []
        for arc in arc_model.arcs_in(v):
            terms.extend(_arc_flow_terms(built, arc))
        expr = _vsum(terms)
        if expr is not None:
            model.add_constraints(expr <= cap)

    # 停滞量の線形化（排出可能エッジ）と排出上限
    for edge in arc_model.active_edges:
        eid = edge.edge_id
        if eid not in inputs.s_obs:
            continue
        s_obs = inputs.s_obs[eid]
        eta = inputs.eta.get(eid, 0.0)
        edge_expr = _vsum(_edge_flow_terms(built, eid))

        if eid in drainable:
            s_bar = inputs.s_bar.get(eid, 0.0)
            c_e = inputs.c_e.get(eid, 1.0)
            # tau*(s̄_e + ε0) + c_e*η_e*f_e >= c_e*s_obs
            lhs = tau * (s_bar + eps0)
            if edge_expr is not None and eta != 0.0:
                lhs = lhs + (c_e * eta) * edge_expr
            model.add_constraints(lhs >= c_e * s_obs)

        # 排出上限（線形近似の妥当域ガード）: η_e*f_e <= s_obs
        if eta > 0.0 and edge_expr is not None:
            model.add_constraints(eta * edge_expr <= s_obs)

    if is_milp:
        _add_direction_and_reachability(built, is_open=is_open)

    return built


def _add_direction_and_reachability(built: _Built, *, is_open: bool) -> None:
    model = built.model
    arc_model = built.arc_model
    x = built.x

    # 各エッジで少なくとも 1 方向有効（完全閉鎖防止）
    for edge in arc_model.active_edges:
        terms = [x[a.key] for a in arc_model.arcs_of_edge.get(edge.edge_id, ())]
        expr = _vsum(terms)
        if expr is not None:
            model.add_constraints(expr >= 1)

    # ローカル可達性: 各有効ノードに出方向・入方向を 1 つ以上
    for v in arc_model.active_nodes:
        out_expr = _vsum([x[a.key] for a in arc_model.arcs_out(v)])
        if out_expr is not None:
            model.add_constraints(out_expr >= 1)
        in_expr = _vsum([x[a.key] for a in arc_model.arcs_in(v)])
        if in_expr is not None:
            model.add_constraints(in_expr >= 1)

    # 入退出点ペア間可達性（Open モードのみ）
    if not is_open or not arc_model.entry_nodes:
        return
    r = arc_model.entry_nodes[0]
    n = len(arc_model.active_nodes)

    y_out: dict[str, Any] = {}
    y_in: dict[str, Any] = {}
    for i, arc in enumerate(arc_model.arcs):
        y_out[arc.key] = model.add_variables(lower=0, name=f"yo{i}")
        y_in[arc.key] = model.add_variables(lower=0, name=f"yi{i}")

    for aux, sign in ((y_out, 1), (y_in, -1)):
        for v in arc_model.active_nodes:
            out_expr = _vsum([aux[a.key] for a in arc_model.arcs_out(v)])
            in_expr = _vsum([aux[a.key] for a in arc_model.arcs_in(v)])
            base = (n - 1) if v == r else -1
            rhs = float(sign * base)
            lhs = _balance(out_expr, in_expr)
            if lhs is None:
                if rhs != 0.0:
                    built.infeasible = True
                continue
            model.add_constraints(lhs == rhs)
        # 補助フローは有効な向きにのみ流せる: y_a <= N * x_a
        for arc in arc_model.arcs:
            model.add_constraints(aux[arc.key] - n * x[arc.key] <= 0)


def _map_status(condition: str, has_solution: bool) -> SolverStatus:
    if condition == "optimal":
        return SolverStatus.OPTIMAL
    if condition in _FEASIBLE_CONDITIONS:
        return SolverStatus.FEASIBLE
    if condition in _TIMEOUT_CONDITIONS:
        return SolverStatus.TIMEOUT
    if condition in _INFEASIBLE_CONDITIONS:
        return SolverStatus.INFEASIBLE
    # error / unknown 等はフォールバックを誘発させる
    return SolverStatus.OPTIMAL if has_solution else SolverStatus.INFEASIBLE


def _value(var: Any) -> float:
    return float(var.solution.item())


def _extract(built: _Built) -> ArcSolution | None:
    try:
        tau_val = _value(built.tau)
    except Exception:
        return None
    if math.isnan(tau_val):
        return None

    flow: dict[str, float] = {}
    for arc in built.arc_model.arcs:
        total = 0.0
        for k in built.commodities:
            var = built.f.get((arc.key, k.index))
            if var is None:
                continue
            total += _value(var)
        flow[arc.key] = total

    direction: dict[str, int] = {}
    for arc in built.arc_model.arcs:
        if built.fixed_x is not None:
            direction[arc.key] = built.fixed_x.get(arc.key, 0)
        else:
            direction[arc.key] = int(round(_value(built.x[arc.key])))

    return ArcSolution(flow=flow, direction=direction, tau=tau_val)


def _solve(model: Any, time_limit: float, seed: int, mip_rel_gap: float = 0.0) -> str:
    options: dict[str, Any] = dict(
        solver_name="highs",
        time_limit=float(time_limit),
        threads=1,
        random_seed=int(seed),
        output_flag=False,
    )
    if mip_rel_gap > 0.0:
        options["mip_rel_gap"] = float(mip_rel_gap)
    model.solve(**options)
    return str(model.termination_condition)


def solve_phase1(
    built: _Built, time_limit: float, seed: int, mip_rel_gap: float = 0.0
) -> PhaseResult:
    if built.infeasible:
        return PhaseResult(SolverStatus.INFEASIBLE, None, 0.0)
    built.model.add_objective(built.tau, sense="min", overwrite=True)
    condition = _solve(built.model, time_limit, seed, mip_rel_gap)
    solution = _extract(built)
    status = _map_status(condition, solution is not None)
    if solution is None:
        return PhaseResult(status, None, 0.0)
    return PhaseResult(status, solution, solution.tau)


def solve_phase2(
    built: _Built,
    tau_star: float,
    throughput_arcs: tuple[Arc, ...],
    epsilon: float,
    time_limit: float,
    seed: int,
    mip_rel_gap: float = 0.0,
) -> PhaseResult:
    # 辞書式緩和: τ <= τ* + ε
    built.model.add_constraints(built.tau <= tau_star + epsilon, name="lex")
    terms: list[Any] = []
    for arc in throughput_arcs:
        terms.extend(_arc_flow_terms(built, arc))
    objective = _vsum(terms)
    if objective is None:
        return PhaseResult(SolverStatus.OPTIMAL, _extract(built), 0.0)
    built.model.add_objective(objective, sense="max", overwrite=True)
    condition = _solve(built.model, time_limit, seed, mip_rel_gap)
    solution = _extract(built)
    status = _map_status(condition, solution is not None)
    throughput = sum(solution.flow[a.key] for a in throughput_arcs) if solution else 0.0
    return PhaseResult(status, solution, throughput)
