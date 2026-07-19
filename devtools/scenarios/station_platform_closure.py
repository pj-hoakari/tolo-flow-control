"""駅コンコースで片方の階段容量が低下し、代替階段へ誘導するケース。"""

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


@register("station-platform-closure")
def build() -> Scenario:
    builder = GraphBuilder()
    builder.node("ticket_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    builder.node("concourse", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    builder.node("stairs_a", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, 1.0))
    builder.node("stairs_b", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, -1.0))
    builder.node("platform", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(4.0, 0.0))
    builder.edge("e_gate_concourse", "ticket_gate", "concourse")
    builder.edge("e_stairs_a", "concourse", "stairs_a")
    builder.edge("e_stairs_a_platform", "stairs_a", "platform")
    builder.edge("e_stairs_b", "concourse", "stairs_b")
    builder.edge("e_stairs_b_platform", "stairs_b", "platform")
    built = with_edge_danger(builder.build(), "e_stairs_a", 3.0)
    observations, history = build_observations_and_history(
        built.graph,
        surge_edges=frozenset({EdgeID("e_gate_concourse")}),
        occupancy=28.0,
        occupancy_delta=10.0,
        eta=0.03,
    )
    return make_scenario(
        "station-platform-closure",
        "駅の片方の階段 e_stairs_a が低容量化し、代替階段経由でホームへ誘導する",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_stairs_a",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
