"""Open モード（入退出点あり）シナリオ"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import Scenario, build_observations_and_history, make_scenario
from ._registry import register


@register("open-mode")
def build() -> Scenario:
    built = graph_builder.linear(5)
    # 単一経路では全需要が各エッジを通るため、排出上限 eta*f<=s_obs を緩めて
    # （eta を小さく）feasible にし、Open モードの正常系（OPTIMAL）を示す
    obs, hist = build_observations_and_history(
        built.graph, surge_edges=frozenset({EdgeID("e2")}), eta=0.02
    )
    return make_scenario(
        "open-mode",
        "入退出点ありの直線グラフ（Open モード）。中央 e2 が急増",
        built,
        obs,
        hist,
    )
