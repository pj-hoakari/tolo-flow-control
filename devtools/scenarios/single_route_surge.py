"""単一ルート急増シナリオ（組合せ発火のベースライン）

入口ルート e_in_j1 で急増（需要警戒）と高停滞（M 分継続）が同時成立し、
組合せ発火する最小構成。入口は単一エッジのため迂回路は存在せず（k_effective=0）、
期待する提案は j1 での hallA / hallB への配分（需要比 25:10 を容量とのバランスで
反映した重み）となる。
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


@register("single-route-surge")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1")})
    # hallA 行きが急増、hallB 行きは平常。急増成分が入口エッジを通り需要警戒を満たす
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
        "single-route-surge",
        "入口ルート e_in_j1 が急増＋停滞し組合せ発火。単一エッジのトリガーを確認する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
