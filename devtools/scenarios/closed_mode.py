"""Closed モード（入退出点なし）シナリオ"""

from __future__ import annotations

import math

from flow_control.domain import EdgeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    Scenario,
    build_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


@register("closed-mode")
def build() -> Scenario:
    # 入退出点を持たない環状グラフ（Closed モード）
    b = GraphBuilder()
    n = 6
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        b.node(
            f"n{i}",
            kind=NodeKind.TRANSIT_ONLY,
            boundary=False,
            pos=(math.cos(angle), math.sin(angle)),
        )
    for i in range(n):
        b.edge(f"e{i}", f"n{i}", f"n{(i + 1) % n}")
    built = b.build()
    hot = frozenset({EdgeID("e0")})
    obs, hist = build_observations_and_history(
        built.graph, surge_edges=hot, stagnation_edges=hot
    )
    return make_scenario(
        "closed-mode",
        "入退出点なしの環状グラフ（Closed モード）。e0 が急増＋停滞し組合せ発火",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
