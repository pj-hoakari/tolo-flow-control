"""expo: 入口コリドー過密 → 入場の一時停止（境界制御）シナリオ

唯一の入口アクセス路 `e_gate_lobby` が危険なほど混雑（危険フラグ）。入退出点 `gate` に
隣接し、gate には流入需要（入場）しかないため、境界制御は需要方向に従い
入場の一時停止（PAUSE_INGRESS）のみを提案する。流出需要が無く gate が唯一の
境界でもあるため、退出停止（PAUSE_EGRESS）は提案されない（排出は塞がない）。
群衆安全の最も分かりやすい出力。
"""

from __future__ import annotations

from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import NodeID

from ..scenario_base import DEFAULT_TIME, ODSpec, Scenario
from ._expo import make_expo_scenario
from ._registry import register


@register("expo-gate-overcrowded")
def build() -> Scenario:
    gate = NodeID("gate")
    return make_expo_scenario(
        "expo-gate-overcrowded",
        "入口アクセス路 e_gate_lobby が過密（危険フラグ）。gate で入場の一時停止を提案",
        od_flows=(
            ODSpec(gate, NodeID("hallA"), 20.0),
            ODSpec(gate, NodeID("hallB"), 15.0),
            ODSpec(gate, NodeID("hallD"), 10.0),
        ),
        edge_danger=("e_gate_lobby", 100.0),
        events=(
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id="edge:e_gate_lobby",
                occurred_at=DEFAULT_TIME,
            ),
        ),
    )
