"""expo: 一方通行＋疎観測（観測のないルート/ポイント）シナリオ"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from ..scenario_base import Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-oneway-unobserved")
def build() -> Scenario:
    # 観測のないルート/ポイントを多めに含み、一方通行ループと併せて疎観測下の挙動を見る
    return make_expo_scenario(
        "expo-oneway-unobserved",
        "入口急増。一方通行ループ＋hallD スポークがセンサ無し、hallD は占有欠測（疎観測）",
        surge_edges=frozenset({EdgeID("e_gate_lobby")}),
        extra_unobserved_edges=frozenset({EdgeID("e_con_D")}),
        unobserved_nodes=frozenset({NodeID("hallD")}),
    )
