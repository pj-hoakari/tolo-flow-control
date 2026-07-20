"""最適化モデルの構築・求解（linopy + HiGHS）

- 厳密モード: 方向バイナリ・非循環バイナリを含む MILP（build_model / solve_phase1/2）
- 基本モード・フォールバック: 方向固定のバイナリゼロ配分 LP
  （build_assignment_lp / solve_assignment）。ホップ数重みの min-cost 配分で
  有向閉路を最適解から排除し、近似残留 τ は解のフローから事後評価する
"""

# linopy / HiGHS は型スタブを提供せず、変数・式・ソルバー操作がすべて Any 型となる
# 本ファイルはソルバーとの境界であり、Any 由来の型警告のみを局所的に抑制する
# pyright: reportAny=false, reportExplicitAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import linopy
import numpy as np
import pandas as pd
import xarray as xr

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

# 容量スラックの罰則係数。フロー 1 単位の輸送コスト（ホップ重み 1）より十分大きくし、
# 容量を守れる解があるかぎりスラックが立たないようにする
_SLACK_PENALTY = 1e6

# 混雑逓増コストの分割数（アーク総フローを等幅で何段に分けるか）
_COST_SEGMENTS = 3

# 既定値用の空集合（パラメータ既定式での関数呼び出しを避ける）
_NO_EDGES: frozenset[EdgeID] = frozenset()


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


@dataclass
class _BuiltAssignment:
    """配分 LP の構築結果（build_assignment_lp / solve_assignment 専用）"""

    model: Any
    f: Any  # linopy Variable（arc×k）。コモディティ or 有効アークなしは None
    arc_keys: tuple[str, ...]  # 変数を持つ有効アーク（変数順・決定的）
    arc_model: ArcModel
    commodities: tuple[Commodity, ...]
    fixed_x: dict[str, int] = field(default_factory=dict)
    infeasible: bool = False


