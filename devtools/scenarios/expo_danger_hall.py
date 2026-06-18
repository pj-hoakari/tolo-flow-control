"""expo: ホール危険フラグシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind

from ..scenario_base import DEFAULT_TIME, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-danger-hall")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-danger-hall",
        "4ホール会場で hallB に危険フラグ立ち上げ。通過量上限が一方通行導線下で MILP に反映",
        node_danger=("hallB", 12.0),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="node:hallB",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
