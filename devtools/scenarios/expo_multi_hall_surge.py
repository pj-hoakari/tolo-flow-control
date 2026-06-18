"""expo: 複数ホール急増シナリオ（hallD 占有欠測）"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from ..scenario_base import Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-multi-hall-surge")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-multi-hall-surge",
        "hallA と hallC が同時に人気化し急増。hallD は占有センサ欠測、ループはセンサ無し",
        surge_edges=frozenset({EdgeID("e_con_A"), EdgeID("e_con_C")}),
        unobserved_nodes=frozenset({NodeID("hallD")}),
    )
