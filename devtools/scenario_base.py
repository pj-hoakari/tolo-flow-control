"""シナリオ共通基盤

シナリオを束ねる ``Scenario`` 型、各モジュール設定 ``PipelineConfigs``、観測・履歴の生成
``build_observations_and_history``、グラフ加工ヘルパー、簡便コンストラクタ ``make_scenario``
を提供する。個々のシナリオ定義は ``devtools/scenarios/`` 配下に 1 ファイル 1 シナリオで置き、
本モジュールの部品を組み合わせて構成する。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from flow_control.detection.config import ResolvedConfig as DetectionConfig
from flow_control.detection.state import DetectionState
from flow_control.detection.triggers import Event
from flow_control.detour_routing.config import ResolvedConfig as DetourConfig
from flow_control.domain import (
    ArcFlow,
    ArcHistoryStat,
    ArcStagnation,
    ArcScalarFlow,
    ArcWindowSeries,
    EdgeID,
    FlowDirection,
    Graph,
    HistoryDigest,
    NodeID,
    NodeKind,
    NodeOccupancy,
    Observations,
    ObservationType,
    Reference,
)
from flow_control.forecasting.config import ResolvedConfig as ForecastingConfig
from flow_control.optimization.config import ResolvedConfig as OptimizationConfig

from .graph_builder import BuiltGraph

if TYPE_CHECKING:
    from flow_control.optimization import OptimizationResult


# 全シナリオで共有する固定時刻（決定性のため）
DEFAULT_TIME = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)

# 既定の参照値（K>=5 で信頼）
DEFAULT_REFERENCE = Reference(by_attribute_tag=(), source_k_anonymity=5)


@dataclass(frozen=True)
class PipelineConfigs:
    """4 モジュールそれぞれの ResolvedConfig を束ねる"""

    detection: DetectionConfig
    forecasting: ForecastingConfig
    detour: DetourConfig
    optimization: OptimizationConfig


def default_configs() -> PipelineConfigs:
    return PipelineConfigs(
        detection=DetectionConfig(
            surge_rate_threshold_percent_per_min=10.0,
            high_stagnation_duration_min=5.0,
            beta=1.0,
        ),
        forecasting=ForecastingConfig(
            min_reference_sample_count=5,
            fallback_eta=0.1,
        ),
        detour=DetourConfig(k_shortest=3),
        # 開発用途では MILP のタイムアウトを短めに（本番既定 600s に対し 30s）
        optimization=OptimizationConfig(milp_time_limit_sec=30.0),
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    built_graph: BuiltGraph
    observations: Observations
    history_digest: HistoryDigest
    references: Reference
    previous_state: DetectionState
    events: tuple[Event, ...]
    server_time: datetime
    configs: PipelineConfigs
    previous_opt_result: "OptimizationResult | None" = None
    # 検証用ヒント（ファジングの不変条件チェックで参照）
    expect_trigger: bool = True
    notes: str = ""

    @property
    def graph(self) -> Graph:
        return self.built_graph.graph


def make_scenario(
    name: str,
    description: str,
    built: BuiltGraph,
    observations: Observations,
    history_digest: HistoryDigest,
    *,
    previous_state: DetectionState | None = None,
    events: tuple[Event, ...] = (),
    configs: PipelineConfigs | None = None,
    references: Reference | None = None,
    server_time: datetime = DEFAULT_TIME,
    previous_opt_result: "OptimizationResult | None" = None,
    expect_trigger: bool = True,
) -> Scenario:
    """既定値（参照値・時刻・設定）を補いつつ ``Scenario`` を組み立てる簡便コンストラクタ

    個々のシナリオファイルはグラフと観測・履歴を用意して本関数を呼ぶだけでよい。
    """
    return Scenario(
        name=name,
        description=description,
        built_graph=built,
        observations=observations,
        history_digest=history_digest,
        references=references if references is not None else DEFAULT_REFERENCE,
        previous_state=previous_state if previous_state is not None else DetectionState(),
        events=events,
        server_time=server_time,
        configs=configs if configs is not None else default_configs(),
        previous_opt_result=previous_opt_result,
        expect_trigger=expect_trigger,
    )


# --- 観測・履歴の生成 -------------------------------------------------------


def _linear_flow_series(
    server_time: datetime,
    *,
    start_value: float,
    slope_per_min: float,
    sample_count: int,
    step_minutes: float = 1.0,
) -> tuple[tuple[tuple[datetime, float], ...], float]:
    """``sample_count-1`` 件の履歴サンプルと、最終点（観測スカラー値）を返す

    最終点の時刻が ``server_time`` に一致するよう配置する（急増回帰の窓に収める）。
    """
    span = (sample_count - 1) * step_minutes
    start_time = server_time - timedelta(minutes=span)
    samples: list[tuple[datetime, float]] = []
    for i in range(sample_count - 1):
        t = start_time + timedelta(minutes=i * step_minutes)
        v = start_value + slope_per_min * (i * step_minutes)
        samples.append((t, v))
    last_value = start_value + slope_per_min * span
    return tuple(samples), last_value


def build_observations_and_history(
    graph: Graph,
    server_time: datetime = DEFAULT_TIME,
    *,
    surge_edges: frozenset[EdgeID] = frozenset(),
    stagnation_edges: frozenset[EdgeID] = frozenset(),
    unobserved_edges: frozenset[EdgeID] = frozenset(),
    unobserved_nodes: frozenset[NodeID] = frozenset(),
    base_flow: float = 20.0,
    surge_start: float = 5.0,
    surge_slope: float = 10.0,
    surge_samples: int = 6,
    base_stag: float = 2.0,
    hot_stag: float = 12.0,
    p90_stag: float = 8.0,
    baseline_stag: float = 3.0,
    recent_stag_ma: float = 5.0,
    eta: float = 0.1,
    flat_samples: int = 8,
    occupancy: float = 10.0,
    occupancy_delta: float = 0.0,
) -> tuple[Observations, HistoryDigest]:
    """グラフと「急増/高停滞のホットエッジ」から整合した観測・履歴を生成する

    - 急増エッジ: 直近の短い区間で急峻に立ち上がる流量系列（回帰の変化率が閾値超）
    - 高停滞エッジ: 観測停滞量を p90 以上かつ移動平均との差が beta 以上に設定
    - ベクトル型エッジには方向別流量（需要推定の主入力）を付与
    - ``unobserved_edges``: 観測・履歴を一切付与しないルート（センサ無し区間。
      フロー感度はフォールバック eta に委ね、保存則で需要を補完させる）
    - ``unobserved_nodes``: 占有観測を付与しないポイント（混在ホールでもセンサ欠測扱い）
    """
    arc_flows: list[ArcFlow] = []
    arc_scalar_flows: list[ArcScalarFlow] = []
    arc_stagnations: list[ArcStagnation] = []
    window_series: list[ArcWindowSeries] = []
    arc_stats: list[ArcHistoryStat] = []

    for edge in graph.enabled_edges():
        eid = edge.edge_id
        if eid in unobserved_edges:
            continue
        if eid in surge_edges:
            samples, scalar = _linear_flow_series(
                server_time,
                start_value=surge_start,
                slope_per_min=surge_slope,
                sample_count=surge_samples,
            )
        else:
            samples, scalar = _linear_flow_series(
                server_time,
                start_value=base_flow,
                slope_per_min=0.0,
                sample_count=flat_samples,
            )
        arc_scalar_flows.append(ArcScalarFlow(edge_id=eid, observed_count=scalar))
        if edge.observation_type == ObservationType.VECTOR:
            arc_flows.append(
                ArcFlow(
                    edge_id=eid,
                    direction=FlowDirection.A_TO_B,
                    flow_rate=scalar,
                )
            )

        stag = hot_stag if eid in stagnation_edges else base_stag
        arc_stagnations.append(ArcStagnation(edge_id=eid, stagnation=stag))

        window_series.append(
            ArcWindowSeries(
                edge_id=eid,
                flow_samples=samples,
                stagnation_samples=((server_time, recent_stag_ma),),
            )
        )
        arc_stats.append(
            ArcHistoryStat(
                edge_id=eid,
                p90_stagnation=p90_stag,
                baseline_stagnation=baseline_stag,
                flow_sensitivity_eta=eta,
            )
        )

    node_occupancies: list[NodeOccupancy] = []
    for node in graph.enabled_nodes():
        if node.node_id in unobserved_nodes:
            continue
        if node.kind == NodeKind.GOAL_TRANSIT_MIXED:
            node_occupancies.append(
                NodeOccupancy(
                    node_id=node.node_id,
                    occupancy=occupancy,
                    occupancy_delta=occupancy_delta,
                )
            )

    observations = Observations(
        observed_at=server_time,
        snapshot_ref="devtools",
        arc_flows=tuple(arc_flows),
        arc_stagnations=tuple(arc_stagnations),
        arc_scalar_flows=tuple(arc_scalar_flows),
        node_occupancies=tuple(node_occupancies),
    )
    history = HistoryDigest(
        arc_stats=tuple(arc_stats),
        window_series=tuple(window_series),
        completeness=1.0,
    )
    return observations, history


# --- グラフ加工ヘルパー（frozen dataclass の置換）---------------------------


def with_edge_danger(built: BuiltGraph, edge_id: str, capacity: float) -> BuiltGraph:
    """指定エッジに危険フラグと容量上限を立てた新しい ``BuiltGraph`` を返す"""
    eid = EdgeID(edge_id)
    new_edges = tuple(
        replace(e, danger_flag=True, danger_capacity=capacity)
        if e.edge_id == eid
        else e
        for e in built.graph.edges
    )
    return BuiltGraph(
        graph=Graph(nodes=built.graph.nodes, edges=new_edges),
        positions=built.positions,
    )


def with_node_danger(built: BuiltGraph, node_id: str, capacity: float) -> BuiltGraph:
    """指定ノードに危険フラグと通過量上限を立てた新しい ``BuiltGraph`` を返す"""
    nid = NodeID(node_id)
    new_nodes = tuple(
        replace(n, danger_flag=True, danger_capacity=capacity)
        if n.node_id == nid
        else n
        for n in built.graph.nodes
    )
    return BuiltGraph(
        graph=Graph(nodes=new_nodes, edges=built.graph.edges),
        positions=built.positions,
    )
