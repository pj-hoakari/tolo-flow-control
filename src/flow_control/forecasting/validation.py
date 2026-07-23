"""整合・検証

推定 OD（od_matrix）を OD 導出と同じ実測配分（転換率実測・観測流量比の前方伝播）で
リンク流量に再現し，観測のあるアークとの残差 reproduction_error を算出
残差と観測フラグ・観測カバレッジを node_confidence に反映し，
Optimization の目的関数重みに供する

    resid = Σ_a |v̂_a − v_a| / (Σ_a v_a + ε_0)   （a は観測のあるアークに限る）

未観測アークに載った再現フローは残差に計上しない（保存補完・prior の受け皿であり，
観測と矛盾しているわけではない）
"""

from collections import defaultdict
from dataclasses import dataclass

from ..domain.enums import FlowDirection, ObservationType
from ..domain.graph import Graph, NodeID
from ..domain.observations import ConfidenceFlag, Observations
from .config import ResolvedConfig
from .demand import ImputedArcFlow, NodeDemand
from .od import ODDemand, reproduce_link_flows

# 観測フラグごとのノード信頼度減衰係数（接続アークの最小を採る）
_HOLD_FACTOR = 0.7
_INVALID_FACTOR = 0.0
# 観測カバレッジ係数: 観測欠損アークの寄与（保存補完・prior の間接推定が受け皿と
# なるため，明示的な計測不能（INVALID = 0.0）とは区別して半減にとどめる）
_MISSING_COVERAGE = 0.5

# 有向アークのキー：(edge_id, from_node)
_ArcKey = tuple[str, NodeID]


@dataclass(frozen=True)
class NodeConfidence:
    node_id: NodeID
    confidence: float  # 0.0-1.0


@dataclass(frozen=True)
class ValidationResult:
    reproduction_error: float = 0.0
    node_confidence: tuple[NodeConfidence, ...] = ()


def validate_od(
    graph: Graph,
    observations: Observations,
    od_matrix: tuple[ODDemand, ...],
    node_demands: tuple[NodeDemand, ...],
    config: ResolvedConfig,
    imputed_flows: tuple[ImputedArcFlow, ...] = (),
) -> ValidationResult:
    """OD の再現残差とノード信頼度を算出

    - reproduction_error: 推定 OD を実測配分（保存補完フローを含む）で再現し，
      観測のあるアークとの相対残差
    - node_confidence: 局所再現品質 × 観測フラグ（HOLD 0.7・INVALID 0.0）
      × 観測カバレッジ（欠損アークは半減）
    """
    observed = _observed_arc_flows(graph, observations)
    reproduced = reproduce_link_flows(
        graph, observations, node_demands, od_matrix, config, imputed_flows
    )
    reproduction_error = _reproduction_error(
        observed, reproduced, has_od=bool(od_matrix), epsilon_0=config.epsilon_0
    )
    node_confidence = _node_confidence(
        graph, observations, observed, reproduced, reproduction_error, config.epsilon_0
    )
    return ValidationResult(
        reproduction_error=reproduction_error,
        node_confidence=node_confidence,
    )


def _observed_arc_flows(
    graph: Graph, observations: Observations
) -> dict[_ArcKey, float]:
    """有効ベクトルアークの観測流量を有向アーク (edge_id, from_node) で集める（INVALID 除外）"""
    flows: dict[_ArcKey, float] = defaultdict(float)
    for arc_flow in observations.arc_flows:
        if arc_flow.confidence_flag == ConfidenceFlag.INVALID:
            continue
        edge = graph.edge_of(arc_flow.edge_id)
        if edge is None or not edge.enabled:
            continue
        if edge.observation_type != ObservationType.VECTOR:
            continue
        from_node = (
            edge.endpoint_a
            if arc_flow.direction == FlowDirection.A_TO_B
            else edge.endpoint_b
        )
        flows[(edge.edge_id.value, from_node)] += arc_flow.flow_rate
    return dict(flows)


