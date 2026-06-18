"""高停滞シナリオ"""

from __future__ import annotations

from datetime import timedelta

from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
)
from ._registry import register


@register("high-stagnation")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = EdgeID("e_hallA_j2")
    obs, hist = build_observations_and_history(
        built.graph,
        stagnation_edges=frozenset({hot}),
        occupancy=30.0,
        occupancy_delta=10.0,
        eta=0.02,
    )
    # M 分継続を満たすため、前サイクルで両条件成立・計時開始済みの watch を与える
    prev = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=hot,
                percentile_breached=True,
                delta_breached=True,
                started_at=DEFAULT_TIME - timedelta(minutes=6),
            ),
        )
    )
    return make_scenario(
        "high-stagnation",
        "e_hallA_j2 が p90 以上かつ移動平均差 beta 以上で M 分継続し高停滞発火",
        built,
        obs,
        hist,
        previous_state=prev,
    )
