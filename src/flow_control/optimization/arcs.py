from collections import defaultdict
from dataclasses import dataclass

from ..domain.enums import CurrentDirection, DirectionConstraint, FlowDirection
from ..domain.graph import Edge, EdgeID, Graph, NodeID


@dataclass(frozen=True)
class Arc:
    """エッジを向き付けした有向アーク。エッジ 1 本につき A→B と B→A の 2 本"""

    edge_id: EdgeID
    direction: FlowDirection
    tail: NodeID  # このアークの始点
    head: NodeID  # このアークの終点

    @property
    def key(self) -> str:
        return f"{self.edge_id.value}|{self.direction.value}"


# 方向制約から (A→B, B→A) それぞれの「許容フラグ α」と「法規制固定フラグ β」を導く
# α=1: その向きを有効化してよい / β=1: その向きの有効・無効が固定されている（x=α を強制）
_ALPHA_BETA: dict[DirectionConstraint, tuple[tuple[int, int], tuple[int, int]]] = {
    # PRIOR 系は既定の向きを示すだけで、最適化が両向きを選べる
    DirectionConstraint.BIDIRECTIONAL_PRIOR: ((1, 1), (0, 0)),
    DirectionConstraint.ONEWAY_A_TO_B_PRIOR: ((1, 1), (0, 0)),
    DirectionConstraint.ONEWAY_B_TO_A_PRIOR: ((1, 1), (0, 0)),
    # LEGAL_FIXED は法規制等で固定。許容外の向きは無効に固定される
    DirectionConstraint.LEGAL_FIXED_A_TO_B: ((1, 0), (1, 1)),
    DirectionConstraint.LEGAL_FIXED_B_TO_A: ((0, 1), (1, 1)),
    DirectionConstraint.LEGAL_FIXED_BIDIRECTIONAL: ((1, 1), (1, 1)),
}


@dataclass(frozen=True)
class ArcModel:
    arcs: tuple[Arc, ...]
    alpha: dict[str, int]  # arc.key -> α_a
    beta: dict[str, int]  # arc.key -> β_a
    arcs_of_edge: dict[EdgeID, tuple[Arc, ...]]
    out_arcs: dict[NodeID, tuple[Arc, ...]]  # δ⁺(v): tail=v のアーク
    in_arcs: dict[NodeID, tuple[Arc, ...]]  # δ⁻(v): head=v のアーク
    active_nodes: tuple[NodeID, ...]
    active_edges: tuple[Edge, ...]
    entry_nodes: tuple[NodeID, ...]  # is_boundary かつ enabled

    def arcs_in(self, node: NodeID) -> tuple[Arc, ...]:
        return self.in_arcs.get(node, ())

    def arcs_out(self, node: NodeID) -> tuple[Arc, ...]:
        return self.out_arcs.get(node, ())


def build_arc_model(graph: Graph) -> ArcModel:
    """グラフから有向アークモデルを構築する

    端点ノードが無効なエッジは除外する
    アーク・ノードの並びは ``Graph`` の定義順に従い決定的
    """
    enabled_node_ids = {node.node_id for node in graph.enabled_nodes()}

    arcs: list[Arc] = []
    alpha: dict[str, int] = {}
    beta: dict[str, int] = {}
    arcs_of_edge: dict[EdgeID, tuple[Arc, ...]] = {}
    out_arcs: dict[NodeID, list[Arc]] = defaultdict(list)
    in_arcs: dict[NodeID, list[Arc]] = defaultdict(list)
    active_edges: list[Edge] = []

    for edge in graph.enabled_edges():
        a, b = edge.endpoint_a, edge.endpoint_b
        if a not in enabled_node_ids or b not in enabled_node_ids:
            continue
        active_edges.append(edge)

        arc_ab = Arc(edge.edge_id, FlowDirection.A_TO_B, tail=a, head=b)
        arc_ba = Arc(edge.edge_id, FlowDirection.B_TO_A, tail=b, head=a)
        (alpha_ab, alpha_ba), (beta_ab, beta_ba) = _ALPHA_BETA[edge.direction_constraint]
        alpha[arc_ab.key] = alpha_ab
        alpha[arc_ba.key] = alpha_ba
        beta[arc_ab.key] = beta_ab
        beta[arc_ba.key] = beta_ba

        arcs.append(arc_ab)
        arcs.append(arc_ba)
        arcs_of_edge[edge.edge_id] = (arc_ab, arc_ba)
        out_arcs[a].append(arc_ab)
        in_arcs[b].append(arc_ab)
        out_arcs[b].append(arc_ba)
        in_arcs[a].append(arc_ba)

    active_nodes = tuple(n.node_id for n in graph.enabled_nodes())
    entry_nodes = tuple(n.node_id for n in graph.boundary_nodes())

    return ArcModel(
        arcs=tuple(arcs),
        alpha=alpha,
        beta=beta,
        arcs_of_edge=arcs_of_edge,
        out_arcs={k: tuple(v) for k, v in out_arcs.items()},
        in_arcs={k: tuple(v) for k, v in in_arcs.items()},
        active_nodes=active_nodes,
        active_edges=tuple(active_edges),
        entry_nodes=entry_nodes,
    )


def fixed_directions(edge: Edge) -> dict[str, int]:
    """``current_direction`` から各アークの有効/無効（x 固定値）を返す（フォールバック LP 用）"""
    a, b = edge.endpoint_a, edge.endpoint_b
    arc_ab = Arc(edge.edge_id, FlowDirection.A_TO_B, tail=a, head=b)
    arc_ba = Arc(edge.edge_id, FlowDirection.B_TO_A, tail=b, head=a)
    cd = edge.current_direction
    if cd == CurrentDirection.A_TO_B:
        return {arc_ab.key: 1, arc_ba.key: 0}
    if cd == CurrentDirection.B_TO_A:
        return {arc_ab.key: 0, arc_ba.key: 1}
    return {arc_ab.key: 1, arc_ba.key: 1}