def _reproduction_error(
    observed: dict[_ArcKey, float],
    reproduced: dict[_ArcKey, float],
    *,
    has_od: bool,
    epsilon_0: float,
) -> float:
    """相対再現残差 Σ|v̂−v| / (Σv + ε_0) を観測のあるアーク上で算出"""
    total_observed = sum(observed.values())
    if total_observed <= 0.0:
        # 検証対象のリンク観測が無い：再現すべき OD も無ければ残差 0，あれば検証不能として最大
        return 0.0 if not has_od else 1.0
    abs_error = sum(
        abs(reproduced.get(key, 0.0) - value) for key, value in observed.items()
    )
    return abs_error / (total_observed + epsilon_0)


def _node_confidence(
    graph: Graph,
    observations: Observations,
    observed: dict[_ArcKey, float],
    reproduced: dict[_ArcKey, float],
    reproduction_error: float,
    epsilon_0: float,
) -> tuple[NodeConfidence, ...]:
    """再現品質・観測フラグ・観測カバレッジから各ノードの信頼度を決める

    confidence_v = base_v × flag_v × coverage_v
    - base_v: 接続する観測済みアークの局所再現残差から clamp(1 − resid_v, 0, 1)。
      接続観測が無ければ全体残差ベース
    - flag_v: 接続アークの観測フラグ係数の最小（HOLD 0.7・INVALID 0.0）
    - coverage_v: 接続ベクトルアークの観測カバレッジ（観測あり 1.0・欠損 0.5 の平均）
    """
    global_base = max(0.0, min(1.0, 1.0 - reproduction_error))

    flag_by_edge: dict[str, ConfidenceFlag] = {}
    for arc_flow in observations.arc_flows:
        # 同一エッジに複数観測があれば最も低信頼（INVALID > HOLD > OK）を採る
        current = flag_by_edge.get(arc_flow.edge_id.value)
        flag_by_edge[arc_flow.edge_id.value] = _worse_flag(
            current, arc_flow.confidence_flag
        )

    incident: dict[NodeID, list[tuple[str, NodeID, NodeID]]] = defaultdict(list)
    for edge in graph.enabled_edges():
        if edge.observation_type != ObservationType.VECTOR:
            continue
        entry = (edge.edge_id.value, edge.endpoint_a, edge.endpoint_b)
        incident[edge.endpoint_a].append(entry)
        incident[edge.endpoint_b].append(entry)

    result: list[NodeConfidence] = []
    for node in graph.enabled_nodes():
        edges = incident.get(node.node_id, ())
        if not edges:
            # ベクトル計測の無いノード（スカラー支線等）は再現品質のみで評価する
            result.append(
                NodeConfidence(node_id=node.node_id, confidence=global_base)
            )
            continue

        flag_factor = 1.0
        covered = 0.0
        local_error = 0.0
        local_observed = 0.0
        for edge_id, endpoint_a, endpoint_b in edges:
            flag = flag_by_edge.get(edge_id)
            if flag is None:
                covered += _MISSING_COVERAGE
                continue
            covered += 1.0
            flag_factor = min(flag_factor, _flag_factor(flag))
            for key in ((edge_id, endpoint_a), (edge_id, endpoint_b)):
                if key in observed:
                    local_observed += observed[key]
                    local_error += abs(reproduced.get(key, 0.0) - observed[key])

        if local_observed > 0.0:
            base = max(
                0.0, min(1.0, 1.0 - local_error / (local_observed + epsilon_0))
            )
        else:
            base = global_base
        coverage = covered / len(edges)
        result.append(
            NodeConfidence(
                node_id=node.node_id, confidence=base * flag_factor * coverage
            )
        )
    return tuple(result)


def _flag_factor(flag: ConfidenceFlag) -> float:
    """観測信頼度フラグ → ノード信頼度減衰係数"""
    if flag == ConfidenceFlag.INVALID:
        return _INVALID_FACTOR
    if flag == ConfidenceFlag.HOLD:
        return _HOLD_FACTOR
    return 1.0


def _worse_flag(
    current: ConfidenceFlag | None, candidate: ConfidenceFlag
) -> ConfidenceFlag:
    """より低信頼なフラグを返す（INVALID < HOLD < OK）"""
    order = {ConfidenceFlag.INVALID: 0, ConfidenceFlag.HOLD: 1, ConfidenceFlag.OK: 2}
    if current is None:
        return candidate
    return current if order[current] <= order[candidate] else candidate
