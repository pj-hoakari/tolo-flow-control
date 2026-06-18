"""MILP 解から重要度スコア・方向属性提案を導く後処理"""

from .arcs import ArcModel
from .model import ArcSolution
from .results import (
    DirectionProposal,
    ImportanceDirection,
    ProposedDirection,
    RouteImportance,
)


def compute_route_importance(
    arc_model: ArcModel, solution: ArcSolution, epsilon_0: float
) -> tuple[RouteImportance, ...]:
    """各エッジの重要度 w = f_e / (max f_e' + ε0) を算出する

    向きはエッジ上で支配的なフロー方向を示す（両方向ゼロなら NONE）
    """
    edge_flow: dict[str, float] = {}
    for edge in arc_model.active_edges:
        arc_ab, arc_ba = arc_model.arcs_of_edge[edge.edge_id]
        edge_flow[edge.edge_id.value] = solution.flow.get(
            arc_ab.key, 0.0
        ) + solution.flow.get(arc_ba.key, 0.0)
    max_flow = max(edge_flow.values(), default=0.0)
    denom = max_flow + epsilon_0

    result: list[RouteImportance] = []
    for edge in arc_model.active_edges:
        arc_ab, arc_ba = arc_model.arcs_of_edge[edge.edge_id]
        flow_ab = solution.flow.get(arc_ab.key, 0.0)
        flow_ba = solution.flow.get(arc_ba.key, 0.0)
        importance = edge_flow[edge.edge_id.value] / denom

        if flow_ab == 0.0 and flow_ba == 0.0:
            direction = ImportanceDirection.NONE
        elif flow_ba > flow_ab:
            direction = ImportanceDirection.B_TO_A
        else:
            direction = ImportanceDirection.A_TO_B

        result.append(
            RouteImportance(
                edge_id=edge.edge_id,
                direction=direction,
                importance=importance,
            )
        )
    return tuple(result)


def compute_direction_proposals(
    arc_model: ArcModel, solution: ArcSolution
) -> tuple[DirectionProposal, ...]:
    """方向変数 x の組合せから各エッジの方向属性提案を導く"""
    result: list[DirectionProposal] = []
    for edge in arc_model.active_edges:
        arc_ab, arc_ba = arc_model.arcs_of_edge[edge.edge_id]
        active_ab = solution.direction.get(arc_ab.key, 0) == 1
        active_ba = solution.direction.get(arc_ba.key, 0) == 1
        if active_ab and active_ba:
            proposed = ProposedDirection.BIDIRECTIONAL
        elif active_ab:
            proposed = ProposedDirection.A_TO_B
        elif active_ba:
            proposed = ProposedDirection.B_TO_A
        else:
            # 両向き無効は完全閉鎖。提案対象から外す
            continue
        result.append(
            DirectionProposal(edge_id=edge.edge_id, proposed_direction=proposed)
        )
    return tuple(result)
