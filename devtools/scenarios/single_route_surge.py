"""単一ルート急増シナリオ"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import Scenario, build_observations_and_history, make_scenario
from ._registry import register


@register("single-route-surge")
def build() -> Scenario:
    built = graph_builder.venue()
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=frozenset({EdgeID("e_in_j1")}),
        # 混在ホールに滞留を与え、OD・信頼度が意味を持つようにする
        occupancy=30.0,
        occupancy_delta=10.0,
        # 単一アクセス通路がホール需要を運べるよう排出上限 eta*f<=s_obs を緩める
        eta=0.02,
    )
    return make_scenario(
        "single-route-surge",
        "入口ルート e_in_j1 が急増。単一エッジのトリガーを確認する",
        built,
        obs,
        hist,
    )
