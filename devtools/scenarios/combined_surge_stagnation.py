"""急増と高停滞が同一エッジで重なる組合せ発火シナリオ

現行の Detection は「停滞警戒が M 分継続」かつ「需要警戒（急増または需要超過）」の
両方が成立して初めてメトリクス発火する。急増のみ・停滞のみの既存シナリオは
発火しないため、組合せ条件を満たす下流実行のベースラインとして本シナリオを置く。
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


@register("combined-surge-stagnation")
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1")})
    obs, hist = build_observations_and_history(
        built.graph,
        surge_edges=hot,
        stagnation_edges=hot,
        # 混在ホールに滞留を与え、OD・信頼度が意味を持つようにする
        occupancy=30.0,
        occupancy_delta=10.0,
        # 単一アクセス通路がホール需要を運べるよう排出上限 eta*f<=s_obs を緩める
        eta=0.02,
    )
    return make_scenario(
        "combined-surge-stagnation",
        "e_in_j1 で急増と高停滞が同時成立し組合せ発火。下流 4 モジュールを通す",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
