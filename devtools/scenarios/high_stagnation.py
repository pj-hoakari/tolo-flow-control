"""高停滞シナリオ（ラインなしエッジの縮退発火）

現行 Detection はライン観測のあるエッジでは停滞警戒単独で発火しない（需要警戒との
組合せが必要）。本シナリオはホットエッジを「ライン通過観測なし・停滞のみ観測」とし、
停滞警戒単独の縮退発火（DEGRADED_COMBINED_TRIGGER 警告付き）の経路をカバーする。
急増との組合せ発火は combined-surge-stagnation が受け持つ。
"""

from __future__ import annotations

from flow_control.domain import EdgeID

from .. import graph_builder
from ..scenario_base import (
    Scenario,
    build_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


@register("high-stagnation")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_hallA_j2")})
    obs, hist = build_observations_and_history(
        built.graph,
        stagnation_edges=hot,
        lineless_edges=hot,
        occupancy=30.0,
        occupancy_delta=10.0,
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