def build_assignment_lp(
    arc_model: ArcModel,
    inputs: MilpInputs,
    commodities: tuple[Commodity, ...],
    *,
    fixed_x: dict[str, int],
    allow_capacity_slack: bool = False,
    congestion_increment: float = 0.0,
    tau_cap: float | None = None,
    drainable: frozenset[EdgeID] = _NO_EDGES,
) -> _BuiltAssignment:
    """基本モードの配分 LP（バイナリゼロ・方向 fixed_x 固定）を構築する

    有効な向きのアークにのみフロー変数を持ち、方向変数・非循環フラグ・τ 変数を
    一切作らない純 LP。目的はホップ数（アーク本数）重みの総フロー最小化で、
    正コストにより有向閉路を含む解が最適から排除される（構造的非循環）。
    τ は本 LP では扱わず、解のフローから ``evaluate_residual_tau`` で事後評価する。

    ``allow_capacity_slack=True`` では容量系上限（危険容量・容量ヒント・パンク・
    ノード通過量・排出上限）に非負スラックを付け、目的へ大きな罰則で加算する
    （フォールバック用）。需要が容量を構造的に超える過密局面でも「最も違反の
    少ない配分」を返せる。フロー保存則は非緩和のまま。

    ``congestion_increment>0`` では輸送コストをアーク総フローの区分線形凸関数に
    する（混雑逓増）。等コストの並列ルートへ配分を分散させるための機構で、
    詳細は目的関数の構築箇所を参照。``tau_cap`` を与えると近似残留 τ を
    その値以下に保つ制約を張る（分散が停滞抑制を悪化させないための上限）。

    変数・制約は linopy の配列 API で一括生成する（スカラー逐次追加は xarray の
    オーバーヘッドが支配的で構築が律速になるため）。並びはアーク定義順・
    コモディティ index 順で決定的に固定する。
    """
    model = linopy.Model()
    enabled = tuple(a for a in arc_model.arcs if fixed_x.get(a.key, 0) == 1)
    built = _BuiltAssignment(
        model=model,
        f=None,
        arc_keys=tuple(a.key for a in enabled),
        arc_model=arc_model,
        commodities=commodities,
        fixed_x=dict(fixed_x),
    )
    if not commodities:
        return built

    # 需要の起終点が有効アークに接続していなければ構造的に不可（求解不要）
    incident: set[NodeID] = set()
    for arc in enabled:
        incident.add(arc.tail)
        incident.add(arc.head)
    for k in commodities:
        if k.demand != 0.0 and (
            k.origin not in incident or k.destination not in incident
        ):
            built.infeasible = True
            return built
    if not enabled:
        return built

    arc_idx = pd.Index(built.arc_keys, name="arc")
    k_idx = pd.Index([k.index for k in commodities], name="k")
    arc_pos = {key: j for j, key in enumerate(built.arc_keys)}
    f = model.add_variables(lower=0.0, coords=[arc_idx, k_idx], name="f")
    built.f = f
    # 容量系上限のスラック（allow_capacity_slack 時のみ生成）。目的で大罰則を課す
    slacks: list[Any] = []

    # フロー保存: 接続行列 (node×arc) と純供給 (node×k) で一括制約
    nodes = arc_model.active_nodes
    node_pos = {v: i for i, v in enumerate(nodes)}
    node_idx = pd.Index([v.value for v in nodes], name="node")
    inc = np.zeros((len(nodes), len(enabled)))
    for j, arc in enumerate(enabled):
        inc[node_pos[arc.tail], j] += 1.0
        inc[node_pos[arc.head], j] -= 1.0
    rhs = np.zeros((len(nodes), len(commodities)))
    for kk, k in enumerate(commodities):
        rhs[node_pos[k.origin], kk] += k.demand
        rhs[node_pos[k.destination], kk] -= k.demand
    inc_da = xr.DataArray(inc, coords=[node_idx, arc_idx])
    rhs_da = xr.DataArray(rhs, coords=[node_idx, k_idx])
    model.add_constraints((inc_da * f).sum("arc") == rhs_da)

    # エッジ・ノード系制約はアーク総フロー（コモディティ合算）に対して張る
    edge_flow = f.sum("k")

    # 容量上限（危険フラグ由来のアーク容量）
    danger_keys: list[str] = []
    danger_caps: list[float] = []
    for edge in arc_model.active_edges:
        cap = inputs.edge_danger_capacity.get(edge.edge_id)
        if cap is None:
            continue
        for arc in arc_model.arcs_of_edge.get(edge.edge_id, ()):
            if arc.key in arc_pos:
                danger_keys.append(arc.key)
                danger_caps.append(cap)
    if danger_keys:
        danger_idx = pd.Index(danger_keys, name="arc")
        cap_da = xr.DataArray(np.asarray(danger_caps), coords=[danger_idx])
        lhs = edge_flow.sel(arc=danger_keys)
        if allow_capacity_slack:
            sl = model.add_variables(lower=0.0, coords=[danger_idx], name="sl_danger")
            slacks.append(sl)
            lhs = lhs - sl
        model.add_constraints(lhs <= cap_da)

    def edge_total(edge_ids: list[EdgeID], scale: dict[EdgeID, float] | None = None):
        # エッジ集合ごとの総フロー Σ_a f_a（scale 指定時は係数 scale_e を掛ける）
        eidx = pd.Index([e.value for e in edge_ids], name="edge")
        mem = np.zeros((len(edge_ids), len(enabled)))
        for i, eid in enumerate(edge_ids):
            coeff = scale.get(eid, 1.0) if scale is not None else 1.0
            for arc in arc_model.arcs_of_edge.get(eid, ()):
                j = arc_pos.get(arc.key)
                if j is not None:
                    mem[i, j] = coeff
        return (xr.DataArray(mem, coords=[eidx, arc_idx]) * edge_flow).sum("arc")

    # 容量ヒント上限・スカラー型パンク制約（エッジ総フロー）
    hint_edges = [
        edge.edge_id
        for edge in arc_model.active_edges
        if edge.edge_id in inputs.capacity_hint
        and any(
            a.key in arc_pos for a in arc_model.arcs_of_edge.get(edge.edge_id, ())
        )
    ]
    if hint_edges:
        hint_idx = pd.Index([e.value for e in hint_edges], name="edge")
        hint_da = xr.DataArray(
            np.asarray([inputs.capacity_hint[e] for e in hint_edges]), coords=[hint_idx]
        )
        lhs = edge_total(hint_edges)
        if allow_capacity_slack:
            sl = model.add_variables(lower=0.0, coords=[hint_idx], name="sl_hint")
            slacks.append(sl)
            lhs = lhs - sl
        model.add_constraints(lhs <= hint_da)
        scalar_capped = [e for e in hint_edges if e in inputs.scalar_edges]
        if scalar_capped:
            punct_idx = pd.Index([e.value for e in scalar_capped], name="edge")
            punct_da = xr.DataArray(
                np.asarray(
                    [
                        max(0.0, inputs.capacity_hint[e] - inputs.sigma.get(e, 0.0))
                        for e in scalar_capped
                    ]
                ),
                coords=[punct_idx],
            )
            lhs = edge_total(scalar_capped)
            if allow_capacity_slack:
                sl = model.add_variables(
                    lower=0.0, coords=[punct_idx], name="sl_punct"
                )
                slacks.append(sl)
                lhs = lhs - sl
            model.add_constraints(lhs <= punct_da)

    # ノード通過量上限（ノード危険フラグ）
    capped_nodes = [
        (v, cap)
        for v, cap in inputs.node_danger_capacity.items()
        if any(a.key in arc_pos for a in arc_model.arcs_in(v))
    ]
    if capped_nodes:
        nidx = pd.Index([v.value for v, _ in capped_nodes], name="capped_node")
        mem = np.zeros((len(capped_nodes), len(enabled)))
        for i, (v, _) in enumerate(capped_nodes):
            for arc in arc_model.arcs_in(v):
                j = arc_pos.get(arc.key)
                if j is not None:
                    mem[i, j] = 1.0
        cap_da = xr.DataArray(
            np.asarray([c for _, c in capped_nodes]), coords=[nidx]
        )
        lhs = (xr.DataArray(mem, coords=[nidx, arc_idx]) * edge_flow).sum("arc")
        if allow_capacity_slack:
            sl = model.add_variables(lower=0.0, coords=[nidx], name="sl_node")
            slacks.append(sl)
            lhs = lhs - sl
        model.add_constraints(lhs <= cap_da)

    # 排出上限（線形近似の妥当域ガード）: η_e*f_e <= s_obs
    drain_edges = [
        edge.edge_id
        for edge in arc_model.active_edges
        if edge.edge_id in inputs.s_obs
        and inputs.eta.get(edge.edge_id, 0.0) > 0.0
        and any(
            a.key in arc_pos for a in arc_model.arcs_of_edge.get(edge.edge_id, ())
        )
    ]
    if drain_edges:
        drain_idx = pd.Index([e.value for e in drain_edges], name="edge")
        s_obs_da = xr.DataArray(
            np.asarray([inputs.s_obs[e] for e in drain_edges]), coords=[drain_idx]
        )
        lhs = edge_total(drain_edges, scale=inputs.eta)
        if allow_capacity_slack:
            sl = model.add_variables(lower=0.0, coords=[drain_idx], name="sl_drain")
            slacks.append(sl)
            lhs = lhs - sl
        model.add_constraints(lhs <= s_obs_da)

    # τ 維持制約: c_e(s_obs_e − η_e f_e)/(s̄_e + ε0) <= tau_cap の線形同値変形。
    # 分散段でフローを散らしても停滞抑制が悪化しないための上限として使う
    if tau_cap is not None:
        bound_edges: list[EdgeID] = []
        bounds: list[float] = []
        for edge in arc_model.active_edges:
            eid = edge.edge_id
            eta_e = inputs.eta.get(eid, 0.0)
            c_e = inputs.c_e.get(eid, 1.0)
            if eid not in drainable or eid not in inputs.s_obs:
                continue
            if eta_e <= 0.0 or c_e <= 0.0:
                continue
            if not any(a.key in arc_pos for a in arc_model.arcs_of_edge.get(eid, ())):
                continue
            rhs = inputs.s_obs[eid] - tau_cap * (
                inputs.s_bar.get(eid, 0.0) + inputs.epsilon_0
            ) / c_e
            if rhs <= 0.0:
                continue  # 制約が自明に成立
            bound_edges.append(eid)
            bounds.append(rhs)
        if bound_edges:
            bidx = pd.Index([e.value for e in bound_edges], name="edge")
            mem = np.zeros((len(bound_edges), len(enabled)))
            for i, eid in enumerate(bound_edges):
                for arc in arc_model.arcs_of_edge.get(eid, ()):
                    j = arc_pos.get(arc.key)
                    if j is not None:
                        mem[i, j] = inputs.eta.get(eid, 0.0)
            model.add_constraints(
                (xr.DataArray(mem, coords=[bidx, arc_idx]) * edge_flow).sum("arc")
                >= xr.DataArray(np.asarray(bounds), coords=[bidx])
            )

    # 最短路シードの透過配分: ホップ数重みの総フロー最小化。
    # 混雑逓増が有効なら、アーク総フローを等幅セグメントへ分割し後段ほど単価を
    # 上げる（凸な区分線形コスト）。等コストの並列ルートがあるとき 1 本へ集中
    # させるより分けた方が総コストが下がるため、配分が並列路へ分散する。
    # 重みはすべて正のままなので構造的非循環は保たれる。
    objective = f.sum()
    if congestion_increment > 0.0 and _COST_SEGMENTS > 1:
        total_demand = sum(k.demand for k in commodities)
        if total_demand > 0.0:
            seg_width = total_demand / _COST_SEGMENTS
            seg_idx = pd.Index(range(_COST_SEGMENTS), name="seg")
            g = model.add_variables(
                lower=0.0, upper=seg_width, coords=[arc_idx, seg_idx], name="g"
            )
            # アーク総フロー（コモディティ合算）＝セグメント和
            model.add_constraints(g.sum("seg") - f.sum("k") == 0)
            # 段ごとの追加単価（第 1 段は基本コスト f.sum() が担うので増分のみ）
            extra = xr.DataArray(
                np.asarray(
                    [congestion_increment * i for i in range(_COST_SEGMENTS)]
                ),
                coords=[seg_idx],
            )
            objective = objective + (extra * g).sum()
    for sl in slacks:
        objective = objective + _SLACK_PENALTY * sl.sum()
    model.add_objective(objective, sense="min")

    return built


