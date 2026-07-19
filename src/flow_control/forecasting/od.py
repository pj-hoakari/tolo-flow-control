"""ルート需要（OD）の推定

点需要分解の周辺量（prod_v / absorb_v）と観測のアーク流量を入力に，OD 需要行列 δ_{s,t} を推定

- TURNING_EXACT   : 全ノードが決定可能（単入口/単出口）かつ全アーク観測済み → 転換率の前方伝播
- DOUBLY_CONSTRAINED: 合流＋分岐ノードを含む → 両制約 IPF（Furness 法）＋距離 prior
- DISTANCE_PRIOR  : 流量観測が無い（占有のみ） → 距離 prior による純再配分
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from ..domain.enums import FlowDirection, NodeKind, ObservationType
from ..domain.graph import EdgeID, Graph, Node, NodeID
from ..domain.observations import ConfidenceFlag, Observations
from .config import ResolvedConfig
from .demand import NodeDemand

# 前方伝播の伝播ステップ上限（純通過サイクルの無限ループ防止。1 ステップ = 1 ホップ）
_MAX_PROPAGATION_STEPS = 1000


class ODResolutionMode(str, Enum):
    TURNING_EXACT = "TURNING_EXACT"
    DOUBLY_CONSTRAINED = "DOUBLY_CONSTRAINED"
    DISTANCE_PRIOR = "DISTANCE_PRIOR"


class ODResolutionReason(str, Enum):
    DETERMINED = "DETERMINED"  # 単入口/単出口で転換率を導出可
    MERGE_SPLIT_AMBIGUOUS = (
        "MERGE_SPLIT_AMBIGUOUS"  # 合流＋分岐で不定（追加観測の優先対象）
    )
    SPARSE_OBSERVATION = "SPARSE_OBSERVATION"  # 流量が一部欠測
    NODE_ONLY = "NODE_ONLY"  # 通路観測なし・占有のみ


@dataclass(frozen=True)
class ODDemand:
    origin: NodeID
    destination: NodeID
    demand: float


@dataclass(frozen=True)
class NodeResolution:
    node_id: NodeID
    mode: ODResolutionMode
    reason: ODResolutionReason
    imputed_arcs: tuple[EdgeID, ...] = ()  # 保存補完で復元したアーク


@dataclass(frozen=True)
class ODResult:
    od_matrix: tuple[ODDemand, ...] = ()
    resolutions: tuple[NodeResolution, ...] = ()


@dataclass(frozen=True)
class _DirectedFlow:
    source: NodeID
    destination: NodeID
    rate: float


def _od_marginals(
    graph: Graph,
    observations: Observations,
    node_demands: tuple[NodeDemand, ...],
    *,
    is_open_mode: bool,
    has_flow: bool,
) -> tuple[dict[NodeID, float], dict[NodeID, float]]:
    """モードごとの OD 行・列周辺を正準規則で選ぶ。"""
    nodes = {node.node_id: node for node in graph.enabled_nodes()}
    occupancy_delta = {
        occupancy.node_id: occupancy.occupancy_delta
        for occupancy in observations.node_occupancies
        if occupancy.confidence_flag != ConfidenceFlag.INVALID
    }

    if not has_flow:
        # NODE_ONLY は占有変化を用いる距離 prior の純再配分である。
        return (
            {d.node_id: d.production for d in node_demands if d.production > 0.0},
            {d.node_id: d.absorption for d in node_demands if d.absorption > 0.0},
        )

    production: dict[NodeID, float] = {}
    absorption: dict[NodeID, float] = {}
    for demand in node_demands:
        node = nodes[demand.node_id]
        if is_open_mode:
            # 境界は外部流入を origin、外部流出を destination として担う。
            if node.is_boundary and demand.production > 0.0:
                production[demand.node_id] = demand.production
            if node.kind == NodeKind.GOAL and demand.production > 0.0:
                production[demand.node_id] = demand.production
            boundary_exit = max(0.0, demand.gross_in - demand.gross_out)
            amount = max(demand.absorption, boundary_exit if node.is_boundary else 0.0)
            if amount > 0.0:
                absorption[demand.node_id] = amount
        else:
            # Closed の通常の生成源は占有が減った排出ノード。GOAL の
            # 再生成は、占有変化に関係なく許す。
            if (
                occupancy_delta.get(demand.node_id, 0.0) < 0.0
                and demand.production > 0.0
            ):
                production[demand.node_id] = demand.production
            if node.kind == NodeKind.GOAL and demand.production > 0.0:
                production[demand.node_id] = demand.production
            if demand.absorption > 0.0:
                absorption[demand.node_id] = demand.absorption
    if not production and not is_open_mode:
        # ΔOcc が提供されない既存観測では、保存則から得た正の production を
        # 最低限の生成シグナルとして使う。ΔOcc が利用可能な場合は上の正準規則が優先する。
        production = {d.node_id: d.production for d in node_demands if d.production > 0.0}
    return production, absorption


def estimate_od(
    graph: Graph,
    observations: Observations,
    node_demands: tuple[NodeDemand, ...],
    config: ResolvedConfig,
    *,
    is_open_mode: bool,
    imputed_arcs: tuple[EdgeID, ...] = (),
) -> ODResult:
    """観測と点需要から OD 需要行列を推定する

    解像度で機構を切替：
    - 全ノード決定可能＋全アーク観測 → 前方伝播（TURNING_EXACT）
    - それ以外で流量観測あり → 両制約 IPF（DOUBLY_CONSTRAINED）
    - 流量観測なし → 距離 prior（DISTANCE_PRIOR）

    OD 採用ペアは δ_{s,t} > config.delta_min のみ
    出力は (origin, destination) 順で決定的
    """
    active_nodes = graph.enabled_nodes()
    boundary_ids = {node.node_id for node in graph.boundary_nodes()}
    flows = _directed_flows(graph, observations)
    has_flow = len(flows) > 0

    in_count, out_count = _io_counts(active_nodes, flows)
    missing_by_node = _missing_observation_by_node(graph, flows)
    turning_nodes = _complete_turning_nodes(graph, observations, flows)

    resolutions = _build_resolutions(
        active_nodes,
        in_count,
        out_count,
        missing_by_node,
        has_flow=has_flow,
        imputed_by_node=_imputed_arcs_by_node(graph, imputed_arcs),
        turning_nodes=turning_nodes,
    )

    # Open では境界が外部流入・流出を吸収する。Closed では排出ノード
    # (ΔOcc < 0) と再生成 GOAL だけを生成源にする。通路観測が無い
    # NODE_ONLY 縮退では、占有変化からの従来の純再配分を維持する。
    production, absorption = _od_marginals(
        graph,
        observations,
        node_demands,
        is_open_mode=is_open_mode,
        has_flow=has_flow,
    )
    if not production or not absorption:
        return ODResult(od_matrix=(), resolutions=resolutions)

    forward_ok = (
        has_flow
        and not any(missing_by_node.values())
        and all(
            _is_decidable(node, in_count[node.node_id], out_count[node.node_id])
            or node.node_id in turning_nodes
            for node in active_nodes
        )
    )

    if forward_ok:
        raw = _forward_propagate(
            node_demands, production, flows, config, observations=observations
        )
        raw = _exclude_invalid_pairs(raw, boundary_ids, is_open_mode)
        od = _cut_and_renormalize(raw, config.delta_min, _row_sums(raw))
    else:
        if not is_open_mode:
            _equalize_per_component(production, absorption, graph)
        raw = _ipf(
            graph,
            production,
            absorption,
            boundary_ids,
            config,
            is_open_mode=is_open_mode,
        )
        od = _cut_and_renormalize(raw, config.delta_min, production)

    od_matrix = _to_od_matrix(od, node_demands)
    return ODResult(od_matrix=od_matrix, resolutions=resolutions)


def _directed_flows(
    graph: Graph, observations: Observations
) -> dict[str, _DirectedFlow]:
    """有効ベクトルアークの観測流量を有向（source→destination）で取り出す"""
    flows: dict[str, _DirectedFlow] = {}
    for arc_flow in observations.arc_flows:
        if arc_flow.confidence_flag == ConfidenceFlag.INVALID:
            continue
        edge = graph.edge_of(arc_flow.edge_id)
        if edge is None or not edge.enabled:
            continue
        if edge.observation_type != ObservationType.VECTOR:
            continue
        if arc_flow.direction == FlowDirection.A_TO_B:
            source, destination = edge.endpoint_a, edge.endpoint_b
        else:
            source, destination = edge.endpoint_b, edge.endpoint_a
        flows[edge.edge_id.value] = _DirectedFlow(
            source, destination, arc_flow.flow_rate
        )
    return flows


def _io_counts(
    active_nodes: tuple[Node, ...],
    flows: dict[str, _DirectedFlow],
) -> tuple[dict[NodeID, int], dict[NodeID, int]]:
    """各ノードの観測入口エッジ数 d_in・出口エッジ数 d_out を数える"""
    in_count: dict[NodeID, int] = {node.node_id: 0 for node in active_nodes}
    out_count: dict[NodeID, int] = {node.node_id: 0 for node in active_nodes}
    for flow in flows.values():
        if flow.source in out_count:
            out_count[flow.source] += 1
        if flow.destination in in_count:
            in_count[flow.destination] += 1
    return in_count, out_count


def _missing_observation_by_node(
    graph: Graph, flows: dict[str, _DirectedFlow]
) -> dict[NodeID, bool]:
    """各ノードに観測欠落の有効ベクトルアークが接続しているか"""
    missing: dict[NodeID, bool] = {
        node.node_id: False for node in graph.enabled_nodes()
    }
    for edge in graph.enabled_edges():
        if edge.observation_type != ObservationType.VECTOR:
            continue
        if edge.edge_id.value in flows:
            continue
        if edge.endpoint_a in missing:
            missing[edge.endpoint_a] = True
        if edge.endpoint_b in missing:
            missing[edge.endpoint_b] = True
    return missing


def _is_decidable(node: Node, in_degree: int, out_degree: int) -> bool:
    """転換率が周辺量だけで一意に定まる（DOF=0）か

    d_out^+ = 出口エッジ数 +（滞在可能 kind なら 1）
    GOAL は全到着終端で実質単一出口
    """
    if node.kind == NodeKind.GOAL:
        d_out_plus = 1
    elif node.kind == NodeKind.GOAL_TRANSIT_MIXED:
        d_out_plus = out_degree + 1
    else:  # TRANSIT_ONLY は滞在を出口に数えない
        d_out_plus = out_degree
    return in_degree <= 1 or d_out_plus <= 1


def _complete_turning_nodes(
    graph: Graph, observations: Observations, flows: dict[str, _DirectedFlow]
) -> set[NodeID]:
    """全入口の配分が有効な TurningObservation で与えられた不定ノード。"""
    by_node_and_entry: dict[tuple[NodeID, str], float] = defaultdict(float)
    for turning in observations.node_turning:
        if turning.confidence_flag == ConfidenceFlag.INVALID:
            continue
        flow = flows.get(turning.from_edge_id.value)
        if flow is None or flow.destination != turning.node_id:
            continue
        if turning.to_edge_id is not None:
            outgoing = flows.get(turning.to_edge_id.value)
            if outgoing is None or outgoing.source != turning.node_id:
                continue
        if turning.ratio < 0.0:
            continue
        by_node_and_entry[(turning.node_id, turning.from_edge_id.value)] += turning.ratio

    result: set[NodeID] = set()
    for node in graph.enabled_nodes():
        incoming = [
            edge_id for edge_id, flow in flows.items() if flow.destination == node.node_id
        ]
        outgoing = sum(1 for flow in flows.values() if flow.source == node.node_id)
        if _is_decidable(node, len(incoming), outgoing) or not incoming:
            continue
        if all(
            abs(by_node_and_entry[(node.node_id, edge_id)] - 1.0) <= 1e-6
            for edge_id in incoming
        ):
            result.add(node.node_id)
    return result


def _build_resolutions(
    active_nodes: tuple[Node, ...],
    in_count: dict[NodeID, int],
    out_count: dict[NodeID, int],
    missing_by_node: dict[NodeID, bool],
    *,
    has_flow: bool,
    imputed_by_node: dict[NodeID, tuple[EdgeID, ...]],
    turning_nodes: set[NodeID],
) -> tuple[NodeResolution, ...]:
    """点／区間ごとの解像度"""
    forward_ok = (
        has_flow
        and not any(missing_by_node.values())
        and all(
            _is_decidable(node, in_count[node.node_id], out_count[node.node_id])
            or node.node_id in turning_nodes
            for node in active_nodes
        )
    )

    resolutions: list[NodeResolution] = []
    for node in active_nodes:
        if not has_flow:
            mode, reason = ODResolutionMode.DISTANCE_PRIOR, ODResolutionReason.NODE_ONLY
        elif forward_ok or node.node_id in turning_nodes:
            mode = ODResolutionMode.TURNING_EXACT
            reason = ODResolutionReason.DETERMINED
        else:
            mode = ODResolutionMode.DOUBLY_CONSTRAINED
            if missing_by_node[node.node_id]:
                reason = ODResolutionReason.SPARSE_OBSERVATION
            elif not _is_decidable(
                node, in_count[node.node_id], out_count[node.node_id]
            ):
                reason = ODResolutionReason.MERGE_SPLIT_AMBIGUOUS
            else:
                reason = ODResolutionReason.DETERMINED
        resolutions.append(
            NodeResolution(
                node_id=node.node_id,
                mode=mode,
                reason=reason,
                imputed_arcs=imputed_by_node.get(node.node_id, ()),
            )
        )
    return tuple(resolutions)


def _imputed_arcs_by_node(
    graph: Graph, imputed_arcs: tuple[EdgeID, ...]
) -> dict[NodeID, tuple[EdgeID, ...]]:
    """保存補完されたアークを、その両端ノードの診断へ関連付ける。"""
    imputed_ids = {edge_id.value for edge_id in imputed_arcs}
    result: dict[NodeID, list[EdgeID]] = defaultdict(list)
    for edge in graph.enabled_edges():
        if edge.edge_id.value not in imputed_ids:
            continue
        result[edge.endpoint_a].append(edge.edge_id)
        result[edge.endpoint_b].append(edge.edge_id)
    return {node_id: tuple(edge_ids) for node_id, edge_ids in result.items()}


def _forward_propagate(
    node_demands: tuple[NodeDemand, ...],
    production: dict[NodeID, float],
    flows: dict[str, _DirectedFlow],
    config: ResolvedConfig,
    *,
    observations: Observations,
) -> dict[tuple[NodeID, NodeID], float]:
    """転換率の前方伝播で OD を直接同定

    各生成源 s の prod_s を seed に，各ノードで終端割合 ρ_v = stay_v/A_v を吸収し，
    残りを出口エッジへ観測流量比で配分して下流へ伝播する
    `A→B`（B で終端）と `A→（B→）C`（B を通過）が厳密に分離される
    """
    gross_in = {d.node_id: d.gross_in for d in node_demands}
    staying = {d.node_id: d.staying for d in node_demands}
    # 終端割合 ρ_v = stay_v/A_v。stay>A の異常時も relay が負にならないよう [0,1] にクランプ
    rho = {
        nid: (min(1.0, staying[nid] / gross_in[nid]) if gross_in[nid] > 0.0 else 0.0)
        for nid in gross_in
    }
    out_split = _out_split_with_edge(flows)
    turning = _turning_split(observations, flows)
    tol = config.ipf_tolerance

    od: dict[tuple[NodeID, NodeID], float] = defaultdict(float)
    for source in node_demands:
        if source.node_id not in production:
            continue
        # 生成量を出口エッジへ射出（生成は s で終端しない）
        pending: dict[tuple[NodeID, str], float] = defaultdict(float)
        for edge_id, neighbor, share in out_split.get(source.node_id, ()):
            pending[(neighbor, edge_id)] += production[source.node_id] * share

        absorbed: dict[NodeID, float] = defaultdict(float)
        steps = 0
        while pending and steps < _MAX_PROPAGATION_STEPS:
            steps += 1
            nxt: dict[tuple[NodeID, str], float] = defaultdict(float)
            moving = 0.0
            for (node_id, incoming_edge), amount in pending.items():
                node_turning = turning.get((node_id, incoming_edge))
                if node_turning is None:
                    ratio = rho.get(node_id, 0.0)
                    absorbed[node_id] += ratio * amount
                    relay = (1.0 - ratio) * amount
                    if relay <= tol:
                        continue
                    for edge_id, neighbor, share in out_split.get(node_id, ()):
                        nxt[(neighbor, edge_id)] += relay * share
                        moving += relay * share
                    continue

                for out_edge, share in node_turning:
                    allocated = amount * share
                    if out_edge is None:
                        absorbed[node_id] += allocated
                    else:
                        flow = flows[out_edge]
                        nxt[(flow.destination, out_edge)] += allocated
                        moving += allocated
            pending = {k: v for k, v in nxt.items() if v > tol}
            if moving <= tol:
                break

        for dest, amount in absorbed.items():
            if amount > 0.0 and dest != source.node_id:
                od[(source.node_id, dest)] += amount

    return dict(od)


def _turning_split(
    observations: Observations, flows: dict[str, _DirectedFlow]
) -> dict[tuple[NodeID, str], tuple[tuple[str | None, float], ...]]:
    """不定ノードで使う入口別の終端・出口配分。"""
    result: dict[tuple[NodeID, str], list[tuple[str | None, float]]] = defaultdict(list)
    for turning in observations.node_turning:
        if turning.confidence_flag == ConfidenceFlag.INVALID:
            continue
        incoming = flows.get(turning.from_edge_id.value)
        if incoming is None or incoming.destination != turning.node_id:
            continue
        if turning.to_edge_id is not None:
            outgoing = flows.get(turning.to_edge_id.value)
            if outgoing is None or outgoing.source != turning.node_id:
                continue
        result[(turning.node_id, turning.from_edge_id.value)].append(
            (
                turning.to_edge_id.value if turning.to_edge_id is not None else None,
                turning.ratio,
            )
        )
    return {
        key: tuple(value)
        for key, value in result.items()
        if abs(sum(ratio for _, ratio in value) - 1.0) <= 1e-6
    }


def _out_split_with_edge(
    flows: dict[str, _DirectedFlow],
) -> dict[NodeID, tuple[tuple[str, NodeID, float], ...]]:
    """出口流量比を edge_id 付きで返す。"""
    out_edges: dict[NodeID, list[tuple[str, NodeID, float]]] = defaultdict(list)
    totals: dict[NodeID, float] = defaultdict(float)
    for edge_id, flow in flows.items():
        out_edges[flow.source].append((edge_id, flow.destination, flow.rate))
        totals[flow.source] += flow.rate
    return {
        node_id: tuple(
            (edge_id, dest, rate / totals[node_id]) for edge_id, dest, rate in edges
        )
        for node_id, edges in out_edges.items()
        if totals[node_id] > 0.0
    }


def _ipf(
    graph: Graph,
    production: dict[NodeID, float],
    absorption: dict[NodeID, float],
    boundary_ids: set[NodeID],
    config: ResolvedConfig,
    *,
    is_open_mode: bool,
) -> dict[tuple[NodeID, NodeID], float]:
    """距離 prior を初期解とする Furness 法（IPF）で行・列周辺へ反復収束

    行制約 Σ_t δ = prod_s，列制約 Σ_s δ = absorb_t
    Open モードは ext→ext を除外
    到達不能ペア（成分横断含む）は対象外
    """
    adjacency = _build_adjacency(graph)
    alpha = config.gravity_alpha

    # 距離 prior を初期重みとして有効ペアを構成
    matrix: dict[tuple[NodeID, NodeID], float] = {}
    for s in production:
        distances = _hop_distances(adjacency, s)
        s_is_boundary = s in boundary_ids
        for t in absorption:
            if t == s:
                continue
            if is_open_mode and s_is_boundary and t in boundary_ids:
                continue  # ext→ext は対象外
            hop = distances.get(t)
            if hop is None:
                continue  # 到達不能（弱連結成分横断を含む）
            matrix[(s, t)] = 1.0 / (hop + 1) ** alpha

    if not matrix:
        return {}

    for _ in range(config.ipf_max_iter):
        max_delta = 0.0
        # 行スケーリング（生成制約）
        row_sum: dict[NodeID, float] = defaultdict(float)
        for (s, _t), value in matrix.items():
            row_sum[s] += value
        for key in matrix:
            s = key[0]
            if row_sum[s] > 0.0:
                scaled = matrix[key] * production[s] / row_sum[s]
                max_delta = max(max_delta, abs(scaled - matrix[key]))
                matrix[key] = scaled
        # 列スケーリング（吸収制約）
        col_sum: dict[NodeID, float] = defaultdict(float)
        for (_s, t), value in matrix.items():
            col_sum[t] += value
        for key in matrix:
            t = key[1]
            if col_sum[t] > 0.0:
                scaled = matrix[key] * absorption[t] / col_sum[t]
                max_delta = max(max_delta, abs(scaled - matrix[key]))
                matrix[key] = scaled
        if max_delta < config.ipf_tolerance:
            break

    # 生成制約を最終的に満たす（Open モードでは境界が列の不均衡を吸収）
    row_sum = defaultdict(float)
    for (s, _t), value in matrix.items():
        row_sum[s] += value
    for key in matrix:
        s = key[0]
        if row_sum[s] > 0.0:
            matrix[key] = matrix[key] * production[s] / row_sum[s]

    return matrix


def _equalize_per_component(
    production: dict[NodeID, float],
    absorption: dict[NodeID, float],
    graph: Graph,
) -> None:
    """Closed モードの均等補正

    弱連結成分ごとに生成・吸収総量を共通量 T=½(Σprod+Σabsorb) へ比例スケールする（in-place）
    """
    for component in _weakly_connected_components(graph):
        prod_total = sum(production.get(nid, 0.0) for nid in component)
        absorb_total = sum(absorption.get(nid, 0.0) for nid in component)
        if prod_total <= 0.0 or absorb_total <= 0.0:
            continue
        target = 0.5 * (prod_total + absorb_total)
        for nid in component:
            if nid in production:
                production[nid] *= target / prod_total
            if nid in absorption:
                absorption[nid] *= target / absorb_total


def _build_adjacency(graph: Graph) -> dict[NodeID, list[NodeID]]:
    """有効エッジから無向隣接リストを構築（ホップ距離・成分算出用）"""
    enabled_node_ids = {node.node_id for node in graph.enabled_nodes()}
    adjacency: dict[NodeID, list[NodeID]] = {nid: [] for nid in enabled_node_ids}
    for edge in graph.enabled_edges():
        a, b = edge.endpoint_a, edge.endpoint_b
        if a in enabled_node_ids and b in enabled_node_ids:
            adjacency[a].append(b)
            adjacency[b].append(a)
    return adjacency


def _hop_distances(
    adjacency: dict[NodeID, list[NodeID]], source: NodeID
) -> dict[NodeID, int]:
    """source から各ノードへの無向ホップ数を BFS で算出（到達不能ノードは欠落）"""
    distances: dict[NodeID, int] = {source: 0}
    queue: deque[NodeID] = deque((source,))
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _weakly_connected_components(graph: Graph) -> list[set[NodeID]]:
    """有効ノードの弱連結成分（無向）"""
    adjacency = _build_adjacency(graph)
    seen: set[NodeID] = set()
    components: list[set[NodeID]] = []
    for node in graph.enabled_nodes():
        if node.node_id in seen:
            continue
        component: set[NodeID] = set()
        queue: deque[NodeID] = deque((node.node_id,))
        seen.add(node.node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in adjacency.get(current, ()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def _exclude_invalid_pairs(
    od: dict[tuple[NodeID, NodeID], float],
    boundary_ids: set[NodeID],
    is_open_mode: bool,
) -> dict[tuple[NodeID, NodeID], float]:
    """自己 OD と Open モードの ext→ext を除外"""
    result: dict[tuple[NodeID, NodeID], float] = {}
    for (s, t), value in od.items():
        if s == t:
            continue
        if is_open_mode and s in boundary_ids and t in boundary_ids:
            continue
        result[(s, t)] = value
    return result


def _row_sums(
    od: dict[tuple[NodeID, NodeID], float],
) -> dict[NodeID, float]:
    row_sum: dict[NodeID, float] = defaultdict(float)
    for (s, _t), value in od.items():
        row_sum[s] += value
    return dict(row_sum)


def _cut_and_renormalize(
    od: dict[tuple[NodeID, NodeID], float],
    delta_min: float,
    row_target: dict[NodeID, float],
) -> dict[tuple[NodeID, NodeID], float]:
    """δ_{s,t} > δ_min のみ採用し，残った要素で行周辺を再正規化"""
    kept = {key: value for key, value in od.items() if value > delta_min}
    row_sum: dict[NodeID, float] = defaultdict(float)
    for (s, _t), value in kept.items():
        row_sum[s] += value
    result: dict[tuple[NodeID, NodeID], float] = {}
    for key, value in kept.items():
        s = key[0]
        target = row_target.get(s, 0.0)
        if row_sum[s] > 0.0 and target > 0.0:
            result[key] = value * target / row_sum[s]
        else:
            result[key] = value
    return result


def _to_od_matrix(
    od: dict[tuple[NodeID, NodeID], float],
    node_demands: tuple[NodeDemand, ...],
) -> tuple[ODDemand, ...]:
    """(origin, destination) を node_demands 順に並べた決定的な ODDemand 列"""
    order = [d.node_id for d in node_demands]
    matrix: list[ODDemand] = []
    for origin in order:
        for destination in order:
            value = od.get((origin, destination))
            if value is not None:
                matrix.append(
                    ODDemand(origin=origin, destination=destination, demand=value)
                )
    return tuple(matrix)
