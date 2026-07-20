"""crossing: 主通路の混雑 → 並行バイパス 2 本への迂回（迂回提案が映える）シナリオ

主通路 `e_main`（容量ヒント小）に hub_e 行き需要の急増が乗り組合せ発火する。
DetourRouting が両端 hub_w–hub_e 間の 2 本のバイパス（北 `e_n1a/e_n1b`・
南 `e_s1a/e_s1b`）を迂回路として列挙し、期待する提案は「主通路の重要度を下げ、
両バイパスへ流量を移す」配分となる。
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


@register("crossing-detour")
def build() -> Scenario:
    built = graph_builder.crossing()
    hot = frozenset({EdgeID("e_main")})
    # hub_e 行き 30 の急増は最短路（e_in → e_main）に乗り、主通路の容量 10 を超える
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("in"), NodeID("hub_e"), 30.0, surge=True),),
        stagnation_edges=hot,
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
