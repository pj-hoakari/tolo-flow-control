"""Closed モード（入退出点なし）シナリオ

入退出点を持たない環状の ``closed-ring`` プリセットを使う。対向する 2 つの広場
（混在ノード）を持ち、放出側（ΔOcc<0）が生成源、蓄積側（ΔOcc>0）が吸収となる
（Closed の需要導出を通す）。
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


@register("closed-mode")
def build() -> Scenario:
    built = graph_builder.closed_ring()
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
