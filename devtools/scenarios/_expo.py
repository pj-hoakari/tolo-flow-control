"""expo グラフ（出入口1・ホール4・一方通行ループ）シナリオ共通部品"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flow_control.detection.triggers import Event
from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import (
    PipelineConfigs,
    Scenario,
    build_observations_and_history,
    compact_configs,
    make_scenario,
    with_edge_danger,
    with_node_danger,
)

if TYPE_CHECKING:
    from flow_control.optimization import OptimizationResult

# 一方通行ループの4エッジ（既定でセンサ無し＝観測のないルート）
EXPO_LOOP_EDGES = frozenset(
    {EdgeID("e_loop_AB"), EdgeID("e_loop_BD"), EdgeID("e_loop_DC"), EdgeID("e_loop_CA")}
)


def expo_configs() -> PipelineConfigs:
    """expo（大規模）向け設定

    単一アクセス通路に全ホール需要が集中しコモディティ数が多いため、OD 量カット
    ``delta_min`` を venue 系よりさらに上げて Phase2 の MILP を軽くする。
    """
    return compact_configs(delta_min=12.0, milp_time_limit_sec=8.0)


def make_expo_scenario(
    name: str,
    description: str,
    *,
    surge_edges: frozenset[EdgeID] = frozenset(),
    extra_unobserved_edges: frozenset[EdgeID] = frozenset(),
    unobserved_nodes: frozenset[NodeID] = frozenset(),
    node_danger: tuple[str, float] | None = None,
    edge_danger: tuple[str, float] | None = None,
    events: tuple[Event, ...] = (),
    previous_opt_result: "OptimizationResult | None" = None,
) -> Scenario:
    """expo グラフ上のシナリオを共通設定（滞留あり・eta 小・delta_min 引上げ）で組む"""
    built = graph_builder.expo()
    if node_danger is not None:
        built = with_node_danger(built, node_danger[0], node_danger[1])
    if edge_danger is not None:
        built = with_edge_danger(built, edge_danger[0], edge_danger[1])
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=surge_edges,
        unobserved_edges=EXPO_LOOP_EDGES | extra_unobserved_edges,
        unobserved_nodes=unobserved_nodes,
        occupancy=30.0,
        occupancy_delta=15.0,  # 各ホールに滞留が生じる（蓄積フェーズ）
        # 単一アクセス通路が全ホール需要を運べるよう排出上限 eta*f<=s_obs を緩める
        eta=0.02,
    )
    return make_scenario(
        name,
        description,
        built,
        obs,
        hist,
        events=events,
        configs=expo_configs(),
        previous_opt_result=previous_opt_result,
    )
