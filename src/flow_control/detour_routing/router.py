from dataclasses import dataclass

from ..domain.enums import Mode
from ..domain.graph import Edge, EdgeID, Graph, NodeID
from ..forecasting import ForecastResult
from .config import ResolvedConfig
from .kshortest import k_shortest_paths
from .traversal import build_adjacency


@dataclass(frozen=True)
class DetourPath:
    edge_ids: tuple[EdgeID, ...]
    total_length: float
    contains_trigger: bool  # 起点アーク自身を含む直行路か


@dataclass(frozen=True)
class DetourSet:
    origin_edge: EdgeID
    endpoint_pair: tuple[NodeID, NodeID]  # 起点アークの両端 (u, v)
    paths: tuple[DetourPath, ...]  # 起点直行路（contains_trigger）＋ k-最短迂回路
    k_effective: int  # G\{a*} 上で得た迂回路の本数（直行路は含めない）

    def edge_set(self) -> frozenset[EdgeID]:
        # P_trigger^{(a*)}：迂回路と起点直行路のアーク和集合
        return frozenset(edge_id for path in self.paths for edge_id in path.edge_ids)


@dataclass(frozen=True)
class DetourResult:
    detour_sets: tuple[DetourSet, ...] = ()

    def detour_set_of(self, origin_edge: EdgeID) -> DetourSet | None:
        for detour_set in self.detour_sets:
            if detour_set.origin_edge == origin_edge:
                return detour_set
        return None

    def trigger_edge_set(self) -> frozenset[EdgeID]:
        # 全トリガーの和集合 P_trigger（複数トリガーの和集合）
        result: frozenset[EdgeID] = frozenset()
        for detour_set in self.detour_sets:
            result |= detour_set.edge_set()
        return result


def route_detour(
    graph: Graph,
    triggered_edges: tuple[EdgeID, ...],
    forecast_result: ForecastResult | None,
    config: ResolvedConfig,
    mode: Mode | None = None,
) -> DetourResult:
    # トリガー起点エッジごとに k-最短迂回路を列挙
    # 出力は triggered_edges 順
    # detour_budget_sec 打ち切り（DETOUR_TRUNCATED）は RequestHandler の責務

    _ = forecast_result
    _ = mode

    detour_sets: list[DetourSet] = []
    seen: set[EdgeID] = set()
    for origin in triggered_edges:
        if origin in seen:
            continue
        seen.add(origin)
        edge = graph.edge_of(origin)
        if edge is None or not edge.enabled:
            continue  # 不明なエッジはスキップ（Detection は有効エッジのみ発火）
        detour_sets.append(_route_one(graph, edge, config))
    return DetourResult(detour_sets=tuple(detour_sets))


def _route_one(graph: Graph, edge: Edge, config: ResolvedConfig) -> DetourSet:
    # 1 本の起点アークについて DetourSet を構築
    u, v = edge.endpoint_a, edge.endpoint_b

    # G\{a*}：起点アークを一時除去して両端間の k-最短路を列挙
    adjacency = build_adjacency(graph, excluded_edges=frozenset({edge.edge_id}))
    detours = k_shortest_paths(adjacency, u, v, config.k_shortest)

    # 起点アーク自身を直行路として 1 本含める
    origin_path = DetourPath(edge_ids=(edge.edge_id,), total_length=1.0, contains_trigger=True)
    detour_paths = tuple(
        DetourPath(
            edge_ids=path.edge_ids,
            total_length=path.total_length,
            contains_trigger=False,
        )
        for path in detours
    )

    return DetourSet(
        origin_edge=edge.edge_id,
        endpoint_pair=(u, v),
        paths=(origin_path, *detour_paths),
        k_effective=len(detour_paths),
    )
