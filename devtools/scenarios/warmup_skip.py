"""ウォームアップ中 → SKIPPED_WARMUP シナリオ

観測点の追加・交換直後は履歴統計が信頼できないため、対象はウォームアップ期間中
トリガー判定を停止する。全対象がウォームアップ中なら verdict は SKIPPED_WARMUP
となり下流は実行されない（危険フラグイベントがあれば例外的に発火する）。
"""

from __future__ import annotations

from flow_control.detection.state import DetectionState

from .. import graph_builder
from ..scenario_base import Scenario
from ._registry import register
from ._state_transition import build_state_scenario, firing_watch_states, warmup_all


@register("warmup-skip")
def build() -> Scenario:
    graph = graph_builder.venue().graph
    return build_state_scenario(
        "warmup-skip",
        "全対象がウォームアップ中。組合せ発火の条件下でも SKIPPED_WARMUP となる",
        previous_state=DetectionState(
            warmup_states=warmup_all(graph),
            arc_watch_states=firing_watch_states(),
        ),
        expect_trigger=False,
    )
