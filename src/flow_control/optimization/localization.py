"""トリガー起点の局所化（ゾーン抽出）

基本モードの求解規模をトリガー近傍に固定するための純関数群。ゾーンは
「トリガー要素の無向 h ホップ近傍（核）」を単位に構築し、核がノードを共有する
ゾーンは併合、散在時は重大度上位 M ゾーンへ決定的に打ち切る。併合後の各ゾーンへ
「各境界入退出点への最短経路上のノード」を付与する（境界への導線をゾーン内に含め、
ゾーン境界を所与の流入出条件として扱えるようにするため。最短経路は併合判定には
使わない — 判定に含めると Open モードでは全ゾーンが入退出点を介して常に 1 つへ
併合され、多ゾーン処理・打ち切りが機能しなくなる）。
ゾーン外を current・観測値に固定して解く段（ゾーン限定 LP）は optimizer 側の
責務で、本モジュールは抽出のみを行う。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.graph import EdgeID, NodeID
from .arcs import ArcModel

# ゾーン整列のタイブレーク末尾値（エッジを一切持たないゾーンを最後に回す）
_TIE_LAST = "￿"
# 重大度未指定時の空マップ
_NO_SEVERITY: Mapping[EdgeID, float] = {}


@dataclass(frozen=True)
class TriggerZone:
    """1 ゾーン分の部分グラフ（ノード・誘導エッジ）と発端トリガー"""

    seed_edges: tuple[EdgeID, ...]  # 発端トリガーエッジ（ID 昇順）
    seed_nodes: tuple[NodeID, ...]  # 発端トリガーノード（ID 昇順）
    nodes: tuple[NodeID, ...]  # ゾーンノード（核＋境界最短経路。ID 昇順）
    edges: tuple[EdgeID, ...]  # 両端がゾーン内にある有効エッジ（ID 昇順）
    severity: float


@dataclass(frozen=True)
class LocalizationResult:
    zones: tuple[TriggerZone, ...]  # 重大度降順・最小エッジ ID 昇順
    capped: bool  # 上限打ち切りが発生した（LOCALIZATION_CAPPED 相当）


def build_trigger_zones(
    arc_model: ArcModel,
    triggered_edges: tuple[EdgeID, ...],
    triggered_nodes: tuple[NodeID, ...],
    *,
    local_radius_hops: int,
    max_trigger_zones: int,
    edge_severity: Mapping[EdgeID, float] | None = None,
) -> LocalizationResult:
    """トリガー集合からゾーン群を構築する

    - 各トリガー要素の無向 ``local_radius_hops`` ホップ近傍をゾーン核とする
    - 核がノードを共有するゾーンは併合する
    - ゾーン数が ``max_trigger_zones`` を超えたら重大度上位のみ残し ``capped`` を立てる
    - 併合・打ち切り後、各ゾーンへ核から各境界入退出点への最短経路上のノードを加える
    - 重大度はトリガー要素に紐づくエッジの ``edge_severity`` 最大値
      （ノードトリガーは接続エッジで代表）。未指定・欠損は 0
    - 並び・併合順は ID 昇順で決定的
    """
    adjacency = _build_adjacency(arc_model)
    severity: Mapping[EdgeID, float] = edge_severity if edge_severity is not None else _NO_SEVERITY

    cores: list[_MutableZone] = []
    active_edge_ids = {edge.edge_id for edge in arc_model.active_edges}
    for edge_id in sorted(set(triggered_edges), key=lambda e: e.value):
        if edge_id not in active_edge_ids:
            continue
        arcs = arc_model.arcs_of_edge.get(edge_id, ())
        if not arcs:
            continue
        seeds = {arcs[0].tail, arcs[0].head}
        cores.append(
            _MutableZone(
                seed_edges={edge_id},
                seed_nodes=set(),
                nodes=_bfs_within(seeds, adjacency, local_radius_hops),
                severity=float(severity.get(edge_id, 0.0)),
            )
        )
    active_node_set = set(arc_model.active_nodes)
    for node_id in sorted(set(triggered_nodes), key=lambda n: n.value):
        if node_id not in active_node_set:
            continue
        incident = [a.edge_id for a in arc_model.arcs_out(node_id)]
        node_sev = max((float(severity.get(e, 0.0)) for e in incident), default=0.0)
        cores.append(
            _MutableZone(
                seed_edges=set(),
                seed_nodes={node_id},
                nodes=_bfs_within({node_id}, adjacency, local_radius_hops),
                severity=node_sev,
            )
        )

    merged = _merge_overlapping(cores)
    frozen = [_freeze(zone, arc_model, adjacency) for zone in merged]
    frozen.sort(key=lambda z: (-z.severity, _tie_key(z)))
    capped = len(frozen) > max_trigger_zones
    if capped:
        frozen = frozen[:max_trigger_zones]

    return LocalizationResult(zones=tuple(frozen), capped=capped)


@dataclass
class _MutableZone:
    seed_edges: set[EdgeID]
    seed_nodes: set[NodeID]
    nodes: set[NodeID]  # 核（h ホップ近傍）のみ
    severity: float


def _build_adjacency(arc_model: ArcModel) -> dict[NodeID, tuple[NodeID, ...]]:
    # 無向隣接（有効エッジのみ）。近傍は ID 昇順で決定的
    neighbors: dict[NodeID, set[NodeID]] = {}
    for edge in arc_model.active_edges:
        arcs = arc_model.arcs_of_edge.get(edge.edge_id, ())
        if not arcs:
            continue
        a, b = arcs[0].tail, arcs[0].head
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    return {v: tuple(sorted(ns, key=lambda n: n.value)) for v, ns in neighbors.items()}


def _bfs_within(
    seeds: set[NodeID],
    adjacency: dict[NodeID, tuple[NodeID, ...]],
    hops: int,
) -> set[NodeID]:
    visited: dict[NodeID, int] = dict.fromkeys(seeds, 0)
    queue: deque[NodeID] = deque(sorted(seeds, key=lambda n: n.value))
    while queue:
        v = queue.popleft()
        depth = visited[v]
        if depth >= hops:
            continue
        for w in adjacency.get(v, ()):
            if w not in visited:
                visited[w] = depth + 1
                queue.append(w)
    return set(visited)


def _shortest_path_nodes(
    seeds: set[NodeID],
    target: NodeID,
    adjacency: dict[NodeID, tuple[NodeID, ...]],
) -> set[NodeID]:
    # 多始点 BFS の最短経路 1 本分のノード集合（到達不能なら空）
    if target in seeds:
        return {target}
    parent: dict[NodeID, NodeID | None] = dict.fromkeys(seeds)
    queue: deque[NodeID] = deque(sorted(seeds, key=lambda n: n.value))
    while queue:
        v = queue.popleft()
        for w in adjacency.get(v, ()):
            if w in parent:
                continue
            parent[w] = v
            if w == target:
                path: set[NodeID] = set()
                cur: NodeID | None = w
                while cur is not None:
                    path.add(cur)
                    cur = parent[cur]
                return path
            queue.append(w)
    return set()


def _merge_overlapping(zones: list[_MutableZone]) -> list[_MutableZone]:
    merged: list[_MutableZone] = []
    for zone in zones:
        target = zone
        remaining: list[_MutableZone] = []
        for existing in merged:
            if existing.nodes & target.nodes:
                target = _MutableZone(
                    seed_edges=existing.seed_edges | target.seed_edges,
                    seed_nodes=existing.seed_nodes | target.seed_nodes,
                    nodes=existing.nodes | target.nodes,
                    severity=max(existing.severity, target.severity),
                )
            else:
                remaining.append(existing)
        remaining.append(target)
        merged = remaining
    return merged


def _zone_edge_ids(zone_nodes: set[NodeID], arc_model: ArcModel) -> list[EdgeID]:
    edges: list[EdgeID] = []
    for edge in arc_model.active_edges:
        arcs = arc_model.arcs_of_edge.get(edge.edge_id, ())
        if not arcs:
            continue
        if arcs[0].tail in zone_nodes and arcs[0].head in zone_nodes:
            edges.append(edge.edge_id)
    return sorted(edges, key=lambda e: e.value)


def _tie_key(zone: TriggerZone) -> str:
    if zone.seed_edges:
        return zone.seed_edges[0].value
    if zone.edges:
        return zone.edges[0].value
    return _TIE_LAST


def _freeze(
    zone: _MutableZone,
    arc_model: ArcModel,
    adjacency: dict[NodeID, tuple[NodeID, ...]],
) -> TriggerZone:
    nodes = set(zone.nodes)
    for entry in arc_model.entry_nodes:
        nodes |= _shortest_path_nodes(zone.nodes, entry, adjacency)
    return TriggerZone(
        seed_edges=tuple(sorted(zone.seed_edges, key=lambda e: e.value)),
        seed_nodes=tuple(sorted(zone.seed_nodes, key=lambda n: n.value)),
        nodes=tuple(sorted(nodes, key=lambda n: n.value)),
        edges=tuple(_zone_edge_ids(nodes, arc_model)),
        severity=zone.severity,
    )
