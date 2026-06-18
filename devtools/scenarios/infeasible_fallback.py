"""INFEASIBLE→方向固定 LP フォールバックシナリオ"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import CurrentDirection, DirectionConstraint, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
)
from ._registry import register


@register("infeasible-fallback")
def build() -> Scenario:
    # 葉ノード dead の唯一のエッジを LEGAL_FIXED で内向き固定 → 出方向可達性 out>=1 が
    # 0>=1 となり Phase1 INFEASIBLE。方向固定 LP フォールバックへ落ちる
    b = GraphBuilder()
    b.node("in", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("mid", kind=NodeKind.TRANSIT_ONLY, pos=(1.0, 0.0))
    b.node("dead", kind=NodeKind.GOAL, boundary=True, pos=(2.0, 0.0))
    b.edge("e1", "in", "mid")
    b.edge(
        "e2",
        "mid",
        "dead",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    built = b.build()
    obs, hist = build_observations_and_history(built.graph)
    return make_scenario(
        "infeasible-fallback",
        "法規制固定が可達性を破り Phase1 INFEASIBLE→方向固定 LP フォールバック",
        built,
        obs,
        hist,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e1",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
