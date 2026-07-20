"""エッジ危険フラグシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import NodeID

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("danger-flag-edge")
def build() -> Scenario:
    built = with_edge_danger(graph_builder.venue(), "e_j1_hallB", capacity=5.0)
    # hallB 行き 20 は危険容量 5 を超えるため、配分は hallA→j2 経由の迂回へ回る
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("hallB"), 20.0),
            ODSpec(NodeID("in"), NodeID("hallA"), 10.0),
        ),
        eta=0.02,
    )
    return make_scenario(
        "danger-flag-edge",
        "e_j1_hallB に危険フラグ立ち上げ。容量上限が配分に反映され迂回が生じる",
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
