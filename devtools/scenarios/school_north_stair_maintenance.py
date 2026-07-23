"""校舎: 北階段の保守による通行容量低下を迂回するケース。"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_consistent_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._school import (
    school_gathering_od_specs,
    school_unobserved_edges,
)
from ._registry import register


@register("school-north-stair-maintenance")
def build() -> Scenario:
    built = with_edge_danger(graph_builder.school(), "e_north_stairs_f4_5", 10.0)
    observations, history = build_consistent_observations_and_history(
        built.graph,
        school_gathering_od_specs(staircase="north"),
        unobserved_edges=school_unobserved_edges(),
        eta=0.03,
    )
    return make_scenario(
        "school-north-stair-maintenance",
        "各階から6階へ集まる時間帯、北階段4-5階間の保守による容量低下を迂回する",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_north_stairs_f4_5",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
