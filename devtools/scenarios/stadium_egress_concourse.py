"""スタジアム退場ピークで可変コンコースを退場方向へ解除する複合ケース

グラフは ``stadium`` プリセット。試合終了後の通常の退場運営。観客はボウル
（場内広場＝滞留する混在ノード）から東側の主出口へ向かうが、幅の広い可変コンコース
`e_concourse` は入場時の運用（east_exit→bowl 向き）のまま残っており、退場は常設の
細い階段 `e_egress_stair`（容量ヒント小）に集中して停滞する。北・南ゲートへ抜ける
副次的な退場流はスカラー観測の支線（ホワイエ・広場経由）を通る。

期待する提案は `e_concourse` の解除（RELEASE_ONEWAY → BIDIRECTIONAL）による
主出口導線の回復と、支線側の退場流の維持。可変コンコース入口の滞留はライン計測が
なく（lineless）、停滞のみの縮退発火となる。避難・緊急対応ではなく、イベント運営の
定常サイクル（入場運用→退場運用の切替）を表す。

既知の制約: 現行 Forecasting は Open モードで混在ノード起点の OD を導出しない
（生成源は境界または純 GOAL のみ）ため、退場需要が OD に乗らず提案が空になる。
エンジン制約ドキュメント（docs/engine_constraints_20260720.md）の E1 を参照。
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


@register("stadium-egress-concourse")
def build() -> Scenario:
    built = graph_builder.stadium()
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
