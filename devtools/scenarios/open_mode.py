"""Open モード（入退出点あり）シナリオ

設計の Open モード OD 種別は ext→int / int→ext / int→int で、境界→境界の
通過需要（ext→ext）は扱わない。素の直線グラフ（内部目的地なし）では OD が
構造的に 0 になるため、中央に混在広場を置いた ``plaza-line`` プリセットを使う。
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


@register("open-mode")
def build() -> Scenario:
    built = graph_builder.plaza_line()
    hot = frozenset({EdgeID("e1")})
    # 入口 n0 から中央広場への需要が急増（ext→int）。反対側入口からの平常流も置く
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("n0"), NodeID("plaza"), 25.0, surge=True),
            ODSpec(NodeID("n4"), NodeID("plaza"), 8.0),
        ),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "open-mode",
        "入退出点ありの直線グラフ（Open モード）。広場手前 e1 が急増＋停滞し組合せ発火",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
