"""MILP 解から重要度スコア・方向属性提案を導く後処理"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..detour_routing import DetourPath, DetourResult
from ..domain.enums import CurrentDirection, DirectionConstraint
from ..domain.graph import Edge, EdgeID, NodeID
from .arcs import Arc, ArcModel
from .model import ArcSolution
from .results import (
    DetourPathProposal,
    DirectionChangeType,
    DirectionProposal,
    ImportanceDirection,
    ProposedDirection,
    RouteImportance,
)


def compute_route_importance(
    arc_model: ArcModel,
    solution: ArcSolution,
    epsilon_0: float,
    detour_emphasis: Mapping[str, float] | None = None,
) -> tuple[RouteImportance, ...]:
    """各エッジの重要度 w = f_e / (max f_e' + ε0) を算出する

    向きはエッジ上で支配的なフロー方向を示す（両方向ゼロなら NONE）
    ``detour_emphasis``（アーク key → 加算フロー）が与えられた場合は
    迂回候補加重を合成した値で正規化・支配方向判定を行う
    """
    emphasis: Mapping[str, float] = detour_emphasis or {}

    edge_flow: dict[str, float] = {}
    for edge in arc_model.active_edges:
        arc_ab, arc_ba = arc_model.arcs_of_edge[edge.edge_id]
        edge_flow[edge.edge_id.value] = (
            solution.flow.get(arc_ab.key, 0.0)
            + solution.flow.get(arc_ba.key, 0.0)
            + emphasis.get(arc_ab.key, 0.0)
            + emphasis.get(arc_ba.key, 0.0)
        )
    max_flow = max(edge_flow.values(), default=0.0)
    denom = max_flow + epsilon_0

    result: list[RouteImportance] = []
    for edge in arc_model.active_edges:
        arc_ab, arc_ba = arc_model.arcs_of_edge[edge.edge_id]
        flow_ab = solution.flow.get(arc_ab.key, 0.0) + emphasis.get(arc_ab.key, 0.0)
        flow_ba = solution.flow.get(arc_ba.key, 0.0) + emphasis.get(arc_ba.key, 0.0)
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


_NO_TRIGGERED_EDGES: frozenset[EdgeID] = frozenset()


@dataclass(frozen=True)
class DetourEmphasis:
    """迂回候補加重の結果

    ``arc_bonus`` は重要度合成用のアーク key → 加算フロー。
    ``assigned_paths`` は割当が付いた (起点エッジ, 候補パス, 割当量) の列で、
    採用迂回パス出力（detour_paths）の導出に使う
    """

    arc_bonus: dict[str, float] = field(default_factory=dict)
    assigned_paths: tuple[tuple[EdgeID, DetourPath, float], ...] = ()


def compute_detour_emphasis(
    arc_model: ArcModel,
    detour_result: DetourResult,
    observed_edge_flow: Mapping[EdgeID, float],
    solution: ArcSolution,
    weight: float,
    *,
    adopted_direction: Mapping[str, int],
    triggered_edges: frozenset[EdgeID] = _NO_TRIGGERED_EDGES,
) -> DetourEmphasis:
    """迂回候補パスへの誘導強調量を求める

    トリガー起点エッジの現況流量（解フローと観測フローの大きい方）を、
    非直行の候補パスへ逆距離重みで配分し、パス残容量でクリップする。
    誘導できない候補は除外する: 他のトリガーエッジを通るパス（迂回先も
    混雑しており、そこへの誘導は混雑の付け替えになる）と、採用方向で
    無効化されたアークを逆走するパス（方向提案と矛盾する誘導になる）。
    結果は重要度出力の合成にのみ使い、フロー解・τ・方向提案・
    通行制限・境界制御には影響させない
    """
    if weight <= 0.0:
        return DetourEmphasis()
    edge_by_id = {e.edge_id: e for e in arc_model.active_edges}
    trigger_set = triggered_edges | frozenset(ds.origin_edge for ds in detour_result.detour_sets)

    def edge_flow(edge_id: EdgeID) -> float:
        arcs = arc_model.arcs_of_edge.get(edge_id, ())
        return sum(solution.flow.get(a.key, 0.0) for a in arcs)

    bonus: dict[str, float] = {}
    assigned_paths: list[tuple[EdgeID, DetourPath, float]] = []
    for detour_set in detour_result.detour_sets:
        if detour_set.origin_edge not in edge_by_id:
            continue
        redirect = max(
            edge_flow(detour_set.origin_edge),
            observed_edge_flow.get(detour_set.origin_edge, 0.0),
        )
        if redirect <= 0.0:
            continue

        candidates: list[tuple[DetourPath, tuple[Arc, ...], float]] = []
        for path in detour_set.paths:
            if path.contains_trigger:
                continue
            if any(edge_id in trigger_set for edge_id in path.edge_ids):
                continue
            arcs = _walk_path_arcs(arc_model, edge_by_id, detour_set.endpoint_pair, path)
            if arcs is None:
                continue
            if any(adopted_direction.get(a.key, 0) != 1 for a in arcs):
                continue
            length = path.total_length if path.total_length > 0.0 else 1.0
            candidates.append((path, arcs, 1.0 / length))
        if not candidates:
            continue

        total_weight = sum(w for _, _, w in candidates)
        for path, arcs, path_weight in candidates:
            share = redirect * (path_weight / total_weight)
            residual = min(
                max(0.0, _effective_capacity(edge_by_id[a.edge_id]) - edge_flow(a.edge_id))
                for a in arcs
            )
            assigned = min(share, residual)
            if assigned <= 0.0:
                continue
            assigned_paths.append((detour_set.origin_edge, path, assigned))
            for arc in arcs:
                bonus[arc.key] = bonus.get(arc.key, 0.0) + weight * assigned
    return DetourEmphasis(arc_bonus=bonus, assigned_paths=tuple(assigned_paths))


_FLOW_CARRIED_EPS = 1e-9


def compute_detour_path_proposals(
    arc_model: ArcModel,
    detour_result: DetourResult,
    solution: ArcSolution,
    emphasis: DetourEmphasis,
    edge_confidence: Mapping[EdgeID, float],
) -> tuple[DetourPathProposal, ...]:
    """採用迂回パス（パス単位の任意出力）を導出する

    重要度と同一の解から、全構成エッジにフローが乗った迂回路と、
    迂回候補加重が割当を行った迂回路を採用として列挙する。
    信頼度は構成エッジの信頼度重み（node_confidence 由来・下限クリップ付き）の最小値
    """
    edge_ids_active = {e.edge_id for e in arc_model.active_edges}

    def edge_flow(edge_id: EdgeID) -> float:
        arcs = arc_model.arcs_of_edge.get(edge_id, ())
        return sum(solution.flow.get(a.key, 0.0) for a in arcs)

    assigned = {(origin, path) for origin, path, _ in emphasis.assigned_paths}

    proposals: list[DetourPathProposal] = []
    for detour_set in detour_result.detour_sets:
        for path in detour_set.paths:
            if path.contains_trigger:
                continue
            if any(edge_id not in edge_ids_active for edge_id in path.edge_ids):
                continue
            flow_carried = all(edge_flow(edge_id) > _FLOW_CARRIED_EPS for edge_id in path.edge_ids)
            if not flow_carried and (detour_set.origin_edge, path) not in assigned:
                continue
            proposals.append(
                DetourPathProposal(
                    origin_edge_id=detour_set.origin_edge,
                    edge_ids=path.edge_ids,
                    confidence=min(
                        (edge_confidence.get(eid, 1.0) for eid in path.edge_ids),
                        default=1.0,
                    ),
                )
            )
    return tuple(proposals)


def _effective_capacity(edge: Edge) -> float:
    caps: list[float] = []
    if edge.danger_flag and edge.danger_capacity is not None:
        caps.append(edge.danger_capacity)
    if edge.capacity_hint is not None:
        caps.append(edge.capacity_hint)
    return min(caps) if caps else math.inf


def _walk_path_arcs(
    arc_model: ArcModel,
    edge_by_id: Mapping[EdgeID, Edge],
    endpoint_pair: tuple[NodeID, NodeID],
    path: DetourPath,
) -> tuple[Arc, ...] | None:
    """パスを起点エッジの u→v 向きに辿り、通過方向のアーク列を返す

    構成エッジが有効集合に無い、または端点が連結しない場合は None
    """
    current, goal = endpoint_pair
    arcs: list[Arc] = []
    for edge_id in path.edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is None:
            return None
        if edge.endpoint_a == current:
            next_node = edge.endpoint_b
        elif edge.endpoint_b == current:
            next_node = edge.endpoint_a
        else:
            return None
        matched = next(
            (a for a in arc_model.arcs_of_edge.get(edge_id, ()) if a.tail == current),
            None,
        )
        if matched is None:
            return None
        arcs.append(matched)
        current = next_node
    if current != goal:
        return None
    return tuple(arcs)


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
            DirectionProposal(
                edge_id=edge.edge_id,
                proposed_direction=proposed,
                change_type=_change_type(
                    edge.current_direction, proposed, edge.direction_constraint
                ),
            )
        )
    return tuple(result)


def _change_type(
    current: CurrentDirection,
    proposed: ProposedDirection,
    constraint: DirectionConstraint,
) -> DirectionChangeType:
    current_proposed = {
        CurrentDirection.A_TO_B: ProposedDirection.A_TO_B,
        CurrentDirection.B_TO_A: ProposedDirection.B_TO_A,
        CurrentDirection.BIDIRECTIONAL: ProposedDirection.BIDIRECTIONAL,
    }[current]
    if current_proposed == proposed:
        return DirectionChangeType.KEEP
    if proposed == ProposedDirection.BIDIRECTIONAL:
        return (
            DirectionChangeType.RELEASE_ONEWAY
            if constraint == DirectionConstraint.BIDIRECTIONAL_PRIOR
            else DirectionChangeType.KEEP
        )
    if current == CurrentDirection.BIDIRECTIONAL:
        return DirectionChangeType.CONVERT_ONEWAY
    return DirectionChangeType.FLIP_ONEWAY