@dataclass
class _BuiltZone:
    """ゾーン限定 LP の構築結果（build_zone_lp / solve_zone_lp 専用）"""

    model: Any
    f: Any  # linopy Variable（arc）。有効ゾーンアークなしは None
    arc_keys: tuple[str, ...]
    infeasible: bool = False


def build_zone_lp(
    arc_model: ArcModel,
    inputs: MilpInputs,
    *,
    zone_edges: frozenset[EdgeID],
    zone_nodes: frozenset[NodeID],
    fixed_x: dict[str, int],
    net_supply: dict[NodeID, float],
) -> _BuiltZone:
    """ゾーン限定の配分 LP（単一品種・純供給ベース）を構築する

    方向候補の τ 比較用にゾーン誘導部分グラフだけを解く。ゾーン外の方向・フローは
    current・ベースライン値に固定し、その影響はゾーン横断アークの固定フローを畳み込んだ
    純供給 ``net_supply``（所与の流入出条件）として与えられる。設計が許すコモディティ
    縮約（単一品種）を用いるため変数はアーク次元のみ。制約族（危険容量・容量ヒント・
    パンク・排出上限）はゾーン内エッジに限定して全体 LP と同一に張る。
    """
    model = linopy.Model()
    enabled = tuple(
        a
        for a in arc_model.arcs
        if a.edge_id in zone_edges and fixed_x.get(a.key, 0) == 1
    )
    built = _BuiltZone(
        model=model, f=None, arc_keys=tuple(a.key for a in enabled)
    )
    demanded = {v for v, b in net_supply.items() if abs(b) > 1e-9}
    if not demanded:
        # 純供給ゼロ: ゼロフローが自明解（min-cost で正コストのため）。求解不要
        return built
    if not enabled:
        built.infeasible = True
        return built
    incident: set[NodeID] = set()
    for arc in enabled:
        incident.add(arc.tail)
        incident.add(arc.head)
    if demanded - incident:
        # 純供給が残るノードに有効アークが無い → 構造的に不可（求解不要）
        built.infeasible = True
        return built

    arc_idx = pd.Index(built.arc_keys, name="arc")
    arc_pos = {key: j for j, key in enumerate(built.arc_keys)}
    f = model.add_variables(lower=0.0, coords=[arc_idx], name="fz")
    built.f = f

    nodes = tuple(sorted(zone_nodes, key=lambda n: n.value))
    node_pos = {v: i for i, v in enumerate(nodes)}
    node_idx = pd.Index([v.value for v in nodes], name="node")
    inc = np.zeros((len(nodes), len(enabled)))
    for j, arc in enumerate(enabled):
        inc[node_pos[arc.tail], j] += 1.0
        inc[node_pos[arc.head], j] -= 1.0
    rhs = np.asarray([net_supply.get(v, 0.0) for v in nodes])
    inc_da = xr.DataArray(inc, coords=[node_idx, arc_idx])
    rhs_da = xr.DataArray(rhs, coords=[node_idx])
    model.add_constraints((inc_da * f).sum("arc") == rhs_da)

    zone_edge_list = sorted(zone_edges, key=lambda e: e.value)

    danger_keys: list[str] = []
    danger_caps: list[float] = []
    for eid in zone_edge_list:
        cap = inputs.edge_danger_capacity.get(eid)
        if cap is None:
            continue
        for arc in arc_model.arcs_of_edge.get(eid, ()):
            if arc.key in arc_pos:
                danger_keys.append(arc.key)
                danger_caps.append(cap)
    if danger_keys:
        cap_da = xr.DataArray(
            np.asarray(danger_caps), coords=[pd.Index(danger_keys, name="arc")]
        )
        model.add_constraints(f.sel(arc=danger_keys) <= cap_da)

    def edge_total(edge_ids: list[EdgeID], scale: dict[EdgeID, float] | None = None):
        eidx = pd.Index([e.value for e in edge_ids], name="edge")
        mem = np.zeros((len(edge_ids), len(enabled)))
        for i, eid in enumerate(edge_ids):
            coeff = scale.get(eid, 1.0) if scale is not None else 1.0
            for arc in arc_model.arcs_of_edge.get(eid, ()):
                j = arc_pos.get(arc.key)
                if j is not None:
                    mem[i, j] = coeff
        return (xr.DataArray(mem, coords=[eidx, arc_idx]) * f).sum("arc")

    hint_edges = [
        eid
        for eid in zone_edge_list
        if eid in inputs.capacity_hint
        and any(a.key in arc_pos for a in arc_model.arcs_of_edge.get(eid, ()))
    ]
    if hint_edges:
        hint_da = xr.DataArray(
            np.asarray([inputs.capacity_hint[e] for e in hint_edges]),
            coords=[pd.Index([e.value for e in hint_edges], name="edge")],
        )
        model.add_constraints(edge_total(hint_edges) <= hint_da)
        scalar_capped = [e for e in hint_edges if e in inputs.scalar_edges]
        if scalar_capped:
            punct_da = xr.DataArray(
                np.asarray(
                    [
                        max(0.0, inputs.capacity_hint[e] - inputs.sigma.get(e, 0.0))
                        for e in scalar_capped
                    ]
                ),
                coords=[pd.Index([e.value for e in scalar_capped], name="edge")],
            )
            model.add_constraints(edge_total(scalar_capped) <= punct_da)

    capped_nodes = [
        (v, cap)
        for v, cap in inputs.node_danger_capacity.items()
        if v in zone_nodes and any(a.key in arc_pos for a in arc_model.arcs_in(v))
    ]
    if capped_nodes:
        nidx = pd.Index([v.value for v, _ in capped_nodes], name="capped_node")
        mem = np.zeros((len(capped_nodes), len(enabled)))
        for i, (v, _) in enumerate(capped_nodes):
            for arc in arc_model.arcs_in(v):
                j = arc_pos.get(arc.key)
                if j is not None:
                    mem[i, j] = 1.0
        cap_da = xr.DataArray(
            np.asarray([c for _, c in capped_nodes]), coords=[nidx]
        )
        model.add_constraints(
            (xr.DataArray(mem, coords=[nidx, arc_idx]) * f).sum("arc") <= cap_da
        )

    drain_edges = [
        eid
        for eid in zone_edge_list
        if eid in inputs.s_obs
        and inputs.eta.get(eid, 0.0) > 0.0
        and any(a.key in arc_pos for a in arc_model.arcs_of_edge.get(eid, ()))
    ]
    if drain_edges:
        s_obs_da = xr.DataArray(
            np.asarray([inputs.s_obs[e] for e in drain_edges]),
            coords=[pd.Index([e.value for e in drain_edges], name="edge")],
        )
        model.add_constraints(edge_total(drain_edges, scale=inputs.eta) <= s_obs_da)

    model.add_objective(f.sum(), sense="min")
    return built


