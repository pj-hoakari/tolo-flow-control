"""検出の状態遷移（クールタイム・キュー・ウォームアップ）シナリオ共通部品

いずれも venue グラフに組合せ発火の条件（急増＋停滞＋計時済み watch）を与えたうえで、
``previous_state`` の cooldown / trigger_queue / warmup を変えて verdict の分岐を作る。
単発リクエストの devtools では時間経過を再現できないため、前サイクル状態として与える。
"""

from __future__ import annotations

from datetime import timedelta

from flow_control.detection.state import ArcWatchState, DetectionState, WarmupState
from flow_control.domain import EdgeID, Graph, NodeID

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    make_scenario,
)

HOT_EDGE = EdgeID("e_in_j1")


def firing_watch_states(*, established: bool = True) -> tuple[ArcWatchState, ...]:
    """組合せ発火の停滞側条件（M 分継続）を満たした watch"""
    if not established:
        return ()
    return (
        ArcWatchState(
            edge_id=HOT_EDGE,
            percentile_breached=True,
            delta_breached=True,
            stagnation_watch_since=DEFAULT_TIME - timedelta(minutes=6),
        ),
    )


def build_state_scenario(
    name: str,
    description: str,
    *,
    previous_state: DetectionState,
    expect_trigger: bool,
    firing: bool = True,
) -> Scenario:
    """venue 上に組合せ発火（firing=True）の観測を置き、previous_state で分岐させる"""
    built = graph_builder.venue()
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("hallA"), 25.0, surge=firing),
            ODSpec(NodeID("in"), NodeID("hallB"), 10.0),
        ),
        stagnation_edges=frozenset({HOT_EDGE}) if firing else frozenset(),
        eta=0.02,
    )
    return make_scenario(
        name,
        description,
        built,
        obs,
        hist,
        previous_state=previous_state,
        expect_trigger=expect_trigger,
    )


def cooldown_until(minutes: float = 30.0):
    """server_time から ``minutes`` 分先までクールタイム中とする"""
    return DEFAULT_TIME + timedelta(minutes=minutes)


def warmup_all(graph: Graph, minutes: float = 30.0) -> tuple[WarmupState, ...]:
    """全アーク・ノードをウォームアップ中にする"""
    until = DEFAULT_TIME + timedelta(minutes=minutes)
    keys = [f"edge:{e.edge_id.value}" for e in graph.enabled_edges()]
    keys += [f"node:{n.node_id.value}" for n in graph.enabled_nodes()]
    return tuple(WarmupState(target_key=k, until=until) for k in keys)
