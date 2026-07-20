"""crossing: 主通路の混雑 → 並行バイパス 2 本への迂回（迂回提案が映える）シナリオ

主通路 `e_main`（容量ヒント小）が急増。DetourRouting が両端 hub_w–hub_e 間の 2 本のバイパス
（北 `e_n1a/e_n1b`・南 `e_s1a/e_s1b`）を迂回路として列挙し、Optimization はスループット最大化対象
（トリガー＋迂回路集合）にこれらを含めるため、route_importance がバイパスへ移る。
「主通路が詰まったらこの 2 ルートへ流す」という最も分かりやすい迂回効果。
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


@register("crossing-detour")
def build() -> Scenario:
    built = graph_builder.crossing()
    hot = frozenset({EdgeID("e_main")})
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=hot,
        stagnation_edges=hot,
        occupancy=30.0,
        occupancy_delta=12.0,
        eta=0.02,
    )
    return make_scenario(
        "crossing-detour",
        "主通路 e_main が急増＋停滞・低容量。両端間の北/南バイパス 2 本へ迂回（route_importance がバイパスへ）",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
