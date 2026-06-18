"""expo: hallA 直行アプローチの容量制限 → 一方通行ループへ迂回するシナリオ

hallA への直行スポーク `e_con_A` が危険フラグで低容量（=3）に制限される。hallA への需要は
concourse 直行では運びきれず、時計回りの一方通行ループ経由（hallC→hallA 等）へ迂回する。
route_importance がスポークからループへ移るのが分かりやすい効果。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import EdgeID

from ..scenario_base import DEFAULT_TIME, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-approach-capacity")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-approach-capacity",
        "hallA 直行 e_con_A が低容量に制限。hallA 需要が一方通行ループ経由へ迂回する",
        surge_edges=frozenset({EdgeID("e_gate_lobby")}),
        edge_danger=("e_con_A", 3.0),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_con_A",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
