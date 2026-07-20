"""機能2（通行制限提案）の判定部品

方向採用後に残る危険を評価し（residual）、迂回で吸収しきれないか（detour_insufficient）を
判定したうえで、制限候補の選定・制限値の算定・CLOSE 可否の安全検査までを担う純関数群。
提案オブジェクトの組み立てと optimizer への統合は後段の責務とする。

閾値 θ_danger は `config.tau_danger_threshold`（None なら機能2 無効）。
判定は正規化停滞（τ と同じ量）で一本化する。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.graph import EdgeID, NodeID
from .arcs import ArcModel
from .drainable import reachable_forward
from .model import MilpInputs

# 迂回路が構造的に不足とみなす k_effective の上限（k<=1 = 実質迂回路なし）
_MIN_SUFFICIENT_K = 2
# 迂回路が「使われている」とみなす利用率（正のフローを持つ迂回エッジの割合）
_MIN_USED_RATIO = 0.5
# フローを「正」とみなす下限
_EPSILON_FLOW = 1e-9


@dataclass(frozen=True)
class ResidualAssessment:
    """ゾーンの残留危険評価"""

    residual: bool
    tau_exceeded: bool  # τ_z(best) > θ_danger
    puncture_residual: bool  # スカラー型パンク制約が残留超過
    undrainable_present: bool  # 排出不能な停滞エッジがゾーンに存在
    tau_value: float
    undrainable_edges: tuple[EdgeID, ...] = ()
    puncture_edges: tuple[EdgeID, ...] = ()


@dataclass(frozen=True)
class DetourGate:
    """迂回吸収力の判定（真＝迂回では足りない）"""

    insufficient: bool
    structural_shortage: bool  # (i) k_effective 小
    unused: bool  # (ii) 迂回路が実際には使われていない
    detour_endangered: bool  # (iii) 迂回先も危険／トリガー・警戒中
    k_effective: int
    used_ratio: float
    endangered_edges: tuple[EdgeID, ...] = ()


def assess_residual(
    inputs: MilpInputs,
    *,
    zone_edges: frozenset[EdgeID],
    tau_zone: float,
    flow: Mapping[str, float],
    arc_keys_of_edge: Mapping[EdgeID, tuple[str, ...]],
    undrainable: frozenset[EdgeID],
    tau_danger_threshold: float,
) -> ResidualAssessment:
    """ゾーンの残留危険を評価する

    residual = (τ_z > θ_danger) ∨ puncture_residual ∨ undrainable_present。
    puncture_residual はスカラー型エッジで配分後もパンク上限
    ``max(0, C_e - σ_e)`` を超えている（＝制約が実質守れていない）状態を指す。
    """
    tau_exceeded = tau_zone > tau_danger_threshold

    undrainable_in_zone = tuple(
        sorted(zone_edges & undrainable, key=lambda e: e.value)
    )

    puncture_edges: list[EdgeID] = []
    for edge_id in sorted(zone_edges, key=lambda e: e.value):
        if edge_id not in inputs.scalar_edges:
            continue
        hint = inputs.capacity_hint.get(edge_id)
        if hint is None:
            continue
        limit = max(0.0, hint - inputs.sigma.get(edge_id, 0.0))
        total = sum(
            flow.get(key, 0.0) for key in arc_keys_of_edge.get(edge_id, ())
        )
        if total > limit + _EPSILON_FLOW:
            puncture_edges.append(edge_id)

    residual = (
        tau_exceeded or bool(puncture_edges) or bool(undrainable_in_zone)
    )
    return ResidualAssessment(
        residual=residual,
        tau_exceeded=tau_exceeded,
        puncture_residual=bool(puncture_edges),
        undrainable_present=bool(undrainable_in_zone),
        tau_value=tau_zone,
        undrainable_edges=undrainable_in_zone,
        puncture_edges=tuple(puncture_edges),
    )


def evaluate_detour_gate(
    inputs: MilpInputs,
    *,
    detour_edges: frozenset[EdgeID],
    k_effective: int,
    flow: Mapping[str, float],
    arc_keys_of_edge: Mapping[EdgeID, tuple[str, ...]],
    triggered_edges: frozenset[EdgeID],
    watched_edges: frozenset[EdgeID],
    tau_danger_threshold: float,
) -> DetourGate:
    """迂回で吸収しきれないかを判定する

    - (i) 構造的不足: k_effective が実質的な迂回路数に足りない
    - (ii) 不使用: 迂回エッジのうち正のフローを持つ割合が低い
    - (iii) 迂回先も危険: 迂回エッジの正規化停滞が θ_danger 超、または
      迂回エッジがトリガー集合・警戒集合と交差する
      （停滞観測のない迂回エッジは正規化停滞項をスキップし、幻の停滞を作らない）

    ``detour_edges`` は起点トリガーエッジ自身を除いた迂回路構成エッジ集合。
    """
    structural_shortage = k_effective < _MIN_SUFFICIENT_K

    if detour_edges:
        used = 0
        for edge_id in detour_edges:
            total = sum(
                flow.get(key, 0.0) for key in arc_keys_of_edge.get(edge_id, ())
            )
            if total > _EPSILON_FLOW:
                used += 1
        used_ratio = used / len(detour_edges)
    else:
        used_ratio = 0.0
    unused = used_ratio < _MIN_USED_RATIO

    endangered: list[EdgeID] = []
    for edge_id in sorted(detour_edges, key=lambda e: e.value):
        if edge_id in triggered_edges or edge_id in watched_edges:
            endangered.append(edge_id)
            continue
        s_obs = inputs.s_obs.get(edge_id)
        if s_obs is None:
            # 停滞観測なし: 正規化停滞は評価しない
            continue
        total = sum(
            flow.get(key, 0.0) for key in arc_keys_of_edge.get(edge_id, ())
        )
        residual_stag = s_obs - inputs.eta.get(edge_id, 0.0) * total
        normalized = inputs.c_e.get(edge_id, 1.0) * residual_stag / (
            inputs.s_bar.get(edge_id, 0.0) + inputs.epsilon_0
        )
        if normalized > tau_danger_threshold:
            endangered.append(edge_id)

    detour_endangered = bool(endangered)
    return DetourGate(
        insufficient=structural_shortage or unused or detour_endangered,
        structural_shortage=structural_shortage,
        unused=unused,
        detour_endangered=detour_endangered,
        k_effective=k_effective,
        used_ratio=used_ratio,
        endangered_edges=tuple(endangered),
    )


@dataclass(frozen=True)
class LimitValue:
    """制限値と、その導出根拠に基づく信頼度"""

    value: float | None
    confidence: float
    # True: 排出上限からの逆算（ラインなし・低信頼）
    derived_from_drain_bound: bool


def compute_limit_value(
    inputs: MilpInputs,
    edge_id: EdgeID,
    *,
    outflow_average: float | None,
    low_confidence: float = 0.5,
) -> LimitValue:
    """制限値 limit_value を設計の優先順で決める

    1. μ̂_e（当該エッジが直近に現に捌けた流出率。ラインあり）— η の推定誤差に依存しない
    2. s̃_e / η_e（排出上限からの逆算。ラインなし）— 停滞プロキシの計数ゲインに
       比例して歪むため低信頼（confidence を減衰）

    どちらも得られなければ value=None（制限値なしの提案＝運用判断に委ねる）。
    """
    if outflow_average is not None and outflow_average >= 0.0:
        return LimitValue(
            value=outflow_average, confidence=1.0, derived_from_drain_bound=False
        )
    s_obs = inputs.s_obs.get(edge_id)
    eta = inputs.eta.get(edge_id, 0.0)
    if s_obs is not None and eta > _EPSILON_FLOW:
        return LimitValue(
            value=s_obs / eta,
            confidence=low_confidence,
            derived_from_drain_bound=True,
        )
    return LimitValue(value=None, confidence=low_confidence, derived_from_drain_bound=False)


def select_feeder_candidates(
    arc_model: ArcModel,
    *,
    danger_edges: frozenset[EdgeID],
    flow: Mapping[str, float],
    importance: Mapping[EdgeID, float],
    zone_edges: frozenset[EdgeID],
) -> tuple[EdgeID, ...]:
    """上流フィーダ（流入寄与が大きく重要度が低いエッジ）を候補化する

    危険エッジの流入側ノードへ入るアークを持つゾーン内エッジのうち、危険エッジ
    自身を除いたものを対象とし、「流入寄与 f_e 降順・重要度 昇順・ID 昇順」で
    決定的に並べる。制限は流入を絞る操作なので、下流ではなく上流を候補にする。
    """
    upstream_nodes: set[NodeID] = set()
    for edge_id in danger_edges:
        for arc in arc_model.arcs_of_edge.get(edge_id, ()):
            if flow.get(arc.key, 0.0) > _EPSILON_FLOW:
                upstream_nodes.add(arc.tail)
    if not upstream_nodes:
        # フローが無い場合は端点両方を上流とみなす（誰も運べていない＝流入自体を絞る）
        for edge_id in danger_edges:
            for arc in arc_model.arcs_of_edge.get(edge_id, ()):
                upstream_nodes.add(arc.tail)

    scored: list[tuple[float, float, str, EdgeID]] = []
    for edge_id in zone_edges - danger_edges:
        contribution = 0.0
        for arc in arc_model.arcs_of_edge.get(edge_id, ()):
            if arc.head in upstream_nodes:
                contribution += flow.get(arc.key, 0.0)
        if contribution <= _EPSILON_FLOW:
            continue
        scored.append(
            (-contribution, importance.get(edge_id, 0.0), edge_id.value, edge_id)
        )
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return tuple(item[3] for item in scored)


def close_preserves_connectivity(
    arc_model: ArcModel,
    *,
    closed_edge: EdgeID,
    direction: Mapping[str, int],
    is_open: bool,
) -> bool:
    """当該エッジを閉鎖しても連結性を保てるか（CLOSE 可否の安全検査）

    Open: 全有効ノードが代表入退出点と双方向に到達可能であること（境界連結性）。
    Closed: 弱連結成分を割らず、各ノードが出入り両方向のアークを持つこと
    （ローカル可達性）。いずれか破れる候補は CLOSE 不可＝LIMIT へ格下げする。
    """
    forward: dict[NodeID, list[NodeID]] = {}
    backward: dict[NodeID, list[NodeID]] = {}
    undirected: dict[NodeID, list[NodeID]] = {}
    out_degree: dict[NodeID, int] = {}
    in_degree: dict[NodeID, int] = {}
    for arc in arc_model.arcs:
        if arc.edge_id == closed_edge:
            continue
        if direction.get(arc.key, 0) != 1:
            continue
        forward.setdefault(arc.tail, []).append(arc.head)
        backward.setdefault(arc.head, []).append(arc.tail)
        undirected.setdefault(arc.tail, []).append(arc.head)
        undirected.setdefault(arc.head, []).append(arc.tail)
        out_degree[arc.tail] = out_degree.get(arc.tail, 0) + 1
        in_degree[arc.head] = in_degree.get(arc.head, 0) + 1

    active = set(arc_model.active_nodes)
    # ローカル可達性: 出入り両方向を持つ（孤立させない）
    for node in active:
        if out_degree.get(node, 0) == 0 or in_degree.get(node, 0) == 0:
            return False

    if is_open:
        if not arc_model.entry_nodes:
            return True
        root = arc_model.entry_nodes[0]
        return active <= reachable_forward(forward, root) and active <= (
            reachable_forward(backward, root)
        )
    # Closed: 弱連結成分を割らない
    if not active:
        return True
    root = next(iter(sorted(active, key=lambda n: n.value)))
    return active <= reachable_forward(undirected, root)
