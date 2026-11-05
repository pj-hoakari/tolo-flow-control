from __future__ import annotations

from dataclasses import replace

from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    compact_configs,
    established_watch_state,
    make_scenario,
)


def build_surge_ramp_scenario(threshold: int, *, expect_trigger: bool) -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1")})
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("in"), NodeID("hallA"), 24.0, surge=True),),
        stagnation_edges=hot,
        surge_start_ratio=0.25,
        surge_samples=16,
        flat_samples=31,
        eta=0.02,
    )
    configs = compact_configs()
    verdict = "発火する" if expect_trigger else "発火しない"
    return make_scenario(
        f"surge-fourfold-ramp-at-threshold-{threshold}",
        f"e_in_j1 の流量が 15 分平坦のあと 15 分で 4 倍に伸び、停滞警戒は成立済み。"
        f"急増しきい値 {threshold} %/分では{verdict}",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
        configs=replace(
            configs,
            detection=replace(
                configs.detection, surge_rate_threshold_percent_per_min=float(threshold)
            ),
        ),
        expect_trigger=expect_trigger,
    )
