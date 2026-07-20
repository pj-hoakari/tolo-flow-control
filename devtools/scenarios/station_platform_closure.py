"""駅コンコースで片方の階段容量が低下し、代替階段へ誘導するケース

エスカレーター保守停止などの運用上の理由で階段 A の通行容量が大きく低下
（危険フラグ＋容量上限 3）した通常運営時のケース。改札からホームへ向かう
ラッシュ需要は最短路の階段 A に乗っているが、期待する提案は容量上限を反映して
代替階段 B 側へ大半を誘導する配分となる。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import NodeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    DEFAULT_TIME,
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("station-platform-closure")
def build() -> Scenario:
    builder = GraphBuilder()
    builder.node("ticket_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    builder.node("concourse", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    builder.node("stairs_a", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, 1.0))
    builder.node("stairs_b", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, -1.0))
    builder.node("platform", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(4.0, 0.0))
    builder.edge("e_gate_concourse", "ticket_gate", "concourse")
    builder.edge("e_stairs_a", "concourse", "stairs_a")
    builder.edge("e_stairs_a_platform", "stairs_a", "platform")
    builder.edge("e_stairs_b", "concourse", "stairs_b")
    builder.edge("e_stairs_b_platform", "stairs_b", "platform")
    built = with_edge_danger(builder.build(), "e_stairs_a", 3.0)
    # ホーム行きラッシュ需要 25 は最短路（階段 A 側）に乗って観測される
    observations, history = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("ticket_gate"), NodeID("platform"), 25.0, surge=True),),
        eta=0.03,
    )
    return make_scenario(
        "station-platform-closure",
        "駅の片方の階段 e_stairs_a が低容量化し、代替階段経由でホームへ誘導する",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_stairs_a",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
