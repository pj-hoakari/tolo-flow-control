from dataclasses import dataclass, field

from ..domain.enums import Mode
from ..domain.graph import EdgeID, Graph
from ..domain.history import HistoryDigest
from ..domain.observations import Observations
from ..domain.references import Reference
from .config import ResolvedConfig
from .demand import NodeDemand, compute_node_demand_result
from .od import NodeResolution, ODDemand, estimate_od
from .sensitivity import (
    ArcFlowSensitivity,
    FallbackReport,
    resolve_arc_flow_sensitivity,
)
from .validation import NodeConfidence, validate_od


@dataclass(frozen=True)
class ForecastResult:
    od_matrix: tuple[ODDemand, ...] = ()
    node_demand: tuple[NodeDemand, ...] = ()
    estimation_resolution: tuple[NodeResolution, ...] = ()
    reproduction_error: float = 0.0
    node_confidence: tuple[NodeConfidence, ...] = ()
    arc_flow_sensitivity: tuple[ArcFlowSensitivity, ...] = ()
    fallback_usage: FallbackReport = field(default_factory=FallbackReport)


def forecast(
    graph: Graph,
    observations: Observations,
    history_digest: HistoryDigest,
    references: Reference,
    triggered_edges: tuple[EdgeID, ...],
    config: ResolvedConfig,
    mode: Mode | None = None,
) -> ForecastResult:
    # triggered_edges は DetourRouting / Optimization 向けの引き回し
    # Forecasting では未使用
    del triggered_edges

    # mode は RequestHandler から伝播する Open/Closed
    # None の場合はグラフから導出（decide_mode と等価: 有効境界 1 つ以上で OPEN）
    if mode is not None:
        is_open_mode = mode == Mode.OPEN
    else:
        is_open_mode = len(graph.boundary_nodes()) > 0

    # Step A: 点需要の独立推定
    demand_result = compute_node_demand_result(graph, observations, config)
    node_demand = demand_result.node_demand

    # Step B: OD 推定
    od_result = estimate_od(
        graph,
        observations,
        node_demand,
        config,
        is_open_mode=is_open_mode,
        imputed_arcs=demand_result.imputed_arcs,
    )

    # Step C: 整合・検証
    validation = validate_od(
        graph,
        observations,
        od_result.od_matrix,
        node_demand,
        config,
        demand_result.imputed_flows,
    )

    # フロー感度 η_e（エッジ単位）
    sensitivity = resolve_arc_flow_sensitivity(graph, history_digest, references, config)

    return ForecastResult(
        od_matrix=od_result.od_matrix,
        node_demand=node_demand,
        estimation_resolution=od_result.resolutions,
        reproduction_error=validation.reproduction_error,
        node_confidence=validation.node_confidence,
        arc_flow_sensitivity=sensitivity.arc_flow_sensitivity,
        fallback_usage=sensitivity.fallback_usage,
    )
