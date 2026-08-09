"""校舎: 南階段の下層部混雑を北階段・エレベーターへ分散するケース。"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import (
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register
from ._school import (
    school_gathering_od_specs,
    school_unobserved_edges,
)


@register("school-south-stair-peak")
def build() -> Scenario:
    built = graph_builder.school()
    hot = frozenset({EdgeID("e_south_stairs_f2_3")})
    observations, history = build_consistent_observations_and_history(
        built.graph,
        school_gathering_od_specs(staircase="south"),
        stagnation_edges=hot,
        unobserved_edges=school_unobserved_edges(),
        eta=0.03,
    )
    return make_scenario(
        "school-south-stair-peak",
        "北階段が下り専用の時間帯、各階から6階へ集まる南階段2-3階間の混雑を分散する",
        built,
        observations,
        history,
        previous_state=established_watch_state(hot),
    )
