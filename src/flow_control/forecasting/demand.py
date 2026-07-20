from dataclasses import dataclass

from ..domain.enums import FlowDirection, NodeKind, ObservationType
from ..domain.graph import Edge, EdgeID, Graph, Node, NodeID
from ..domain.observations import ConfidenceFlag, NodeOccupancy, Observations
from .config import ResolvedConfig


@dataclass(frozen=True)
class NodeDemand:
    """点需要分解の結果

    粗流出 P_v・粗流入 A_v を相殺せず保持し，滞在・通過・真の生成・吸収に分解する
    """

    node_id: NodeID
    gross_out: float  # P_v 粗流出
    gross_in: float  # A_v 粗流入
    production: float  # prod_v = max(0, P_v − A_v + stay_v)（OD 行周辺＝真の生成量）
    absorption: float  # absorb_v = stay_v（OD 列周辺＝吸収量）
    transit: float  # trans_v = A_v − stay_v（通過量）
    staying: float  # stay_v（滞在＝終端需要）


@dataclass(frozen=True)
class DemandResult:
    """Step A の需要と、保存則で復元したアークの診断情報。"""

    node_demand: tuple[NodeDemand, ...]
    imputed_arcs: tuple[EdgeID, ...] = ()


def compute_node_demand(
    graph: Graph,
    observations: Observations,
    config: ResolvedConfig,
) -> tuple[NodeDemand, ...]:
    return compute_node_demand_result(graph, observations, config).node_demand


def compute_node_demand_result(
    graph: Graph,
    observations: Observations,
    config: ResolvedConfig,
) -> DemandResult:
    """点需要の独立推定

    有効ノードごとに，ベクトル型アークの観測流量から粗流出 P_v・粗流入 A_v を
    相殺せず集計し，単一未観測アークを保存則で補完したうえで，
    滞在 stay_v・通過 trans_v・真の生成 prod_v・吸収 absorb_vを算出する

    - 集計対象は有効ノードのベクトル型（VECTOR）アークのみ
    - confidence_flag == INVALID の観測・無効エッジ・グラフ非存在エッジは除外
      （HOLD は全量寄与・低信頼）
    - 戻り値は enabled_nodes() の順序（決定的）
    """
    active_nodes = graph.enabled_nodes()
    active_ids = {node.node_id for node in active_nodes}
    outflow: dict[NodeID, float] = {nid: 0.0 for nid in active_ids}  # P_v
    inflow: dict[NodeID, float] = {nid: 0.0 for nid in active_ids}  # A_v

    # ── 10.1.1 粗流出・粗流入（相殺しない） ──
    observed_edges: set[str] = set()
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

        if source in outflow:
            outflow[source] += arc_flow.flow_rate
        if destination in inflow:
            inflow[destination] += arc_flow.flow_rate
        observed_edges.add(edge.edge_id.value)

    occupancy_by_node = _valid_occupancy_by_node(observations)

    # ── 未観測アークの保存補完（in-place で P_v, A_v を更新） ──
    imputed_arcs = _impute_unobserved_arcs(
        active_nodes, outflow, inflow, observed_edges, occupancy_by_node, graph
    )

    # ── 滞在・通過・生成・吸収 ──
    demands: list[NodeDemand] = []
    for node in active_nodes:
        gross_out = outflow[node.node_id]
        gross_in = inflow[node.node_id]
        staying = _staying_demand(
            node, gross_in, occupancy_by_node.get(node.node_id), config
        )
        transit = gross_in - staying
        production = max(0.0, gross_out - gross_in + staying)
        demands.append(
            NodeDemand(
                node_id=node.node_id,
                gross_out=gross_out,
                gross_in=gross_in,
                production=production,
                absorption=staying,
                transit=transit,
                staying=staying,
            )
        )

    return DemandResult(
        node_demand=tuple(demands),
        imputed_arcs=tuple(
            EdgeID(edge_id) for edge_id in graph_edge_order(graph, imputed_arcs)
        ),
    )


def graph_edge_order(graph: Graph, edge_ids: set[str]) -> tuple[str, ...]:
    """グラフ定義順で、保存補完アークを決定的に並べる。"""
    return tuple(
        edge.edge_id.value
        for edge in graph.enabled_edges()
        if edge.edge_id.value in edge_ids
    )


def _valid_occupancy_by_node(
    observations: Observations,
) -> dict[NodeID, NodeOccupancy]:
    result: dict[NodeID, NodeOccupancy] = {}
    for occ in observations.node_occupancies:
        if occ.confidence_flag == ConfidenceFlag.INVALID:
            continue
        result[occ.node_id] = occ
    return result


