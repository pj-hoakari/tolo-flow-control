from __future__ import annotations

from .. import graph_builder
from ..scenario_base import Scenario
from ._observation import as_sent_run, to_scenario
from ._registry import register


@register("observation-as-sent")
def build() -> Scenario:
    built = graph_builder.venue()
    return to_scenario(
        "observation-as-sent",
        "tolo-observation が現在送る形のリクエスト。停滞観測と履歴が空のため急増中でも NO_TRIGGER",
        built,
        as_sent_run(built.graph),
        expect_trigger=False,
    )
