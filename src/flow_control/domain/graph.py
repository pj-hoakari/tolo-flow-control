"""Graph domain model"""

from dataclasses import dataclass, field

from .enums import CurrentDirection, DirectionConstraint, NodeKind, ObservationType


@dataclass(frozen=True)
class NodeID:
    value: str


@dataclass(frozen=True)
class EdgeID:
    value: str


@dataclass(frozen=True)
class Node:
    node_id: NodeID
    kind: NodeKind
    is_boundary: bool
    enabled: bool
    attribute_tags: tuple[str, ...] = ()
    time_resolution_s: int = 60
    danger_flag: bool = False
    danger_capacity: float | None = None


@dataclass(frozen=True)
class Edge:
    edge_id: EdgeID
    endpoint_a: NodeID
    endpoint_b: NodeID
    direction_constraint: DirectionConstraint
    current_direction: CurrentDirection
    enabled: bool
    observation_type: ObservationType
    attribute_tags: tuple[str, ...] = ()
    time_resolution_s: int = 60
    danger_flag: bool = False
    danger_capacity: float | None = None
    capacity_hint: float | None = None


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...] = field(default_factory=tuple)
    edges: tuple[Edge, ...] = field(default_factory=tuple)

    def node_of(self, node_id: NodeID) -> Node | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def edge_of(self, edge_id: EdgeID) -> Edge | None:
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        return None

    def enabled_nodes(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.enabled)

    def enabled_edges(self) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.enabled)

    def boundary_nodes(self) -> tuple[Node, ...]:
        """
        Only nodes that satisfy both ``is_boundary`` and ``enabled`` are included in the set of entry/exit points
        """
        return tuple(n for n in self.nodes if n.is_boundary and n.enabled)
