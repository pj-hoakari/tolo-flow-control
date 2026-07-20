"""設計想定上限規模（ノード約 10・エッジ約 50）の性能ストレスシナリオ

グラフは ``design-limit`` プリセット（要件が定める規模上限いっぱいの密グラフ:
10 ノード完全グラフ 45 本＋並行 5 本）。複数エッジ同時の組合せ発火から下流を通し、
軽量モードの求解・モデル構築時間のヘッドルームを実測する。
迂回・提案の妥当性検証ではなく計測が目的。
"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import (
    Scenario,
    build_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register

# 組合せ発火させるゲート周辺の 3 エッジ（貪欲探索の候補数も規模なりに増やす）
_HOT_EDGES = ("e_gate_j_ne", "e_gate_hallA", "e_gate_j_w")


@register("stress-design-limit")
def build() -> Scenario:
    built = graph_builder.design_limit()
    hot = frozenset(EdgeID(e) for e in _HOT_EDGES)
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=hot,
        stagnation_edges=hot,
        occupancy=30.0,
        occupancy_delta=10.0,
        eta=0.02,
    )
    return make_scenario(
        "stress-design-limit",
        "上限規模グラフ(10 ノード/50 エッジ)でゲート周辺 3 エッジが組合せ発火。性能計測用",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