def solve_zone_lp(
    built: _BuiltZone, time_limit: float, seed: int
) -> tuple[SolverStatus, dict[str, float] | None]:
    """ゾーン限定 LP を求解し、ゾーンアークのフロー（arc.key → f_a）を返す"""
    if built.infeasible:
        return SolverStatus.INFEASIBLE, None
    if built.f is None:
        return SolverStatus.OPTIMAL, {}
    condition = _solve(built.model, time_limit, seed, io_api="direct")
    try:
        sol = built.f.solution
        values = {
            str(key): float(val)
            for key, val in zip(
                sol.coords["arc"].values.tolist(), sol.values.tolist()
            )
        }
    except Exception:
        values = None
    if values is not None and any(math.isnan(v) for v in values.values()):
        values = None
    status = _map_status(condition, values is not None)
    return status, values


def evaluate_residual_tau(
    arc_model: ArcModel,
    inputs: MilpInputs,
    drainable: frozenset[EdgeID],
    flow: dict[str, float],
) -> float:
    """配分解の近似残留 τ を事後評価する

    τ = max_e c_e(s_obs_e − η_e f_e)/(s̄_e + ε0)（排出可能かつ停滞観測のあるエッジ）。
    排出上限 η_e f_e ≤ s_obs_e を満たす解では各項は負にならない。対象がなければ 0。
    """
    tau = 0.0
    for edge in arc_model.active_edges:
        eid = edge.edge_id
        if eid not in drainable or eid not in inputs.s_obs:
            continue
        f_e = sum(
            flow.get(arc.key, 0.0) for arc in arc_model.arcs_of_edge.get(eid, ())
        )
        residual = inputs.s_obs[eid] - inputs.eta.get(eid, 0.0) * f_e
        value = inputs.c_e.get(eid, 1.0) * residual / (
            inputs.s_bar.get(eid, 0.0) + inputs.epsilon_0
        )
        tau = max(tau, value)
    return tau


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


