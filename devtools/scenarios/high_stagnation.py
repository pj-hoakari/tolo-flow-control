"""高停滞シナリオ（ラインなしエッジの縮退発火）

現行 Detection はライン観測のあるエッジでは停滞警戒単独で発火しない（需要警戒との
組合せが必要）。本シナリオはホットエッジを「ライン通過観測なし・停滞のみ観測」とし、
停滞警戒単独の縮退発火（DEGRADED_COMBINED_TRIGGER 警告付き）の経路をカバーする。
急増との組合せ発火は single-route-surge が受け持つ。

想定ケース: ホール A の催しが終わり、hallA から出口へ抜ける流出動線
`e_hallA_j2`（ライン計測なし）に退出流が集中して停滞する。放出中（ΔOcc<0）の
混在ノードは Open モードの生成源となるため、退出需要 hallA→out（int→ext）が
OD として導出され、発火エッジがその経路に乗る。期待する提案は発火エッジを含む
配分と残留 τ の報告。停滞エッジからの迂回振替は設計上行わない（排出モデルでは
フローが停滞を排出するため、振替は残留 τ を悪化させる）。

（設計上、境界→境界の通過需要 ext→ext は Open モードの対象外のため、
退出流の起点は境界ではなくホール＝混在ノードで表す。）
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
    # 急増なし（縮退発火のみ）。hallA からの退出 18 がホットエッジを通る
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("hallA"), NodeID("out"), 18.0),
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