def _staying_demand(
    node: Node,
    gross_in: float,
    occupancy: NodeOccupancy | None,
    config: ResolvedConfig,
) -> float:
    """滞在（終端）需要 stay_v を Node.kind で分岐して決める

    GOAL_TRANSIT_MIXED は (b) 占有量変化 → (c) リトルの法則 → (d) prior の順
    （(a) 導出転換率は Step B の転換率内部導出に対応するため扱わない）
    """
    if node.kind == NodeKind.TRANSIT_ONLY:
        return 0.0
    if node.kind == NodeKind.GOAL:
        return gross_in  # 全到着が終端

    # GOAL_TRANSIT_MIXED
    delta_occ = occupancy.occupancy_delta if occupancy is not None else None
    level = occupancy.occupancy if occupancy is not None else None
    tau = config.transit_time_prior_sec
    dwell = config.dwell_time_prior_sec

    if delta_occ is not None and delta_occ > 0.0:
        return delta_occ  # (b) 蓄積フェーズ
    if (
        occupancy is not None
        and occupancy.same_sensor_arrival
        and tau is not None
        and dwell is not None
        and dwell > tau
        and level is not None
    ):
        # (c) リトルの法則：占有レベルのうち通過ベースラインを超える滞留分を換算
        return max(0.0, (level - gross_in * tau) / (dwell - tau))
    if delta_occ is not None:
        return max(0.0, delta_occ)  # (b) 定常・排出フェーズ（実質 0）
    return 0.0  # (d) 信号なし → prior 縮退


def _impute_unobserved_arcs(
    active_nodes: tuple[Node, ...],
    outflow: dict[NodeID, float],
    inflow: dict[NodeID, float],
    observed_edges: set[str],
    occupancy_by_node: dict[NodeID, NodeOccupancy],
    graph: Graph,
) -> set[str]:
    """単一未観測アークの保存補完

    保存恒等式「到着 = 出発 + 滞留増」より，ノードに未観測のベクトルアークが
    ちょうど 1 本だけある場合，その流量を一意に逆算する：

        v_{a*} = |A_obs(v) − P_obs(v) − ΔOcc_v|

    符号で向きを決め（残差 > 0 なら v からの流出，< 0 なら v への流入），
    補完値を両端ノードの P_v / A_v に反映する。確定したアークは観測済みに繰り入れ，
    観測フロンティアから内側へ反復適用する。2 本以上未観測のノードは劣決定として残す

    錨にできるのは滞留が収支の残差を吸収しないノードのみ：TRANSIT_ONLY と、
    ΔOcc が観測されている GOAL_TRANSIT_MIXED。純 GOAL は到着が全て終端で
    任意の流入超過を滞留が吸収するため恒等式が未観測アークを定めず、錨にすると
    実在しない流出を捏造して偽の再生成（逆向き OD）を生む。境界ノードは外部との
    出入りが観測されないため恒等式が閉じず、同じく錨にしない

    補完したエッジ ID の集合を返す
    """
    # 補完は観測フロンティアからの逆算である。ベクトル流量の観測が 1 つも無ければ
    # フロンティアが存在せず、ΔOcc 単独からのフロー捏造になるため何もしない
    # （占有のみの NODE_ONLY 縮退は距離 prior の純再配分に委ねる）
    if not observed_edges:
        return set()

    active_ids = {node.node_id for node in active_nodes}
    incident: dict[NodeID, list[Edge]] = {nid: [] for nid in active_ids}
    for edge in graph.enabled_edges():
        if edge.observation_type != ObservationType.VECTOR:
            continue
        if edge.endpoint_a in incident:
            incident[edge.endpoint_a].append(edge)
        if edge.endpoint_b in incident:
            incident[edge.endpoint_b].append(edge)

    resolved = set(observed_edges)
    imputed: set[str] = set()

    def can_anchor(node: Node) -> bool:
        if node.is_boundary:
            return False
        if node.kind == NodeKind.TRANSIT_ONLY:
            return True
        if node.kind == NodeKind.GOAL_TRANSIT_MIXED:
            return node.node_id in occupancy_by_node
        return False

    progressed = True
    while progressed:
        progressed = False
        for node in active_nodes:
            if not can_anchor(node):
                continue
            unobserved = [
                edge
                for edge in incident[node.node_id]
                if edge.edge_id.value not in resolved
            ]
            if len(unobserved) != 1:
                continue

            edge = unobserved[0]
            occ = occupancy_by_node.get(node.node_id)
            delta_occ = occ.occupancy_delta if occ is not None else 0.0
            residual = inflow[node.node_id] - outflow[node.node_id] - delta_occ
            magnitude = abs(residual)

            neighbor = (
                edge.endpoint_b if edge.endpoint_a == node.node_id else edge.endpoint_a
            )
            if residual > 0.0:
                # 流入超過 → 未観測アークは v からの流出（出発）
                outflow[node.node_id] += magnitude
                if neighbor in inflow:
                    inflow[neighbor] += magnitude
            elif residual < 0.0:
                # 流出超過 → 未観測アークは v への流入（到着）
                inflow[node.node_id] += magnitude
                if neighbor in outflow:
                    outflow[neighbor] += magnitude
            # residual == 0 のときは流量 0 のアークとして確定（加算なし）

            resolved.add(edge.edge_id.value)
            imputed.add(edge.edge_id.value)
            progressed = True

    return imputed
