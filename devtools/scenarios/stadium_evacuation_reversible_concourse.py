"""スタジアム退場時に可変コンコースを解除する、複合的な方向変更ケース。"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    EdgeID,
    NodeKind,
    ObservationType,
)

from ..graph_builder import GraphBuilder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
    with_edge_danger,
)
from ._registry import register


@register("stadium-evacuation-reversible-concourse")
def build() -> Scenario:
    """複数ゲートを持つ場内で、東側可変コンコースの解除を評価する。"""
    builder = GraphBuilder()
    # 北・南の入退場ゲートから中央ボウルへ集まり、東側の主出口へ退場する。
    builder.node("north_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 2.0))
    builder.node("south_gate", kind=NodeKind.GOAL, pos=(0.0, -2.0))
    builder.node("west_plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.4, 0.0))
    builder.node("north_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, 1.8))
    builder.node("central_bowl", kind=NodeKind.GOAL, boundary=True, pos=(3.0, 0.0))
    builder.node("south_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, -1.8))
    builder.node("east_exit", kind=NodeKind.GOAL, pos=(6.0, 0.0))

    # 支線は方向別ラインを持たないスカラー観測の通路として表す。
    # Forecasting の OD を主退出導線の方向別観測で決めつつ、Optimization では
    # 実在する複数ホワイエ・クロス通路の連結性を安全性検査に含める。
    builder.edge("e_north_gate", "north_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    builder.edge("e_south_gate", "south_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    builder.edge("e_west_north", "west_plaza", "north_foyer", observation_type=ObservationType.SCALAR)
    builder.edge("e_west_south", "west_plaza", "south_foyer", observation_type=ObservationType.SCALAR)
    builder.edge("e_north_bowl", "north_foyer", "central_bowl", observation_type=ObservationType.SCALAR)
    builder.edge("e_south_bowl", "south_foyer", "central_bowl", observation_type=ObservationType.SCALAR)
    # 迂回用のクロス通路。片側ホワイエが混雑しても中央へ合流できる。
    builder.edge("e_foyer_cross", "north_foyer", "south_foyer", observation_type=ObservationType.SCALAR)
    # 前サイクルの入場運用が残り、東向きの避難導線が閉じている可変コンコース。
    builder.edge(
        "e_reversible_east_concourse",
        "central_bowl",
        "east_exit",
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.B_TO_A,
    )
    # 消防上固定された戻り用サービス通路。可変コンコースの解除後も変更しない。
    builder.edge(
        "e_fixed_return_service",
        "east_exit",
        "central_bowl",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )

    built = with_edge_danger(builder.build(), "e_reversible_east_concourse", 100.0)
    observations, history = build_observations_and_history(
        built.graph,
        surge_edges=frozenset({EdgeID("e_reversible_east_concourse")}),
        stagnation_edges=frozenset({EdgeID("e_reversible_east_concourse")}),
        base_flow=16.0,
        hot_stag=32.0,
        eta=0.08,
    )
    return make_scenario(
        "stadium-evacuation-reversible-concourse",
        "複数ゲート・ホワイエ・迂回クロス通路を持つスタジアムで、誤向きの東側可変コンコースを双方向へ解除して主出口への避難導線を回復する",
        built,
        observations,
        history,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_reversible_east_concourse",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
