"""複数ルート急増シナリオ"""

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


@register("multi-route-surge")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1"), EdgeID("e_j1_hallA"), EdgeID("e_hallA_j2")})
    # 組合せ発火: 急増（需要警戒）に加え停滞警戒＋計時済み watch を同一エッジ群へ与える
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=hot,
        stagnation_edges=hot,
        occupancy=30.0,
        occupancy_delta=10.0,
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
