"""キュー蓄積による統合発火シナリオ

クールタイム中でも、キューの累積スコアが ``queue_score_threshold`` を超えると
統合発火する（QueueScoreEvidence）。長時間くすぶる混雑をクールタイムで
取りこぼさないための機構で、既存の cooldown-queued の続きに当たる。
"""

from __future__ import annotations

from datetime import timedelta

from flow_control.detection.state import (
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
)
from flow_control.domain import EdgeID

from ..scenario_base import DEFAULT_TIME, Scenario
from ._registry import register
from ._state_transition import (
    HOT_EDGE,
    build_state_scenario,
    cooldown_until,
    firing_watch_states,
)

# 既定の queue_score_threshold=5.0 を超える蓄積（別アーク由来を 2 件）
_QUEUE = (
    QueuedTrigger(
        kind=QueuedTriggerKind.HIGH_STAGNATION,
        first_fired_at=DEFAULT_TIME - timedelta(minutes=20),
        last_fired_at=DEFAULT_TIME - timedelta(minutes=5),
        accumulated_score=3.5,
        origin_edge_id=EdgeID("e_j1_hallA"),
    ),
    QueuedTrigger(
        kind=QueuedTriggerKind.HIGH_STAGNATION,
        first_fired_at=DEFAULT_TIME - timedelta(minutes=15),
        last_fired_at=DEFAULT_TIME - timedelta(minutes=4),
        accumulated_score=2.5,
        origin_edge_id=HOT_EDGE,
    ),
)


@register("queue-burst-fire")
def build() -> Scenario:
    return build_state_scenario(
        "queue-burst-fire",
        "クールタイム中でもキュー累積スコアが閾値超過で統合発火する",
        previous_state=DetectionState(
            cooldown_until=cooldown_until(),
            trigger_queue=_QUEUE,
            arc_watch_states=firing_watch_states(),
        ),
        expect_trigger=True,
    )
