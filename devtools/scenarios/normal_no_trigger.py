"""正常（未発火）シナリオ"""

from __future__ import annotations

from .. import graph_builder
from ..scenario_base import Scenario, build_observations_and_history, make_scenario
from ._registry import register


@register("normal-no-trigger")
def build() -> Scenario:
    built = graph_builder.venue()
    # 平坦な流量・低い停滞・移動平均との差小 → 何も発火しない
    obs, hist = build_observations_and_history(
        built.graph,
        base_stag=2.0,
        recent_stag_ma=2.0,
        p90_stag=8.0,
        occupancy=30.0,
        occupancy_delta=10.0,
        eta=0.02,
    )
    return make_scenario(
        "normal-no-trigger",
        "急増も高停滞もなく NO_TRIGGER。下流は --force 指定時のみ実行",
        built,
        obs,
        hist,
        expect_trigger=False,
    )
