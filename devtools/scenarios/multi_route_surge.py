"""複数ルート急増シナリオ

入口から hallA へ向かう連続 2 エッジ（e_in_j1・e_j1_hallA）が同時に急増＋停滞し、
複数トリガーの統合処理と迂回路の列挙を確認する。hallA 行きの急増がホットエッジ
2 本を覆い、hallB 行きを平常成分として残す。期待する提案は hallA 経路の混雑を
hallB 側へ逃がす配分と、e_j1_hallA に対する迂回路（直結コリドー経由）の列挙。

（境界→境界の通過需要 ext→ext は Open モードの対象外のため、需要はすべて
ホールを目的地とする。）
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


@register("multi-route-surge")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1"), EdgeID("e_j1_hallA")})
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("hallA"), 25.0, surge=True),
            ODSpec(NodeID("in"), NodeID("hallB"), 10.0),
        ),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "multi-route-surge",
        "入口〜hallA の連続 2 エッジが同時急増＋停滞。複数トリガーと迂回路を確認する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
