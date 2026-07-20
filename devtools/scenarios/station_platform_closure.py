"""駅コンコースで片方の階段容量が低下し、代替階段へ誘導するケース

グラフは ``station-stairs`` プリセット。エスカレーター保守停止などの運用上の理由で
階段 A の通行容量が大きく低下（危険フラグ＋容量上限 3）した通常運営時のケース。
改札からホームへ向かうラッシュ需要は最短路の階段 A に乗っているが、期待する提案は
容量上限を反映して代替階段 B 側へ大半を誘導する配分となる。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import NodeID

from .. import graph_builder
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
    built = with_edge_danger(graph_builder.station_stairs(), "e_stairs_a", 3.0)
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
