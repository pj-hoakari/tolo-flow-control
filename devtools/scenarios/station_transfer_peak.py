"""乗換駅の通勤ピークで主連絡通路が混雑し、地下通路へ迂回誘導するケース

西改札から東側ホームへ向かう乗換流が朝ピークで急増し、コンコース間の
主連絡通路 `e_passage`（容量ヒント小）で組合せ発火する。並行する地下通路
`e_underpass` はセンサ未設置（観測のないルート）で、Forecasting の保存補完と
DetourRouting の列挙が疎観測下でも機能することを併せて確認する。

期待する提案は主連絡通路の重要度を下げ、地下通路へ流量を移す迂回配分
（乗換流 30 は通路容量 18 を超えるため、地下通路の併用が必須になる）。

既知の制約: ホーム間乗換（混在ノード plat1 起点の int→int OD）は現行 Forecasting の
Open モード生成源規則では導出されず、配分に反映されない。エンジン制約ドキュメントの
E1 を参照。
"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID, NodeKind

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
    b.node("gate_w", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("conc_w", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("conc_e", kind=NodeKind.TRANSIT_ONLY, pos=(3.5, 0.0))
    b.node("gate_e", kind=NodeKind.GOAL, boundary=True, pos=(5.0, 0.0))
    b.node("plat1", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(1.5, 1.6))
    b.node("plat2", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.5, 1.6))

    b.edge("e_gate_w", "gate_w", "conc_w", capacity_hint=100.0)
    b.edge("e_gate_e", "gate_e", "conc_e", capacity_hint=100.0)
    # 主連絡通路（容量小）と、センサ未設置の地下通路
    b.edge("e_passage", "conc_w", "conc_e", capacity_hint=18.0)
    b.edge("e_underpass", "conc_w", "conc_e", capacity_hint=40.0)
    b.edge("e_cw_p1", "conc_w", "plat1")
    b.edge("e_ce_p2", "conc_e", "plat2")
    return b


@register("station-transfer-peak")
def build() -> Scenario:
    built = _build_graph().build()
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
