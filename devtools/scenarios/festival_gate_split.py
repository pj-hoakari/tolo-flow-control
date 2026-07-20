"""フェス会場の入場ゲート集中を、二系統の広場導線へ分散するケース

入場ゲートからの一本道 `e_gate_plaza`（容量ヒント 18 の狭い動線）にフード広場行き・
メインステージ行きの需要（計 30）が重なって急増し、組合せ発火する。期待する提案は
plaza での二系統（`e_food` / `e_stage`）への分散配分（需要比を反映した重み）と、
ゲート動線が容量超過であることを踏まえた入場側の抑制。

既知の制約: 需要がゲート容量を超えるため現行エンジンでは Phase1 が INFEASIBLE となり、
容量スラック付きフォールバック LP の分散配分のみが返る（方向提案は空、
fallback_to_previous=true）。エンジン制約ドキュメントの E4 を参照。
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


def _build_graph() -> GraphBuilder:
    b = GraphBuilder()
    b.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("food", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 1.0))
    b.node("main_stage", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -1.0))
    b.node("exit", kind=NodeKind.GOAL, boundary=True, pos=(4.5, 0.0))
    b.edge("e_gate_plaza", "gate", "plaza", capacity_hint=18.0)
    b.edge("e_food", "plaza", "food")
    b.edge("e_stage", "plaza", "main_stage")
    b.edge("e_food_stage", "food", "main_stage")
    b.edge("e_food_exit", "food", "exit")
    b.edge("e_stage_exit", "main_stage", "exit")
    return b


@register("festival-gate-split")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_gate_plaza")})
    # フード行き・ステージ行きの両需要が入場路に重なって急増する
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("gate"), NodeID("main_stage"), 18.0, surge=True),
            ODSpec(NodeID("gate"), NodeID("food"), 12.0, surge=True),
        ),
        stagnation_edges=hot,
        eta=0.04,
    )
    return make_scenario(
        "festival-gate-split",
        "入場ゲートの急増をフード広場・メインステージの二系統へ分散するフェス会場導線",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
