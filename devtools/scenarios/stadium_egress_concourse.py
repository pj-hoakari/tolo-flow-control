"""スタジアム退場ピークで可変コンコースを退場方向へ解除する複合ケース

試合終了後の通常の退場運営。観客はボウル（場内広場）から東側の主出口へ向かうが、
幅の広い可変コンコース `e_concourse` は入場時の運用（east_exit→bowl 向き）のまま
残っており、退場は常設の細い階段 `e_egress_stair`（容量ヒント小）に集中して停滞する。
北・南ゲートへ抜ける副次的な退場流はスカラー観測の支線（ホワイエ・広場経由）を通る。

期待する提案は `e_concourse` の解除（RELEASE_ONEWAY → BIDIRECTIONAL）による
主出口導線の回復と、支線側の退場流の維持。可変コンコース入口の滞留はライン計測が
なく（lineless）、停滞のみの縮退発火となる。避難・緊急対応ではなく、イベント運営の
定常サイクル（入場運用→退場運用の切替）を表す。

現実に即したモデル化: ボウルは観客が滞留し退場時に放出源となる内部の混在ノード
（ΔOcc<0）、各出口（東主出口・北/南ゲート）は場外への入退出点（境界 GOAL）とする。

既知の制約: 現行 Forecasting は Open モードで混在ノード起点の OD を導出しない
（生成源は境界または純 GOAL のみ）ため、退場需要が OD に乗らず提案が空になる。
エンジン制約ドキュメント（docs/engine_constraints_20260720.md）の E1 を参照。
"""

from __future__ import annotations

from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    EdgeID,
    NodeID,
    NodeKind,
    ObservationType,
)

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
    b.node("north_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 2.0))
    b.node("south_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, -2.0))
    b.node("west_plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.4, 0.0))
    b.node("north_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, 1.8))
    b.node("bowl", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.0))
    b.node("south_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, -1.8))
    b.node("east_exit", kind=NodeKind.GOAL, boundary=True, pos=(6.0, 0.0))

    # 支線は方向別ラインを持たないスカラー観測の通路として表す（疎観測の現実性）
    b.edge("e_north_gate", "north_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    b.edge("e_south_gate", "south_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    b.edge("e_west_north", "west_plaza", "north_foyer", observation_type=ObservationType.SCALAR)
    b.edge("e_west_south", "west_plaza", "south_foyer", observation_type=ObservationType.SCALAR)
    b.edge("e_north_bowl", "north_foyer", "bowl", observation_type=ObservationType.SCALAR)
    b.edge("e_south_bowl", "south_foyer", "bowl", observation_type=ObservationType.SCALAR)
    # 迂回用のクロス通路。片側ホワイエが混雑しても合流できる
    b.edge("e_foyer_cross", "north_foyer", "south_foyer", observation_type=ObservationType.SCALAR)
    # 入場運用のまま残った可変コンコース（east_exit→bowl 向き・幅広）
    b.edge(
        "e_concourse",
        "bowl",
        "east_exit",
        capacity_hint=60.0,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.B_TO_A,
    )
    # 常設の退場階段（bowl→east_exit の一方通行・容量小）
    b.edge(
        "e_egress_stair",
        "bowl",
        "east_exit",
        capacity_hint=8.0,
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    return b


@register("stadium-egress-concourse")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_concourse")})
    # 主出口行き 30 が細い常設階段に集中して急増。北・南ゲートへの退場は支線経由。
    # スカラー支線も経路に使うため route_vector_only=False を指定する
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("bowl"), NodeID("east_exit"), 30.0, surge=True),
            ODSpec(NodeID("bowl"), NodeID("north_gate"), 10.0),
            ODSpec(NodeID("bowl"), NodeID("south_gate"), 9.0),
        ),
        stagnation_edges=hot,
        lineless_edges=hot,
        eta=0.03,
        route_vector_only=False,
    )
    return make_scenario(
        "stadium-egress-concourse",
        "退場ピークで入場向きのまま残った可変コンコースを双方向へ解除し、主出口への退場導線を回復する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
