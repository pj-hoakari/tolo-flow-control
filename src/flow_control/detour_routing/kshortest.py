from dataclasses import dataclass

import networkx as nx

from ..domain.graph import EdgeID, NodeID
from .traversal import DirectedArc

Adjacency = dict[NodeID, tuple[DirectedArc, ...]]
# (始点, 終点) → 集約後の (edge_id, weight)
EdgeIndex = dict[tuple[NodeID, NodeID], tuple[EdgeID, float]]


@dataclass(frozen=True)
class WeightedPath:
    nodes: tuple[NodeID, ...]  # 通過ノード列（source 始点・target 終点）
    edge_ids: tuple[EdgeID, ...]  # 通過エッジ列（len = len(nodes) - 1）
    total_length: float


def k_shortest_paths(
    adjacency: Adjacency,
    source: NodeID,
    target: NodeID,
    k: int,
) -> list[WeightedPath]:
    # source→target の k-最短単純路を距離昇順で列挙（NetworkX shortest_simple_paths）
    # 取得本数は min(k, 実在数)。source==target / k<=0 / 到達不能は空
    if k <= 0 or source == target:
        return []

    graph, edge_of = _build_digraph(adjacency)
    if not graph.has_node(source) or not graph.has_node(target):
        return []

    paths: list[WeightedPath] = []
    try:
        for node_path in nx.shortest_simple_paths(
            graph, source, target, weight="weight"
        ):
            paths.append(_to_weighted_path(edge_of, node_path))
            if len(paths) >= k:
                break
    except nx.NetworkXNoPath:
        return []
    return paths


def _build_digraph(adjacency: Adjacency) -> tuple["nx.DiGraph[NodeID]", EdgeIndex]:
    # 有向隣接から DiGraph と (始点, 終点)→(edge_id, weight) 索引を構成
    # 並行エッジ（同一ノード対）は (weight, edge_id) 最小の 1 本へ集約
    graph: "nx.DiGraph[NodeID]" = nx.DiGraph()
    edge_of: EdgeIndex = {}
    for node, arcs in adjacency.items():
        graph.add_node(node)
        for arc in arcs:
            key = (node, arc.to_node)
            existing = edge_of.get(key)
            if existing is not None and (arc.weight, arc.edge_id.value) >= (
                existing[1],
                existing[0].value,
            ):
                continue
            _ = graph.add_edge(node, arc.to_node, weight=arc.weight)
            edge_of[key] = (arc.edge_id, arc.weight)
    return graph, edge_of


def _to_weighted_path(edge_of: EdgeIndex, node_path: list[NodeID]) -> WeightedPath:
    # ノード列を edge_id 列・総距離つきの WeightedPath に写す（重みは edge_of から取得）
    edge_ids: list[EdgeID] = []
    total_length = 0.0
    for current, nxt in zip(node_path, node_path[1:]):
        edge_id, weight = edge_of[(current, nxt)]
        edge_ids.append(edge_id)
        total_length += weight
    return WeightedPath(
        nodes=tuple(node_path),
        edge_ids=tuple(edge_ids),
        total_length=total_length,
    )
