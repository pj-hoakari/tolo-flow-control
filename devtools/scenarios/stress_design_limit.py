"""設計想定上限規模（ノード約 10・エッジ約 50）の性能ストレスシナリオ

要件が定める規模上限いっぱいの密グラフ（10 ノード完全グラフ 45 本＋並行 5 本）で、
複数エッジ同時の組合せ発火から下流を通し、軽量モードの求解・モデル構築時間の
ヘッドルームを実測する。迂回・提案の妥当性検証ではなく計測が目的。
"""

from __future__ import annotations

import math
from itertools import combinations

from flow_control.domain import EdgeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    Scenario,
    build_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register

_NODE_SPECS: tuple[tuple[str, NodeKind, bool], ...] = (
    ("gate", NodeKind.GOAL, True),
    ("j_ne", NodeKind.TRANSIT_ONLY, False),
    ("hallA", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_e", NodeKind.TRANSIT_ONLY, False),
    ("hallB", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("exit", NodeKind.GOAL, True),
    ("hallC", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_s", NodeKind.TRANSIT_ONLY, False),
    ("hallD", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_w", NodeKind.TRANSIT_ONLY, False),
)

# 組合せ発火させるゲート周辺の 3 エッジ（貪欲探索の候補数も規模なりに増やす）
_HOT_EDGES = ("e_gate_j_ne", "e_gate_hallA", "e_gate_j_w")


def _build_graph() -> GraphBuilder:
    builder = GraphBuilder()
    n = len(_NODE_SPECS)
    for i, (name, kind, boundary) in enumerate(_NODE_SPECS):
        angle = 2.0 * math.pi * i / n
        builder.node(
            name,
            kind=kind,
            boundary=boundary,
            pos=(3.0 * math.cos(angle), 3.0 * math.sin(angle)),
        )
    # 完全グラフ 45 本
    names = [name for (name, _, _) in _NODE_SPECS]
    for a, b in combinations(names, 2):
        builder.edge(f"e_{a}_{b}", a, b)
    # 隣接ホール-ジャンクション間の並行通路 5 本で計 50 本に揃える
    for a, b in (
        ("j_ne", "hallA"),
        ("hallA", "j_e"),
        ("j_e", "hallB"),
        ("hallC", "j_s"),
        ("j_s", "hallD"),
    ):
        builder.edge(f"e_{a}_{b}_2", a, b)
    return builder


@register("stress-design-limit")
def build() -> Scenario:
    built = _build_graph().build()
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
