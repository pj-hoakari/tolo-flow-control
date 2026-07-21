"""6 階建て校舎のシナリオ共通部品。"""

from __future__ import annotations

from flow_control.domain import EdgeID, NodeID

from .. import graph_builder
from ..scenario_base import ODSpec


def school_gathering_od_specs(*, staircase: str) -> tuple[ODSpec, ...]:
    """1〜5階にいる人と1階入口から、6階の集会へ向かう需要を返す。

    ``surge=True`` は1階ホールからの到着増を表す。2〜5階の在校者も明示的な
    生成源として含めるため、各階間階段の流量は上層に近づくほど累積する。
    """
    if staircase not in ("north", "south"):
        raise ValueError(f"unknown staircase: {staircase}")

    goal = NodeID("floor6_goal")

    def path_from_floor(floor: int, *, from_entrance: bool = False) -> tuple[EdgeID, ...]:
        edges: list[EdgeID] = []
        if from_entrance:
            edges.append(EdgeID("e_entrance_hall_f1"))
            floor = 1
        edges.append(EdgeID(f"e_hall_{staircase}_landing_f{floor}"))
        edges.extend(
            EdgeID(f"e_{staircase}_stairs_f{level}_{level + 1}")
            for level in range(floor, 6)
        )
        edges.extend(
            (EdgeID(f"e_hall_{staircase}_landing_f6"), EdgeID("e_hall_f6_goal"))
        )
        return tuple(edges)

    return (
        ODSpec(NodeID("entrance"), goal, 2.0, path=path_from_floor(1, from_entrance=True)),
        ODSpec(NodeID("elevator_hall_f1"), goal, 10.0, surge=True, path=path_from_floor(1)),
        ODSpec(NodeID("elevator_hall_f2"), goal, 3.0, path=path_from_floor(2)),
        ODSpec(NodeID("elevator_hall_f3"), goal, 2.0, path=path_from_floor(3)),
        ODSpec(NodeID("elevator_hall_f4"), goal, 2.0, path=path_from_floor(4)),
        ODSpec(NodeID("elevator_hall_f5"), goal, 1.0, path=path_from_floor(5)),
    )


def school_unobserved_edges() -> frozenset[EdgeID]:
    """各階間のエレベーター区間を未観測として返す。

    入口・6階ゴールに接する短いアークは、指定されたポイント観測のラインを表す。
    1〜5階の階段以外の移動（ホール―踊り場廊下・エレベーター）は観測せず通過のみ
    とする。
    """
    return frozenset(
        EdgeID(edge.edge_id.value)
        for edge in graph_builder.school().graph.edges
        if edge.edge_id.value.startswith(
            ("e_hall_north_landing_", "e_hall_south_landing_", "e_vertical_elevator_")
        )
    )

