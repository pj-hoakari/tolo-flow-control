"""expo: 入口コリドー過密 → 入退場の一時停止（境界制御）シナリオ

唯一の入口アクセス路 `e_gate_lobby` が危険なほど混雑（危険フラグ）。入退出点 `gate` に
隣接するため、最適化は `gate` での入場・退出の一時停止（PAUSE_INGRESS / PAUSE_EGRESS）を提案する。
群衆安全の最も分かりやすい出力。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind

from ..scenario_base import DEFAULT_TIME, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-gate-overcrowded")
def build() -> Scenario:
    return make_expo_scenario(
        "expo-gate-overcrowded",
        "入口アクセス路 e_gate_lobby が過密（危険フラグ）。gate で入退場の一時停止を提案",
        edge_danger=("e_gate_lobby", 100.0),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_gate_lobby",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
