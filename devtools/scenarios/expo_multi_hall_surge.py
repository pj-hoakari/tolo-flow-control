"""expo: 複数ホール急増シナリオ（hallD 占有欠測）

急増ホールは VECTOR 観測スポークを持つ hallA / hallB とする（hallC スポークは
SCALAR 観測でライン系列を持たず、組合せ発火の需要警戒を満たせないため）。
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from ..scenario_base import ODSpec, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-multi-hall-surge")
def build() -> Scenario:
    gate = NodeID("gate")
    return make_expo_scenario(
        "expo-multi-hall-surge",
        "hallA と hallB が同時に人気化し急増。hallD は占有センサ欠測、ループはセンサ無し",
        od_flows=(
            ODSpec(gate, NodeID("hallA"), 25.0, surge=True),
            ODSpec(gate, NodeID("hallB"), 20.0, surge=True),
            ODSpec(gate, NodeID("hallD"), 12.0),
            ODSpec(gate, NodeID("hallC"), 10.0),
        ),
        trigger_edges=frozenset({EdgeID("e_con_A"), EdgeID("e_con_B")}),
        unobserved_nodes=frozenset({NodeID("hallD")}),
    )
