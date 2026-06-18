"""expo: 単一ホール急増シナリオ"""

from __future__ import annotations

from flow_control.domain import EdgeID

from ..scenario_base import Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-single-hall-surge")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-single-hall-surge",
        "単一入退出口・4ホール会場で hallA への入場が急増。一方通行ループはセンサ無し",
        surge_edges=frozenset({EdgeID("e_con_A")}),
    )
