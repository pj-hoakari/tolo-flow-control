"""校舎: 北階段の上層部混雑を南階段・エレベーターへ分散するケース。"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import (
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._school import (
    school_gathering_od_specs,
    school_unobserved_edges,
)
from ._registry import register


@register("school-north-stair-peak")
def build() -> Scenario:
    built = graph_builder.school()
    hot = frozenset({EdgeID("e_north_stairs_f3_4")})
    observations, history = build_consistent_observations_and_history(
        built.graph,
        school_gathering_od_specs(staircase="north"),
        stagnation_edges=hot,
        unobserved_edges=school_unobserved_edges(),
        eta=0.03,
    )
    return make_scenario(
        "school-north-stair-peak",
        "1〜5階と1階入口から6階イベントへ集まり、北階段3-4階間の混雑を分散する",
        built,
        observations,
        history,
        previous_state=established_watch_state(hot),
    )
