"""機能2（通行制限提案）の残留評価と Detour 不足ゲート

方向採用後に残る危険を評価し（residual）、迂回で吸収しきれないか（detour_insufficient）を
判定する純関数群。ここでは「制限を提案すべきゾーンか」までを決め、候補エッジの選定・
limit_value 算定・CLOSE/LIMIT の格下げは後段の責務とする。

閾値 θ_danger は `config.tau_danger_threshold`（None なら機能2 無効）。
判定は正規化停滞（τ と同じ量）で一本化する。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.graph import EdgeID
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
