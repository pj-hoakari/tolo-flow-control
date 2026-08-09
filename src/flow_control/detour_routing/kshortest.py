from dataclasses import dataclass

import networkx as nx

from ..domain.graph import EdgeID, NodeID
from .traversal import DirectedArc

Adjacency = dict[NodeID, tuple[DirectedArc, ...]]
type _RouteNode = NodeID | tuple[str, str, str, str]


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

    graph, arc_of = _build_digraph(adjacency)
    if not graph.has_node(source) or not graph.has_node(target):
        return []

    paths: list[WeightedPath] = []
    try:
        for node_path in nx.shortest_simple_paths(graph, source, target, weight="weight"):
            paths.append(_to_weighted_path(arc_of, node_path))
            if len(paths) >= k:
                break
    except nx.NetworkXNoPath:
        return []
    return paths


def _build_digraph(
    adjacency: Adjacency,
) -> tuple["nx.DiGraph[_RouteNode]", dict[_RouteNode, DirectedArc]]:
    """有向アークを仮想ノードへ展開して、並行エッジも独立経路として保持する。"""
    graph: nx.DiGraph[_RouteNode] = nx.DiGraph()
    arc_of: dict[_RouteNode, DirectedArc] = {}
    for node in sorted(adjacency, key=lambda node_id: node_id.value):
        arcs = adjacency[node]
        graph.add_node(node)
        for arc in sorted(
            arcs, key=lambda item: (item.weight, item.edge_id.value, item.to_node.value)
        ):
            virtual: _RouteNode = (
                "__detour_arc__",
                node.value,
                arc.edge_id.value,
                arc.to_node.value,
            )
            _ = graph.add_edge(node, virtual, weight=arc.weight)
            _ = graph.add_edge(virtual, arc.to_node, weight=0.0)
            arc_of[virtual] = arc
    return graph, arc_of


def _to_weighted_path(
    arc_of: dict[_RouteNode, DirectedArc], node_path: list[_RouteNode]
) -> WeightedPath:
    # 仮想ノード列を、実ノード列・エッジ列へ戻す。
    assert isinstance(node_path[0], NodeID)
    edge_ids: list[EdgeID] = []
    nodes: list[NodeID] = [node_path[0]]
    total_length = 0.0
    for node in node_path:
        arc = arc_of.get(node)
        if arc is None:
            continue
        edge_ids.append(arc.edge_id)
        nodes.append(arc.to_node)
        total_length += arc.weight
    return WeightedPath(
        nodes=tuple(nodes),
        edge_ids=tuple(edge_ids),
        total_length=total_length,
    )
