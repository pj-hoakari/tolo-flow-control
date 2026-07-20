"""crossing: 一方通行バイパス循環 → 方向属性提案が映えるシナリオ

crossing と同位相だが、2 本のバイパスを LEGAL_FIXED の一方通行にする:
北バイパスは hub_w→hub_e（A_TO_B）、南バイパスは hub_e→hub_w（B_TO_A）の一方通行循環。
主通路 `e_main` とアクセスは双方向。期待する提案は、direction_proposal が一方通行バイパスを
A_TO_B / B_TO_A の有向、主通路・アクセスを BIDIRECTIONAL と提示し（有向/双方向の差が
一目で分かる）、迂回配分は現在方向で hub_e へ向かえる北バイパスにのみ乗ること。

（最適化は双方向 PRIOR エッジを自発的に一方通行化はしない＝方向提案が有向になるのは
LEGAL_FIXED の反映。本シナリオはその効果を明示する。）
"""

from __future__ import annotations

from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    EdgeID,
    NodeID,
    NodeKind,
)

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
    b.node("in", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("hub_w", kind=NodeKind.TRANSIT_ONLY, pos=(1.0, 0.0))
    b.node("hub_e", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.0))
    b.node("out", kind=NodeKind.GOAL, boundary=True, pos=(4.0, 0.0))
    b.node("n1", kind=NodeKind.TRANSIT_ONLY, pos=(2.0, 1.0))
    b.node("s1", kind=NodeKind.TRANSIT_ONLY, pos=(2.0, -1.0))

    b.edge("e_in", "in", "hub_w")
    b.edge("e_main", "hub_w", "hub_e", capacity_hint=10.0)
    # 北バイパス: 一方通行 hub_w→hub_e（A_TO_B）
    b.edge(
        "e_n1a", "hub_w", "n1",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    b.edge(
        "e_n1b", "n1", "hub_e",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    # 南バイパス: 一方通行 hub_e→hub_w（B_TO_A: endpoint_a 側が下流）
    b.edge(
        "e_s1a", "hub_w", "s1",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_B_TO_A,
        current_direction=CurrentDirection.B_TO_A,
    )
    b.edge(
        "e_s1b", "s1", "hub_e",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_B_TO_A,
        current_direction=CurrentDirection.B_TO_A,
    )
    b.edge("e_out", "hub_e", "out")
    return b


@register("crossing-oneway")
def build() -> Scenario:
    built = _build_graph().build()
    hot = frozenset({EdgeID("e_main")})
    # hub_e 行き 30 の急増が主通路（容量 10）に乗る
    obs, hist = build_consistent_observations_and_history(
        built.graph,
        (ODSpec(NodeID("in"), NodeID("hub_e"), 30.0, surge=True),),
        stagnation_edges=hot,
        eta=0.02,
    )
    return make_scenario(
        "crossing-oneway",
        "バイパスを一方通行循環（北 A_TO_B・南 B_TO_A）に。direction_proposal が有向/双方向を提案",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
