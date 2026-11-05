from __future__ import annotations

from ..scenario_base import Scenario
from ._registry import register
from ._surge_ramp import build_surge_ramp_scenario


@register("surge-fourfold-ramp-at-threshold-10")
def build() -> Scenario:
    return build_surge_ramp_scenario(10, expect_trigger=False)
