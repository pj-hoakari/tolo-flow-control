"""複数ルート急増シナリオ"""

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


@register("multi-route-surge")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1"), EdgeID("e_j1_hallA"), EdgeID("e_hallA_j2")})
    # 保存則整合の観測: hallA 行きと出口行き（hallA 通過）の急増でホットエッジ 3 本を
    # 覆い、hallB 行きを平常成分として残す
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("hallA"), 25.0, surge=True),
            ODSpec(NodeID("in"), NodeID("out"), 15.0, surge=True),
            ODSpec(NodeID("in"), NodeID("hallB"), 10.0),
        ),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "multi-route-surge",
        "入口〜hallA 経路の複数エッジが同時急増＋停滞。複数トリガーと迂回路を確認する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