def _solve(
    model: Any,
    time_limit: float,
    seed: int,
    mip_rel_gap: float = 0.0,
    io_api: str | None = None,
) -> str:
    options: dict[str, Any] = dict(
        solver_name="highs",
        time_limit=float(time_limit),
        threads=1,
        random_seed=int(seed),
        output_flag=False,
    )
    if io_api is not None:
        options["io_api"] = io_api
    if mip_rel_gap > 0.0:
        options["mip_rel_gap"] = float(mip_rel_gap)
    model.solve(**options)
    return str(model.termination_condition)


def solve_assignment(
    built: _BuiltAssignment, time_limit: float, seed: int
) -> PhaseResult:
    """配分 LP を求解する（build_assignment_lp 専用）

    τ は解に含めない（呼出し側が evaluate_residual_tau で事後評価する。
    ArcSolution.tau は 0.0 のプレースホルダ）。LP ファイルを経由しない
    direct API（highspy へ直接受け渡し）で求解する。
    """
    if built.infeasible:
        return PhaseResult(SolverStatus.INFEASIBLE, None, 0.0)
    if built.f is None:
        # コモディティなし: ゼロフローが自明解
        return PhaseResult(SolverStatus.OPTIMAL, _zero_flow_solution(built), 0.0)
    condition = _solve(built.model, time_limit, seed, io_api="direct")
    solution = _extract_assignment(built)
    status = _map_status(condition, solution is not None)
    if solution is None:
        return PhaseResult(status, None, 0.0)
    return PhaseResult(status, solution, 0.0)


def _fixed_direction_map(built: _BuiltAssignment) -> dict[str, int]:
    return {arc.key: built.fixed_x.get(arc.key, 0) for arc in built.arc_model.arcs}


def _zero_flow_solution(built: _BuiltAssignment) -> ArcSolution:
    flow = {arc.key: 0.0 for arc in built.arc_model.arcs}
    return ArcSolution(flow=flow, direction=_fixed_direction_map(built), tau=0.0)


def _extract_assignment(built: _BuiltAssignment) -> ArcSolution | None:
    try:
        totals = built.f.solution.sum("k")
        values = {
            str(key): float(val)
            for key, val in zip(
                totals.coords["arc"].values.tolist(), totals.values.tolist()
            )
        }
    except Exception:
        return None
    if any(math.isnan(v) for v in values.values()):
        return None
    flow = {arc.key: values.get(arc.key, 0.0) for arc in built.arc_model.arcs}
    return ArcSolution(flow=flow, direction=_fixed_direction_map(built), tau=0.0)


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
