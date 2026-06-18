from collections import defaultdict, deque
from dataclasses import dataclass

from ..domain.graph import EdgeID, NodeID
from .arcs import ArcModel


@dataclass(frozen=True)
class DrainableResult:
    drainable: frozenset[EdgeID]  # E_drain
    undrainable: frozenset[EdgeID]  # 停滞観測ありだが排出不能なエッジ


def reachable_forward(
    adjacency: dict[NodeID, list[NodeID]], source: NodeID
) -> set[NodeID]:
    seen: set[NodeID] = {source}
    queue: deque[NodeID] = deque((source,))
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def compute_drainable(
    arc_model: ArcModel,
    od_pairs: tuple[tuple[NodeID, NodeID], ...],
    stagnation_edges: frozenset[EdgeID],
) -> DrainableResult:
    """排出可能エッジ集合 E_drain を求める

    事前制約上許容される向き（α=1）のアークだけからなる有向グラフ上で、
    各 OD ペア (s,t) について「s から到達できるノード」「t へ到達できるノード」を計算
    停滞観測のあるエッジのうち、いずれかの向きのアークが
    （始点が s 到達集合・終点が t 到達集合に含まれ）s→t パスに乗り得るものを E_drain とする
    停滞観測がありながら E_drain に入らないエッジは排出不能として報告する
    """
    # α=1 のアークのみで前向き・後ろ向き隣接を構築
    forward: dict[NodeID, list[NodeID]] = defaultdict(list)
    backward: dict[NodeID, list[NodeID]] = defaultdict(list)
    for arc in arc_model.arcs:
        if arc_model.alpha.get(arc.key, 0) != 1:
            continue
        forward[arc.tail].append(arc.head)
        backward[arc.head].append(arc.tail)

    # OD ペアごとの到達集合（始点・終点でメモ化）
    reach_from: dict[NodeID, set[NodeID]] = {}
    reach_to: dict[NodeID, set[NodeID]] = {}
    for source, target in od_pairs:
        if source not in reach_from:
            reach_from[source] = reachable_forward(forward, source)
        if target not in reach_to:
            reach_to[target] = reachable_forward(backward, target)

    drainable: set[EdgeID] = set()
    for edge in arc_model.active_edges:
        if edge.edge_id not in stagnation_edges:
            continue
        arcs = arc_model.arcs_of_edge.get(edge.edge_id, ())
        on_some_path = False
        for source, target in od_pairs:
            rf = reach_from[source]
            rt = reach_to[target]
            for arc in arcs:
                if arc_model.alpha.get(arc.key, 0) != 1:
                    continue
                if arc.tail in rf and arc.head in rt:
                    on_some_path = True
                    break
            if on_some_path:
                break
        if on_some_path:
            drainable.add(edge.edge_id)

    undrainable = stagnation_edges - drainable
    return DrainableResult(
        drainable=frozenset(drainable), undrainable=frozenset(undrainable)
    )
