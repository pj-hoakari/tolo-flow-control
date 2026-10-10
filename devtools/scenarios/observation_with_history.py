from __future__ import annotations

from .. import graph_builder
from ..scenario_base import Scenario
from ._observation import to_scenario, with_history_run
from ._registry import register


@register("observation-with-history")
def build() -> Scenario:
    built = graph_builder.venue()
    return to_scenario(
        "observation-with-history",
        "停滞観測と直近 30 サイクルの履歴を足し、急増閾値を 10%/分にすると組合せ発火する",
        built,
        with_history_run(built.graph),
        expect_trigger=True,
    )
