"""expo: 危険解除後の入場再開提案（境界制御の続き）シナリオ

前サイクルで `gate` の入場停止（PAUSE_INGRESS）を出していた状態を `previous_opt_result` で与える。
今サイクルは危険フラグが解除され（入口の軽い急増のみで発火）、最適化は停止していた `gate` への
再開（RESUME）を提案する。インシデント収束→再開という運用ライフサイクルを示す。
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID
from flow_control.optimization import BoundaryAction, BoundaryControl, OptimizationResult

from ..scenario_base import Scenario
from ._expo import make_expo_scenario
from ._registry import register

# 前サイクルで gate の入場を停止していた、という直前結果
_PREVIOUS = OptimizationResult(
    boundary_control=(
        BoundaryControl(
            node_id=NodeID("gate"),
            action=BoundaryAction.PAUSE_INGRESS,
            reason="prior incident",
        ),
    )
)


@register("expo-incident-resume")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-incident-resume",
        "前回 gate を入場停止。危険解除後、入口の軽い急増で再評価し gate の再開(RESUME)を提案",
        surge_edges=frozenset({EdgeID("e_gate_lobby")}),
        previous_opt_result=_PREVIOUS,
    )
