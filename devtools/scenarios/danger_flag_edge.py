"""エッジ危険フラグシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("danger-flag-edge")
def build() -> Scenario:
    built = with_edge_danger(graph_builder.venue(), "e_j1_hallB", capacity=5.0)
    obs, hist = build_observations_and_history(
        built.graph, occupancy=30.0, occupancy_delta=10.0, eta=0.02
    )
    return make_scenario(
        "danger-flag-edge",
        "e_j1_hallB に危険フラグ立ち上げ。エッジ容量上限が MILP に反映される",
        built,
        obs,
        hist,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_j1_hallB",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
