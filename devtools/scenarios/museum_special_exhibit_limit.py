"""美術館の特別展入場待ちに対する流入制限（機能2）の現実ケース

特別展示室は袋小路のスパー（迂回路なし）にあり、開場直後の人気で入場待ち列が
アクセス通路 `e_foyer_special` に伸びて高停滞になる。方向変更や迂回では解消できず
（k_effective=0）、残留停滞の評価が閾値を超えるため、期待する提案は上流フィーダ
`e_entrance_foyer` への流入制限（LIMIT・整理入場のレート値付き）となる。
常設展側 `e_foyer_main` の平常流は妨げない。

機能2（通行制限提案）は既定で無効のため、`restriction_proposal_enabled=True` と
`tau_danger_threshold` を設定して有効化する。restriction-undrainable が最小構成の
機能検証であるのに対し、本シナリオは実際の館内運営（整理入場）の文脈で確認する。
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
    b.node("entrance", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("foyer", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    # 特別展示室: 袋小路（迂回路が存在しないアクセス）
    b.node("special_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 1.0))
    b.node("main_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -1.0))
    b.node("cafe", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(4.5, -1.0))
    b.edge("e_entrance_foyer", "entrance", "foyer", capacity_hint=120.0)
    b.edge("e_foyer_special", "foyer", "special_hall")
    b.edge("e_foyer_main", "foyer", "main_hall")
    b.edge("e_main_cafe", "main_hall", "cafe")
    return b


@register("museum-special-exhibit-limit")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_foyer_special")})
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
            ODSpec(NodeID("entrance"), NodeID("special_hall"), 30.0, surge=True),
            ODSpec(NodeID("entrance"), NodeID("main_hall"), 8.0),
            ODSpec(NodeID("entrance"), NodeID("cafe"), 4.0),
        ),
        stagnation_edges=hot,
        # 排出感度を小さくし、配分後も停滞が残る（残留 τ が閾値を超える）状態にする
        eta=0.01,
    )
    return make_scenario(
        "museum-special-exhibit-limit",
        "特別展の入場待ちで袋小路アクセスが高停滞。上流フィーダへ整理入場の流入制限を提案する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
        configs=configs,
    )
