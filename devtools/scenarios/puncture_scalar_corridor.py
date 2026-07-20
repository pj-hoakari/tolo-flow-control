"""パンクトリガー（スカラー観測コリドーの容量超過）シナリオ

スカラー型観測のエッジでは方向別フローが取れず停滞プロキシも弱いため、Detection は
「観測人数が容量ヒントの ρ 倍以上」を独立の前処理トリガー（パンク）として扱う。
本シナリオは venue の直結コリドー `e_j1_j2`（SCALAR・容量ヒント 50）へ容量超えの
通過需要（60）を流し、PunctureEvidence の発火と、パンク制約
（f_e <= max(0, C_e - σ_e)）が配分へ効く様子を確認する。

**スカラー区間は OD 推定の盲点である**という性質も同時に示す。当該コリドーを通る
60 は方向別フロー（VECTOR）に現れないため Forecasting からは見えず、保存補完で
別ルートへ帰属されて再現誤差が高くなる（0.86 前後）。この盲点を埋めるために
パンクトリガーが独立の前処理として存在する、という設計意図がそのまま観察できる。

パンクは `puncture_trigger_enabled=True` で有効化する（既定は無効＝ノーハーム）。
"""

from __future__ import annotations

from dataclasses import replace

from flow_control.domain import NodeID

from .. import graph_builder
from ..scenario_base import (
    ODSpec,
    Scenario,
    build_consistent_observations_and_history,
    compact_configs,
    make_scenario,
)
from ._registry import register


@register("puncture-scalar-corridor")
def build() -> Scenario:
    built = graph_builder.venue()
    base = compact_configs()
    configs = replace(
        base,
        detection=replace(
            base.detection,
            puncture_trigger_enabled=True,
            puncture_ratio_threshold=1.0,
        ),
    )
    # in→out の通過需要 60 は直結コリドー（容量 50）を超え、パンクが発火する。
    # SCALAR エッジも経路に使うため route_vector_only=False を指定する
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (
            ODSpec(NodeID("in"), NodeID("out"), 60.0),
            ODSpec(NodeID("in"), NodeID("hallA"), 10.0),
        ),
        eta=0.02,
        route_vector_only=False,
    )
    return make_scenario(
        "puncture-scalar-corridor",
        "スカラー観測の直結コリドー e_j1_j2 が容量ヒント超過。パンクトリガーが発火する",
        built,
        obs,
        hist,
        configs=configs,
    )
