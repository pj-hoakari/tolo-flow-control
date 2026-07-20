"""クールタイム中・トリガーなし → SKIPPED_COOLDOWN シナリオ

前サイクルで発火してクールタイムに入っており、今サイクルは警戒条件も満たさない。
下流は実行されず、状態（cooldown・キュー）は据え置かれる。
"""

from __future__ import annotations

from flow_control.detection.state import DetectionState

from ..scenario_base import Scenario
from ._registry import register
from ._state_transition import build_state_scenario, cooldown_until


@register("cooldown-skip")
def build() -> Scenario:
    return build_state_scenario(
        "cooldown-skip",
        "クールタイム中でトリガーなし。SKIPPED_COOLDOWN で下流をスキップする",
        previous_state=DetectionState(cooldown_until=cooldown_until()),
        expect_trigger=False,
        firing=False,
    )
