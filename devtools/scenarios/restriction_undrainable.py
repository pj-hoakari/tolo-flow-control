"""機能2（通行制限提案）: 迂回不足の行き止まりコリドーへの流入制限シナリオ

袋小路のホールへ向かう単一アクセス路が高停滞になり、迂回路も存在しない
（k_effective=0）ため、方向変更では解消できない。残留評価が閾値超となり
Detour ゲートも「構造的不足」で開くため、上流フィーダへ通行制限を提案する。

機能2 は既定で無効。本シナリオは `restriction_proposal_enabled=True` と
`tau_danger_threshold` を設定して有効化する。
"""

from __future__ import annotations

from dataclasses import replace

from flow_control.domain import EdgeID, NodeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    compact_configs,
    established_watch_state,
    make_scenario,
)
from ._registry import register


def _build_graph() -> GraphBuilder:
    b = GraphBuilder()
    b.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("lobby", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    # 袋小路のホール（迂回路が存在しないアクセス）
    b.node("deadend_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.8))
    b.node("side_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -0.8))
    b.edge("e_gate_lobby", "gate", "lobby", capacity_hint=120.0)
    b.edge("e_lobby_dead", "lobby", "deadend_hall")
    b.edge("e_lobby_side", "lobby", "side_hall")
    return b


@register("restriction-undrainable")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_lobby_dead")})
    base = compact_configs()
    configs = replace(
        base,
        optimization=replace(
            base.optimization,
            restriction_proposal_enabled=True,
            tau_danger_threshold=1.0,
        ),
    )
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("gate"), NodeID("deadend_hall"), 30.0, surge=True),
            ODSpec(NodeID("gate"), NodeID("side_hall"), 10.0),
        ),
        stagnation_edges=hot,
        # 排出感度を小さくし、配分後も停滞が残る（残留 τ が閾値を超える）状態にする
        eta=0.01,
    )
    return make_scenario(
        "restriction-undrainable",
        "袋小路コリドーが高停滞で迂回路なし。上流フィーダへ通行制限を提案する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
        configs=configs,
    )
