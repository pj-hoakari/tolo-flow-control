"""境界制御提案の生成（決定的ヒューリスティック）

危険フラグが境界ノードに隣接または一致するとき、需要方向に応じて入場・退出の
一時停止を提案する:

- PAUSE_INGRESS: 当該境界に流入需要（OD の起点）があるとき。新規入場は危険箇所
  近傍への負荷を追加するため、入場の一時停止が危険箇所を保護する
- PAUSE_EGRESS: 当該境界に流出需要（OD の終点）があり、かつ代替の退出境界が
  存在するときのみ。唯一の排出口を塞ぐと場内に滞留を閉じ込め危険を悪化させる
- 需要情報が無い場合は予防的に PAUSE_INGRESS のみ（排出を塞ぐ判断は需要の
  裏付けなしには行わない）

危険フラグ解除後の最初の最適化で過去に停止した境界ノードへ再開を提案する。
最適化解とは独立の後処理で、Open モードのみで生成する。
"""

from collections.abc import Sequence

from ..domain.graph import Graph, Node, NodeID
from .model import Commodity
from .results import BoundaryAction, BoundaryControl, OptimizationResult


def _boundary_demands(
    commodities: Sequence[Commodity],
    boundary_ids: set[NodeID],
) -> tuple[dict[NodeID, float], dict[NodeID, float]]:
    """境界ノードごとの流入需要（起点）・流出需要（終点）を集計する"""
    inflow: dict[NodeID, float] = {}
    outflow: dict[NodeID, float] = {}
    for k in commodities:
        if k.origin in boundary_ids and k.demand > 0.0:
            inflow[k.origin] = inflow.get(k.origin, 0.0) + k.demand
        if k.destination in boundary_ids and k.demand > 0.0:
            outflow[k.destination] = outflow.get(k.destination, 0.0) + k.demand
    return inflow, outflow


def compute_boundary_control(
    graph: Graph,
    is_open: bool,
    previous_result: OptimizationResult | None,
    commodities: Sequence[Commodity] = (),
) -> tuple[BoundaryControl, ...]:
    if not is_open:
        return ()

    boundary_ids = {n.node_id for n in graph.boundary_nodes()}
    if not boundary_ids:
        return ()

    node_by_id: dict[NodeID, Node] = {n.node_id: n for n in graph.nodes}
    inflow, outflow = _boundary_demands(commodities, boundary_ids)
    has_alternate_exit = len(boundary_ids) > 1

    # 危険要素に隣接・一致する境界ノードと、その危険要素の表示名を集める
    danger_near: dict[NodeID, str] = {}

    def note_danger(node: NodeID, label: str) -> None:
        if node not in danger_near:
            danger_near[node] = label

    for edge in graph.enabled_edges():
        if not edge.danger_flag:
            continue
        for endpoint in (edge.endpoint_a, edge.endpoint_b):
            if endpoint in boundary_ids:
                note_danger(endpoint, f"danger edge {edge.edge_id.value}")

    for node in graph.enabled_nodes():
        if not node.danger_flag:
            continue
        if node.node_id in boundary_ids:
            note_danger(node.node_id, f"danger node {node.node_id.value}")
            continue
        for edge in graph.enabled_edges():
            if node.node_id not in (edge.endpoint_a, edge.endpoint_b):
                continue
            other = (
                edge.endpoint_b if edge.endpoint_a == node.node_id else edge.endpoint_a
            )
            if other in boundary_ids:
                note_danger(other, f"danger node {node.node_id.value}")

    result: list[BoundaryControl] = []
    paused_now: set[NodeID] = set()
    for node in graph.nodes:
        label = danger_near.get(node.node_id)
        if label is None:
            continue
        node_in = inflow.get(node.node_id, 0.0)
        node_out = outflow.get(node.node_id, 0.0)
        if node_in > 0.0:
            result.append(
                BoundaryControl(
                    node_id=node.node_id,
                    action=BoundaryAction.PAUSE_INGRESS,
                    reason=(
                        f"inbound demand at {node.node_id.value} adds load near "
                        f"{label}; pause new entries to protect it"
                    ),
                )
            )
            paused_now.add(node.node_id)
        if node_out > 0.0 and has_alternate_exit:
            result.append(
                BoundaryControl(
                    node_id=node.node_id,
                    action=BoundaryAction.PAUSE_EGRESS,
                    reason=(
                        f"exit flows converge toward {label} at "
                        f"{node.node_id.value}; alternate exits are available"
                    ),
                )
            )
            paused_now.add(node.node_id)
        if node_in <= 0.0 and node_out <= 0.0:
            # 需要情報なし: 予防的な入場停止のみ（排出は塞がない）
            result.append(
                BoundaryControl(
                    node_id=node.node_id,
                    action=BoundaryAction.PAUSE_INGRESS,
                    reason=(
                        f"no demand observed at {node.node_id.value}; "
                        f"precautionary ingress pause near {label}"
                    ),
                )
            )
            paused_now.add(node.node_id)

    # 危険フラグ解除後の再開提案: 前回 PAUSE した境界ノードのうち、今回 PAUSE がないもの
    if previous_result is not None:
        paused_before: set[NodeID] = {
            bc.node_id
            for bc in previous_result.boundary_control
            if bc.action in (BoundaryAction.PAUSE_INGRESS, BoundaryAction.PAUSE_EGRESS)
        }
        for node_id in paused_before:
            if node_id in paused_now:
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
