"""クールタイム中の発火 → QUEUED シナリオ

組合せ発火の条件は満たすが、クールタイム中のため即時発火せずトリガーキューへ積まれる。
スコア・多様性の閾値を超えないので verdict は QUEUED（下流は実行されない）。
キューに積まれた分は次サイクル以降の統合発火（queue-burst-fire）で消化される。
"""

from __future__ import annotations

from flow_control.detection.state import DetectionState

from ..scenario_base import Scenario
from ._registry import register
from ._state_transition import build_state_scenario, cooldown_until, firing_watch_states


@register("cooldown-queued")
def build() -> Scenario:
    return build_state_scenario(
        "cooldown-queued",
        "クールタイム中に組合せ発火。閾値未満のためキューへ積まれ QUEUED となる",
        previous_state=DetectionState(
            cooldown_until=cooldown_until(),
            arc_watch_states=firing_watch_states(),
        ),
        expect_trigger=False,
    )
