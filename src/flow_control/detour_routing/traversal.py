from collections import defaultdict
from dataclasses import dataclass

from ..domain.enums import DirectionConstraint
from ..domain.graph import EdgeID, Graph, NodeID

_NO_EXCLUDED_EDGES: frozenset[EdgeID] = frozenset()


@dataclass(frozen=True)
class DirectedArc:
    to_node: NodeID
    edge_id: EdgeID
    weight: float  # ホップ距離（各エッジ 1.0）


def feasible_directions(constraint: DirectionConstraint) -> tuple[bool, bool]:
    # (A→B 可, B→A 可) を返す（α_a 相当）
    # LEGAL_FIXED_* のみ当該方向に限定
    # PRIOR 系は最適化が方向を変えうるため両方向可
    if constraint == DirectionConstraint.LEGAL_FIXED_A_TO_B:
        return (True, False)
    if constraint == DirectionConstraint.LEGAL_FIXED_B_TO_A:
        return (False, True)
    return (True, True)


def build_adjacency(
    graph: Graph,
    *,
    excluded_edges: frozenset[EdgeID] = _NO_EXCLUDED_EDGES,
) -> dict[NodeID, tuple[DirectedArc, ...]]:
    # 方向制約を反映した有向隣接を構築
    # excluded_edges は起点アーク a* の一時除去 G\{a*} 用
    # 並びは Graph.edges 順で決定的
    enabled_node_ids = {node.node_id for node in graph.enabled_nodes()}
    out_arcs: dict[NodeID, list[DirectedArc]] = defaultdict(list)
    for edge in graph.enabled_edges():
        if edge.edge_id in excluded_edges:
            continue
        a, b = edge.endpoint_a, edge.endpoint_b
        # 端点ノードが無効なエッジは除外
        if a not in enabled_node_ids or b not in enabled_node_ids:
            continue
        a_to_b, b_to_a = feasible_directions(edge.direction_constraint)
        if a_to_b:
            out_arcs[a].append(DirectedArc(to_node=b, edge_id=edge.edge_id, weight=1.0))
        if b_to_a:
            out_arcs[b].append(DirectedArc(to_node=a, edge_id=edge.edge_id, weight=1.0))
    return {node_id: tuple(arcs) for node_id, arcs in out_arcs.items()}
