"""境界制御提案の生成（決定的ヒューリスティック）

入退出点に隣接または一致する危険フラグに対して入場・退出の一時停止を提案
危険フラグ解除後の最初の最適化で過去に停止した境界ノードへ再開を提案
MILP の解とは独立
Open モードのみで生成
"""

from ..domain.enums import CurrentDirection
from ..domain.graph import Edge, Graph, Node, NodeID
from .results import BoundaryAction, BoundaryControl, OptimizationResult


def _flows_into(edge: Edge, node: NodeID) -> bool:
    # エッジが node へ流入する向きを持つか（node 向き、または双方向）
    cd = edge.current_direction
    if cd == CurrentDirection.BIDIRECTIONAL:
        return True
    if node == edge.endpoint_b:
        return cd == CurrentDirection.A_TO_B
    if node == edge.endpoint_a:
        return cd == CurrentDirection.B_TO_A
    return False


def _flows_out_of(edge: Edge, node: NodeID) -> bool:
    # エッジが node から流出する向きを持つか（node 発、または双方向）
    cd = edge.current_direction
    if cd == CurrentDirection.BIDIRECTIONAL:
        return True
    if node == edge.endpoint_a:
        return cd == CurrentDirection.A_TO_B
    if node == edge.endpoint_b:
        return cd == CurrentDirection.B_TO_A
    return False


def _add(
    pauses: dict[NodeID, set[BoundaryAction]],
    node: NodeID,
    action: BoundaryAction,
) -> None:
    pauses.setdefault(node, set()).add(action)


def compute_boundary_control(
    graph: Graph,
    is_open: bool,
    previous_result: OptimizationResult | None,
) -> tuple[BoundaryControl, ...]:
    if not is_open:
        return ()

    boundary_ids = {n.node_id for n in graph.boundary_nodes()}
    if not boundary_ids:
        return ()

    node_by_id: dict[NodeID, Node] = {n.node_id: n for n in graph.nodes}
    pauses: dict[NodeID, set[BoundaryAction]] = {}
    reasons: dict[tuple[NodeID, BoundaryAction], str] = {}

    def register(node: NodeID, action: BoundaryAction, reason: str) -> None:
        _add(pauses, node, action)
        if (node, action) not in reasons:
            reasons[(node, action)] = reason

    # 危険フラグの立ったエッジ
    for edge in graph.enabled_edges():
        if not edge.danger_flag:
            continue
        for endpoint in (edge.endpoint_a, edge.endpoint_b):
            if endpoint not in boundary_ids:
                continue
            reason = f"danger edge {edge.edge_id.value} adjacent to boundary"
            if _flows_into(edge, endpoint):
                register(endpoint, BoundaryAction.PAUSE_INGRESS, reason)
            if _flows_out_of(edge, endpoint):
                register(endpoint, BoundaryAction.PAUSE_EGRESS, reason)

    # 危険フラグの立ったノード
    for node in graph.enabled_nodes():
        if not node.danger_flag:
            continue
        if node.node_id in boundary_ids:
            reason = f"danger node {node.node_id.value} is boundary"
            register(node.node_id, BoundaryAction.PAUSE_INGRESS, reason)
            register(node.node_id, BoundaryAction.PAUSE_EGRESS, reason)
            continue
        # 隣接する境界ノードへ、接続エッジの向きに応じて適用
        for edge in graph.enabled_edges():
            if node.node_id not in (edge.endpoint_a, edge.endpoint_b):
                continue
            other = (
                edge.endpoint_b if edge.endpoint_a == node.node_id else edge.endpoint_a
            )
            if other not in boundary_ids:
                continue
            reason = f"danger node {node.node_id.value} adjacent to boundary"
            if _flows_into(edge, other):
                register(other, BoundaryAction.PAUSE_INGRESS, reason)
            if _flows_out_of(edge, other):
                register(other, BoundaryAction.PAUSE_EGRESS, reason)

    result: list[BoundaryControl] = []
    for node in graph.nodes:
        actions = pauses.get(node.node_id)
        if not actions:
            continue
        for action in (BoundaryAction.PAUSE_INGRESS, BoundaryAction.PAUSE_EGRESS):
            if action in actions:
                result.append(
                    BoundaryControl(
                        node_id=node.node_id,
                        action=action,
                        reason=reasons[(node.node_id, action)],
                    )
                )

    # 危険フラグ解除後の再開提案: 前回 PAUSE した境界ノードのうち、今回 PAUSE がないもの
    if previous_result is not None:
        paused_before: set[NodeID] = {
            bc.node_id
            for bc in previous_result.boundary_control
            if bc.action in (BoundaryAction.PAUSE_INGRESS, BoundaryAction.PAUSE_EGRESS)
        }
        for node_id in paused_before:
            if node_id in pauses:
                continue
            if node_id not in boundary_ids:
                continue
            if node_id not in node_by_id:
                continue
            result.append(
                BoundaryControl(
                    node_id=node_id,
                    action=BoundaryAction.RESUME,
                    reason="danger cleared",
                )
            )

    return tuple(result)
