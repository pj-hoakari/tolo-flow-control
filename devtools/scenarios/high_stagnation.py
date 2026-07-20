"""高停滞シナリオ（ラインなしエッジの縮退発火）

現行 Detection はライン観測のあるエッジでは停滞警戒単独で発火しない（需要警戒との
組合せが必要）。本シナリオはホットエッジを「ライン通過観測なし・停滞のみ観測」とし、
停滞警戒単独の縮退発火（DEGRADED_COMBINED_TRIGGER 警告付き）の経路をカバーする。
急増との組合せ発火は single-route-surge が受け持つ。

想定ケース: hallA から出口へ抜ける流出動線 `e_hallA_j2`（ライン計測なし）が停滞する。
出口行き需要（in→out。最短路は hallA 経由）がこのエッジを通るため、期待する提案は
出口行きを hallB 経由（e_j1_hallB→e_hallB_j2）へ逃がす配分となる。

既知の制約: 混在ホールを通過する OD は滞在/通過の帰属が観測上曖昧なため、現行
Forecasting は in→out 需要を hallA の滞在として吸収し、発火エッジに流量・重要度が
付かない（提案が発火箇所に触れない）。エンジン制約ドキュメント
（docs/engine_constraints_20260720.md）の E2 を参照。
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


@register("high-stagnation")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_hallA_j2")})
    # 急増なし（縮退発火のみ）。出口行き 18 がホットエッジを通過する
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("out"), 18.0),
            ODSpec(NodeID("in"), NodeID("hallA"), 12.0),
            ODSpec(NodeID("in"), NodeID("hallB"), 9.0),
        ),
        stagnation_edges=hot,
        lineless_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "high-stagnation",
        "ラインなしの e_hallA_j2 が p90 以上かつ移動平均差 beta 以上で M 分継続し縮退発火",
        built,
        obs,
        hist,
        # M 分継続を満たすため、前サイクルで両条件成立・計時開始済みの watch を与える
        previous_state=established_watch_state(hot),
    )
