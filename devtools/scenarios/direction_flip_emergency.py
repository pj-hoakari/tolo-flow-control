"""誤向きの一方通行を解除して、避難・退出方向を回復する実証ケース。"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import CurrentDirection, DirectionConstraint, EdgeID, NodeKind

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("direction-flip-emergency")
def build() -> Scenario:
    """可変レーンが逆向きのとき、法的固定の帰路と合わせて解除を提案する。"""
    builder = GraphBuilder()
    builder.node("assembly", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    builder.node("exit", kind=NodeKind.GOAL, boundary=False, pos=(3.0, 0.0))
    # e_adjustable は前サイクルの運用で exit→assembly に設定されている。
    builder.edge(
        "e_adjustable",
        "assembly",
        "exit",
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.B_TO_A,
    )
    # 法的固定の帰路は exit→assembly。可変レーンを解除すれば双方向の退出導線が成立する。
    builder.edge(
        "e_return",
        "exit",
        "assembly",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    built = with_edge_danger(builder.build(), "e_adjustable", 100.0)
    observations, history = build_observations_and_history(
        built.graph,
        surge_edges=frozenset({EdgeID("e_adjustable")}),
        stagnation_edges=frozenset({EdgeID("e_adjustable")}),
        base_flow=12.0,
        hot_stag=30.0,
        eta=0.2,
    )
    return make_scenario(
        "direction-flip-emergency",
        "退出需要に対し逆向きの可変レーンを双方向へ解除し、法的固定の帰路と双方向導線を回復する",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_adjustable",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
