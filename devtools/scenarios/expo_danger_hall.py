"""expo: ホール危険フラグシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import NodeID

from ..scenario_base import DEFAULT_TIME, ODSpec, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-danger-hall")
def build() -> Scenario:
    # hallB 行き需要（10）は通過量上限（12）の内側で「適用されるが実行可能」な例
    gate = NodeID("gate")
    return make_expo_scenario(
        "expo-danger-hall",
        "4ホール会場で hallB に危険フラグ立ち上げ。通過量上限が一方通行導線下で配分に反映",
        od_flows=(
            ODSpec(gate, NodeID("hallA"), 15.0),
            ODSpec(gate, NodeID("hallB"), 10.0),
            ODSpec(gate, NodeID("hallC"), 9.0),
        ),
        node_danger=("hallB", 12.0),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="node:hallB",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
