"""expo: 単一ホール急増シナリオ"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from ..scenario_base import ODSpec, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-single-hall-surge")
def build() -> Scenario:
    gate = NodeID("gate")
    return make_expo_scenario(
        "expo-single-hall-surge",
        "単一入退出口・4ホール会場で hallA への入場が急増。一方通行ループはセンサ無し",
        od_flows=(
            ODSpec(gate, NodeID("hallA"), 30.0, surge=True),
            ODSpec(gate, NodeID("hallB"), 15.0),
            ODSpec(gate, NodeID("hallD"), 12.0),
            ODSpec(gate, NodeID("hallC"), 10.0),
        ),
        trigger_edges=frozenset({EdgeID("e_con_A")}),
    )
