"""乗換駅の通勤ピークで主連絡通路が混雑し、地下通路へ迂回誘導するケース

グラフは ``transfer-station`` プリセット。西改札から東側ホームへ向かう乗換流が
朝ピークで急増し、コンコース間の主連絡通路 `e_passage`（容量ヒント小）で組合せ
発火する。並行する地下通路 `e_underpass` はセンサ未設置（観測のないルート）で、
Forecasting の保存補完と DetourRouting の列挙が疎観測下でも機能することを併せて
確認する。

期待する提案は主連絡通路の重要度を下げ、地下通路へ流量を移す迂回配分
（乗換流 30 は通路容量 18 を超えるため、地下通路の併用が必須になる）。

既知の制約: ホーム間乗換（混在ノード plat1 起点の int→int OD）は現行 Forecasting の
Open モード生成源規則では導出されず、配分に反映されない。エンジン制約ドキュメントの
E1 を参照。
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


@register("station-transfer-peak")
def build() -> Scenario:
    built = graph_builder.transfer_station()
    hot = frozenset({EdgeID("e_passage")})
    # 西改札→東ホームの乗換流が急増。ホーム間の乗換（int→int）と東改札の平常流も置く
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("gate_w"), NodeID("plat2"), 30.0, surge=True),
            ODSpec(NodeID("plat1"), NodeID("plat2"), 12.0),
            ODSpec(NodeID("gate_e"), NodeID("plat2"), 9.0),
        ),
        stagnation_edges=hot,
        unobserved_edges=frozenset({EdgeID("e_underpass")}),
        eta=0.03,
    )
    return make_scenario(
        "station-transfer-peak",
        "乗換ピークで主連絡通路が急増＋停滞。センサ未設置の地下通路へ迂回誘導する",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
