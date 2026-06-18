"""ノード危険フラグシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
    with_node_danger,
)
from ._registry import register


@register("danger-flag-node")
def build() -> Scenario:
    built = with_node_danger(graph_builder.venue(), "hallA", capacity=8.0)
    obs, hist = build_observations_and_history(built.graph)
    return make_scenario(
        "danger-flag-node",
        "ノード hallA に危険フラグ立ち上げ。通過量（流入）上限が MILP に反映される",
        built,
        obs,
        hist,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="node:hallA",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
