"""Closed モード（入退出点なし）シナリオ"""

from __future__ import annotations

import math

from flow_control.domain import EdgeID, NodeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


@register("closed-mode")
def build() -> Scenario:
    # 入退出点を持たない環状グラフ（Closed モード）。
    # 対向する 2 つの広場（混在ノード）を持ち、放出側（ΔOcc<0）が生成源、
    # 蓄積側（ΔOcc>0）が吸収となる（Closed の需要導出を通す）
    b = GraphBuilder()
    n = 6
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        b.node(
            f"n{i}",
            kind=NodeKind.GOAL_TRANSIT_MIXED if i in (0, 3) else NodeKind.TRANSIT_ONLY,
            boundary=False,
            pos=(math.cos(angle), math.sin(angle)),
        )
    for i in range(n):
        b.edge(f"e{i}", f"n{i}", f"n{(i + 1) % n}")
    built = b.build()
    hot = frozenset({EdgeID("e0")})
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("n0"), NodeID("n3"), 20.0, surge=True),),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "closed-mode",
        "入退出点なしの環状グラフ（Closed モード）。広場間の移動が急増し e0 が組合せ発火",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
