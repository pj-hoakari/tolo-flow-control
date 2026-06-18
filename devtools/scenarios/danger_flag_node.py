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
    # 容量はホール滞留需要（~14）より上に設定し、上限が「適用されるが実行可能」な例にする
    built = with_node_danger(graph_builder.venue(), "hallA", capacity=20.0)
    obs, hist = build_observations_and_history(
        built.graph, occupancy=30.0, occupancy_delta=10.0, eta=0.02
    )
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
