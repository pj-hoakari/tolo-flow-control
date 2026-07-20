"""可変通路の向き解除（RELEASE_ONEWAY）を通常運営で確認するシナリオ

午前の入場ピークに合わせて入場向き（lobby→hall）に運用していた可変通路 `e_flex` が、
午後の退場需要の増加で逆向きの圧力を受ける。退場は常設の細い通路 `e_service`
（容量ヒント小）しか使えず、可変通路の入口付近にはライン計測のない滞留が
発生する（lineless の縮退発火）。

現実に即したモデル化: 場内ホール `hall` は観客が滞留し午後に放出源となる内部の
混在ノード（ΔOcc<0）、退場先 `lobby` は場外への入退出点（境界 GOAL）とする。

期待する提案は `e_flex` の一方通行運用の解除（RELEASE_ONEWAY → BIDIRECTIONAL）で、
退場流を可変通路にも流して停滞を解消する。緊急・避難の文脈ではなく、
時間帯による需要反転への通常運営の追従を表す。

既知の制約: 現行 Forecasting は Open モードで混在ノード起点の OD を導出しない
（生成源は境界または純 GOAL のみ）ため、退場需要が OD に乗らず提案が空になる。
エンジン制約ドキュメント（docs/engine_constraints_20260720.md）の E1 を参照。
"""

from __future__ import annotations

from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    EdgeID,
    NodeID,
    NodeKind,
)

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


def _build_graph() -> GraphBuilder:
    b = GraphBuilder()
    # 場内ホール: 観客が滞留し、退場時間帯に放出源となる混在ノード
    b.node("hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(0.0, 0.0))
    # 退場先ロビー: 場外への入退出点
    b.node("lobby", kind=NodeKind.GOAL, boundary=True, pos=(3.0, 0.0))
    # 可変通路: 午前の運用のまま入場向き（lobby→hall）
    b.edge(
        "e_flex",
        "lobby",
        "hall",
        capacity_hint=30.0,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.A_TO_B,
    )
    # 常設の退出通路: hall→lobby の一方通行・容量小
    b.edge(
        "e_service",
        "hall",
        "lobby",
        capacity_hint=10.0,
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    return b


@register("reversible-corridor-flip")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_flex")})
    # 退場 25 が細い e_service に集中して急増。可変通路の入口滞留はライン計測がなく、
    # 停滞のみの縮退発火となる
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("hall"), NodeID("lobby"), 25.0, surge=True),),
        stagnation_edges=hot,
        lineless_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "reversible-corridor-flip",
        "退場需要の増加で入場向きの可変通路を双方向へ解除し、細い常設退出路の停滞を解消する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
