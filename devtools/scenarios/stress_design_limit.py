"""設計想定上限規模（ノード約 10・エッジ約 50）の性能ストレスシナリオ

グラフは ``design-limit`` プリセット（要件が定める規模上限いっぱいの密グラフ:
10 ノード完全グラフ 45 本＋並行 5 本）。ゲート直結の 3 スポークが同時に組合せ発火し、
2 境界・4 ホール行きの 6 コモディティを流した状態で、軽量モードの求解・モデル構築
時間のヘッドルームを実測する。迂回・提案の妥当性検証ではなく計測が目的。
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register

# 組合せ発火させるゲート直結の 3 スポーク（surge OD の最短路が各エッジに乗る）
_HOT_EDGES = ("e_gate_hallA", "e_gate_hallB", "e_gate_hallC")


@register("stress-design-limit")
def build() -> Scenario:
    built = graph_builder.design_limit()
    hot = frozenset(EdgeID(e) for e in _HOT_EDGES)
    gate, exit_ = NodeID("gate"), NodeID("exit")
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(gate, NodeID("hallA"), 30.0, surge=True),
            ODSpec(gate, NodeID("hallB"), 28.0, surge=True),
            ODSpec(gate, NodeID("hallC"), 26.0, surge=True),
            ODSpec(gate, NodeID("hallD"), 18.0),
            ODSpec(exit_, NodeID("hallC"), 12.0),
            ODSpec(exit_, NodeID("hallD"), 12.0),
        ),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "stress-design-limit",
        "上限規模グラフ(10 ノード/50 エッジ)でゲート直結 3 エッジが組合せ発火。性能計測用",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
