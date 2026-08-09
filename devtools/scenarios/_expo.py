"""expo グラフ（出入口1・ホール4・一方通行ループ）シナリオ共通部品"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flow_control.detection.triggers import Event
from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import (
    ODSpec,
    PipelineConfigs,
    Scenario,
    build_consistent_observations_and_history,
    compact_configs,
    established_watch_state,
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

    軽量モードが既定となり配分 LP は軽いため、OD 量カット ``delta_min`` は
    compact 既定（8.0）をそのまま使う。STRICT で基準系を回す場合に備えて
    MILP 時間上限のみ短縮を維持する。
    """
    return compact_configs(milp_time_limit_sec=8.0)


def make_expo_scenario(
    name: str,
    description: str,
    *,
    od_flows: tuple[ODSpec, ...],
    trigger_edges: frozenset[EdgeID] = frozenset(),
    extra_unobserved_edges: frozenset[EdgeID] = frozenset(),
    unobserved_nodes: frozenset[NodeID] = frozenset(),
    node_danger: tuple[str, float] | None = None,
    edge_danger: tuple[str, float] | None = None,
    events: tuple[Event, ...] = (),
    previous_opt_result: OptimizationResult | None = None,
) -> Scenario:
    """expo グラフ上のシナリオを保存則整合の観測で組む

    ``od_flows`` を current 方向の最短路で流し込み（一方通行ループはセンサ無しの
    まま経路に使われ、Forecasting の保存補完が働く）、``trigger_edges`` に
    停滞警戒＋計時済み watch を与えて組合せ発火させる（空なら危険フラグ等の
    イベント発火のみ）。
    """
    built = graph_builder.expo()
    if node_danger is not None:
        built = with_node_danger(built, node_danger[0], node_danger[1])
    if edge_danger is not None:
        built = with_edge_danger(built, edge_danger[0], edge_danger[1])
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        od_flows,
        stagnation_edges=trigger_edges,
        unobserved_edges=EXPO_LOOP_EDGES | extra_unobserved_edges,
        unobserved_nodes=unobserved_nodes,
        # 単一アクセス通路が全ホール需要を運べるよう排出上限 eta*f<=s_obs を緩める
        eta=0.02,
    )
    return make_scenario(
        name,
        description,
        built,
        obs,
        hist,
        previous_state=(established_watch_state(trigger_edges) if trigger_edges else None),
        events=events,
        configs=expo_configs(),
        previous_opt_result=previous_opt_result,
    )
