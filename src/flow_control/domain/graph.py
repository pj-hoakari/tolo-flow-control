"""Graph domain model"""

from dataclasses import dataclass, field

from .enums import (
    BoundaryDirection,
    CurrentDirection,
    DirectionConstraint,
    NodeKind,
    ObservationType,
)


@dataclass(frozen=True)
class NodeID:
    value: str


@dataclass(frozen=True)
class EdgeID:
    value: str


@dataclass(frozen=True)
class Boundary:
    direction: BoundaryDirection
    active: bool


@dataclass(frozen=True)
class Node:
    node_id: NodeID
    kind: NodeKind
    enabled: bool
    boundary: Boundary | None = None
    attribute_tags: tuple[str, ...] = ()
    time_resolution_s: int = 60
    danger_flag: bool = False
    danger_capacity: float | None = None

    @property
    def has_active_boundary(self) -> bool:
        return self.boundary is not None and self.boundary.active

    @property
    def admits_entry(self) -> bool:
        return (
            self.boundary is not None
            and self.boundary.active
            and self.boundary.direction.admits_entry
        )

    @property
    def admits_exit(self) -> bool:
        return (
            self.boundary is not None
            and self.boundary.active
            and self.boundary.direction.admits_exit
        )


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
        Only enabled nodes with an active ``boundary`` are included in the set of entry/exit points
        """
        return tuple(n for n in self.nodes if n.has_active_boundary and n.enabled)

    def entry_nodes(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.admits_entry and n.enabled)

    def exit_nodes(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.admits_exit and n.enabled)
