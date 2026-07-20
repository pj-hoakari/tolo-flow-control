"""INFEASIBLE→方向固定 LP フォールバックシナリオ

葉ノード dead の唯一のエッジが LEGAL_FIXED で内向き固定の ``oneway-leaf``
プリセットを使う。出方向可達性 out>=1 が 0>=1 となり Phase1 INFEASIBLE、
方向固定 LP フォールバックへ落ちる。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind

from .. import graph_builder
from ..scenario_base import (
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    make_scenario,
)
from ._registry import register


@register("infeasible-fallback")
def build() -> Scenario:
    built = graph_builder.oneway_leaf()
    obs, hist = build_observations_and_history(built.graph)
    return make_scenario(
        "infeasible-fallback",
        "法規制固定が可達性を破り Phase1 INFEASIBLE→方向固定 LP フォールバック",
        built,
        obs,
        hist,
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e1",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
