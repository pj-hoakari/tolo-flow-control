"""フェス会場の入場ゲート集中を、二系統の広場導線へ分散するケース。"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import EdgeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("festival-gate-split")
def build() -> Scenario:
    builder = GraphBuilder()
    builder.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    builder.node("plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    builder.node("food", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 1.0))
    builder.node("main_stage", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -1.0))
    builder.node("exit", kind=NodeKind.GOAL, boundary=True, pos=(4.5, 0.0))
    builder.edge("e_gate_plaza", "gate", "plaza", capacity_hint=18.0)
    builder.edge("e_food", "plaza", "food")
    builder.edge("e_stage", "plaza", "main_stage")
    builder.edge("e_food_stage", "food", "main_stage")
    builder.edge("e_food_exit", "food", "exit")
    builder.edge("e_stage_exit", "main_stage", "exit")
    built = with_edge_danger(builder.build(), "e_gate_plaza", 18.0)
    observations, history = build_observations_and_history(
        built.graph,
        surge_edges=frozenset({EdgeID("e_gate_plaza")}),
        occupancy=35.0,
        occupancy_delta=14.0,
        eta=0.04,
    )
    return make_scenario(
        "festival-gate-split",
        "入場ゲートの急増をフード広場・メインステージの二系統へ分散するフェス会場導線",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_gate_plaza",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
