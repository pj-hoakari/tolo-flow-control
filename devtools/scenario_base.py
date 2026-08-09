"""シナリオ共通基盤

シナリオを束ねる ``Scenario`` 型、各モジュール設定 ``PipelineConfigs``、観測・履歴の生成
``build_observations_and_history``、グラフ加工ヘルパー、簡便コンストラクタ ``make_scenario``
を提供する。個々のシナリオ定義は ``devtools/scenarios/`` 配下に 1 ファイル 1 シナリオで置き、
本モジュールの部品を組み合わせて構成する。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from flow_control.detection.config import ResolvedConfig as DetectionConfig
from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.detection.triggers import Event
from flow_control.detour_routing.config import ResolvedConfig as DetourConfig
from flow_control.domain import (
    ArcFlow,
    ArcHistoryStat,
    ArcScalarFlow,
    ArcStagnation,
    ArcWindowSeries,
    CurrentDirection,
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
DEFAULT_TIME = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)

# 既定の参照値（K>=5 で信頼）
DEFAULT_REFERENCE = Reference(by_attribute_tag=(), source_k_anonymity=5)


def established_watch_state(
    edges: Iterable[EdgeID],
    *,
    server_time: datetime = DEFAULT_TIME,
    established_minutes: float = 6.0,
) -> DetectionState:
    """組合せ発火の「停滞警戒 M 分継続」を満たした前サイクル状態を組む

    現行 Detection は停滞警戒（p90 かつ相対増分）が M 分継続し、かつ需要警戒
    （急増または需要超過）が同時成立して初めてメトリクス発火する。単発リクエストの
    devtools では継続時間を再現できないため、前サイクルで両条件成立・計時開始済みの
    watch を previous_state として与える。``build_observations_and_history`` の
    ``stagnation_edges``（当該サイクルでも両条件を満たす観測）と併用すること。
    """
    return DetectionState(
        arc_watch_states=tuple(
            ArcWatchState(
                edge_id=edge_id,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=server_time - timedelta(minutes=established_minutes),
            )
            for edge_id in sorted(edges, key=lambda e: e.value)
        )
    )


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


def compact_configs(
    *,
    delta_min: float = 8.0,
    milp_time_limit_sec: float = 8.0,
    mip_rel_gap: float = 0.02,
) -> PipelineConfigs:
    """コモディティ数が多くなりがちなグラフ向けの設定

    OD 量カット ``delta_min`` を上げて支配的な需要のみ残し（Phase2 の MILP を軽くする）、
    MILP 時間上限も短縮、さらに相対ギャップ ``mip_rel_gap`` を許容して分枝限定を早期打ち切る。
    ``make_scenario`` の既定。
    """
    base = default_configs()
    return replace(
        base,
        optimization=replace(
            base.optimization,
            delta_min=delta_min,
            milp_time_limit_sec=milp_time_limit_sec,
            mip_rel_gap=mip_rel_gap,
        ),
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
    previous_opt_result: OptimizationResult | None = None
    # 検証用ヒント（ファジングの不変条件チェックで参照）
    expect_trigger: bool = True
    notes: str = ""
    # run-all から除外する（プロセスごと落ちる既知問題があるシナリオ用。単独 run は可）
    skip_in_run_all: bool = False

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
    previous_opt_result: OptimizationResult | None = None,
    expect_trigger: bool = True,
    skip_in_run_all: bool = False,
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
        configs=configs if configs is not None else compact_configs(),
        previous_opt_result=previous_opt_result,
        expect_trigger=expect_trigger,
        skip_in_run_all=skip_in_run_all,
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
    lineless_edges: frozenset[EdgeID] = frozenset(),
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
    - ``lineless_edges``: ライン通過観測を持たない（arc_flows・流量履歴なし）が停滞は
      観測されるエッジ。ライン無しでは停滞警戒単独の縮退発火となる検出経路を再現する
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
        if eid in lineless_edges:
            # ライン通過観測なし: 流量系の観測・履歴を付与しない（停滞のみ観測）
            samples = ()
        else:
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


# --- 保存則整合な観測生成 ---------------------------------------------------


@dataclass(frozen=True)
class ODSpec:
    """観測合成用の起点→終点フロー指定（人/分）

    ``surge=True`` の成分は履歴系列でランプ状に立ち上がり（急増検出の対象）、
    False の成分は全期間一定となる。いずれも最終スナップショットでは ``rate`` が流れる。
    """

    origin: NodeID
    destination: NodeID
    rate: float
    surge: bool = False
    # 指定時は current 方向に従う最短路の代わりに、このエッジ列で観測を合成する。
    # シナリオの「既存の利用経路」を表す開発用ヒントであり、最適化の入力制約ではない。
    path: tuple[EdgeID, ...] | None = None


def build_consistent_observations_and_history(
    graph: Graph,
    od_flows: tuple[ODSpec, ...],
    server_time: datetime = DEFAULT_TIME,
    *,
    stagnation_edges: frozenset[EdgeID] = frozenset(),
    lineless_edges: frozenset[EdgeID] = frozenset(),
    unobserved_edges: frozenset[EdgeID] = frozenset(),
    unobserved_nodes: frozenset[NodeID] = frozenset(),
    surge_start_ratio: float = 0.1,
    surge_samples: int = 6,
    flat_samples: int = 8,
    base_stag: float = 2.0,
    hot_stag: float = 12.0,
    p90_stag: float = 8.0,
    baseline_stag: float = 3.0,
    recent_stag_ma: float = 5.0,
    eta: float = 0.1,
    occupancy_base: float = 10.0,
    route_vector_only: bool = True,
) -> tuple[Observations, HistoryDigest]:
    """OD 指定から保存則と整合する観測・履歴を合成する

    各 OD を current 方向に従う有向最短路（BFS・ID 昇順で決定的）、または指定された
    既存利用経路で流し込み、
    方向別アークフローを合成する。通過ノードでは流入=流出が成立し、
    混在ホールでは「流入超過 = 滞在」を占有量変化（ΔOcc）として与えるため、
    Forecasting の需要導出（滞在=ΔOcc・生成=流出超過）と帳尻が合い、
    OD 再現誤差が構造的に小さくなる。

    - ``surge=True`` の OD 成分は履歴末尾 ``surge_samples`` 点で
      ``surge_start_ratio``→1.0 へ線形に立ち上がる（経路上エッジのみ急増）
    - 既定では VECTOR 観測エッジのみを経路に使う（SCALAR エッジへ流すと方向別
      フローに現れず保存が崩れて見えるため）。``route_vector_only=False`` で解除可
    - 混在ホール（GOAL_TRANSIT_MIXED）を通過する OD を含めると、滞在と通過の帰属が
      観測上本質的に曖昧になり再現誤差は残る（実世界と同じ性質）。誤差を小さく
      したい場合はホールを終点としてのみ使う OD 構成にする
    - 停滞・ラインなし・未観測の扱いは ``build_observations_and_history`` と同じ
    """
    adjacency = _directed_adjacency(graph, vector_only=route_vector_only)

    # OD ごとに最短路を引き、方向別レート（base, surge）を積み上げる
    base_rate: dict[tuple[EdgeID, FlowDirection], float] = {}
    surge_rate: dict[tuple[EdgeID, FlowDirection], float] = {}
    staying_rate: dict[NodeID, float] = {}
    origin_rate: dict[NodeID, float] = {}
    for od in od_flows:
        path = (
            _path_from_edge_ids(graph, od.origin, od.destination, od.path)
            if od.path is not None
            else _shortest_directed_path(adjacency, od.origin, od.destination)
        )
        if path is None:
            raise ValueError(
                f"OD {od.origin.value}->{od.destination.value} は current 方向で到達不能"
            )
        target = surge_rate if od.surge else base_rate
        for key in path:
            target[key] = target.get(key, 0.0) + od.rate
        staying_rate[od.destination] = staying_rate.get(od.destination, 0.0) + od.rate
        origin_rate[od.origin] = origin_rate.get(od.origin, 0.0) + od.rate

    # ランプ係数列（全エッジ共通の時間グリッド。最終点が server_time に一致）
    n = max(flat_samples, surge_samples, 2)
    start_time = server_time - timedelta(minutes=n - 1)
    ramp: list[float] = []
    for i in range(n):
        k = i - (n - surge_samples)
        if k <= 0:
            ramp.append(surge_start_ratio)
        else:
            ramp.append(surge_start_ratio + (1.0 - surge_start_ratio) * k / (surge_samples - 1))

    arc_flows: list[ArcFlow] = []
    arc_scalar_flows: list[ArcScalarFlow] = []
    arc_stagnations: list[ArcStagnation] = []
    window_series: list[ArcWindowSeries] = []
    arc_stats: list[ArcHistoryStat] = []

    for edge in graph.enabled_edges():
        eid = edge.edge_id
        if eid in unobserved_edges:
            continue

        stag = hot_stag if eid in stagnation_edges else base_stag
        arc_stagnations.append(ArcStagnation(edge_id=eid, stagnation=stag))
        arc_stats.append(
            ArcHistoryStat(
                edge_id=eid,
                p90_stagnation=p90_stag,
                baseline_stagnation=baseline_stag,
                flow_sensitivity_eta=eta,
            )
        )

        if eid in lineless_edges:
            window_series.append(
                ArcWindowSeries(
                    edge_id=eid,
                    flow_samples=(),
                    stagnation_samples=((server_time, recent_stag_ma),),
                )
            )
            continue

        base_total = 0.0
        surge_total = 0.0
        directional: list[tuple[FlowDirection, tuple[tuple[datetime, float], ...]]] = []
        for direction in (FlowDirection.A_TO_B, FlowDirection.B_TO_A):
            b = base_rate.get((eid, direction), 0.0)
            s = surge_rate.get((eid, direction), 0.0)
            base_total += b
            surge_total += s
            final = b + s
            if final > 0.0 and edge.observation_type == ObservationType.VECTOR:
                arc_flows.append(ArcFlow(edge_id=eid, direction=direction, flow_rate=final))
                # 方向別ライン通過系列（排出実績 μ̂ の算出に使われる）
                directional.append(
                    (
                        direction,
                        tuple(
                            (start_time + timedelta(minutes=i), b + s * ramp[i])
                            for i in range(n - 1)
                        ),
                    )
                )
        arc_scalar_flows.append(ArcScalarFlow(edge_id=eid, observed_count=base_total + surge_total))
        samples = tuple(
            (start_time + timedelta(minutes=i), base_total + surge_total * ramp[i])
            for i in range(n - 1)
        )
        window_series.append(
            ArcWindowSeries(
                edge_id=eid,
                flow_samples=samples,
                stagnation_samples=((server_time, recent_stag_ma),),
                directional_flow_samples=tuple(directional) if directional else None,
            )
        )

    node_occupancies: list[NodeOccupancy] = []
    for node in graph.enabled_nodes():
        if node.node_id in unobserved_nodes:
            continue
        if node.kind == NodeKind.GOAL_TRANSIT_MIXED:
            # 終点分は蓄積（ΔOcc>0）、起点分は放出（ΔOcc<0。Closed モードの生成源表現）。
            # 同一ノードが起点かつ終点の場合は差分になり、滞在の帰属は縮退する
            stay = staying_rate.get(node.node_id, 0.0)
            delta = stay - origin_rate.get(node.node_id, 0.0)
            node_occupancies.append(
                NodeOccupancy(
                    node_id=node.node_id,
                    occupancy=occupancy_base + max(0.0, delta),
                    occupancy_delta=delta,
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


def reachable_od(
    graph: Graph, origin: NodeID, destination: NodeID, *, vector_only: bool = True
) -> bool:
    """``origin``→``destination`` が current 方向で到達可能か

    ``build_consistent_observations_and_history`` は到達不能な OD を指定すると
    例外を投げるため、OD をランダムに組む側（ファジング等）の事前判定に使う。
    """
    if origin == destination:
        return False
    adjacency = _directed_adjacency(graph, vector_only=vector_only)
    return _shortest_directed_path(adjacency, origin, destination) is not None


def _directed_adjacency(
    graph: Graph,
    *,
    vector_only: bool = True,
) -> dict[NodeID, tuple[tuple[NodeID, EdgeID, FlowDirection], ...]]:
    """current 方向で通行可能な有向隣接（近傍は ID 昇順で決定的）"""
    adjacency: dict[NodeID, list[tuple[NodeID, EdgeID, FlowDirection]]] = {}
    enabled_nodes = {n.node_id for n in graph.enabled_nodes()}
    for edge in graph.enabled_edges():
        a, b = edge.endpoint_a, edge.endpoint_b
        if a not in enabled_nodes or b not in enabled_nodes:
            continue
        if vector_only and edge.observation_type != ObservationType.VECTOR:
            continue
        if edge.current_direction in (
            CurrentDirection.A_TO_B,
            CurrentDirection.BIDIRECTIONAL,
        ):
            adjacency.setdefault(a, []).append((b, edge.edge_id, FlowDirection.A_TO_B))
        if edge.current_direction in (
            CurrentDirection.B_TO_A,
            CurrentDirection.BIDIRECTIONAL,
        ):
            adjacency.setdefault(b, []).append((a, edge.edge_id, FlowDirection.B_TO_A))
    return {
        v: tuple(sorted(items, key=lambda t: (t[0].value, t[1].value)))
        for v, items in adjacency.items()
    }


def _shortest_directed_path(
    adjacency: dict[NodeID, tuple[tuple[NodeID, EdgeID, FlowDirection], ...]],
    origin: NodeID,
    destination: NodeID,
) -> list[tuple[EdgeID, FlowDirection]] | None:
    """BFS 最短路（有向アーク列）。到達不能なら None"""
    if origin == destination:
        return []
    parent: dict[NodeID, tuple[NodeID, EdgeID, FlowDirection]] = {}
    seen = {origin}
    queue: deque[NodeID] = deque([origin])
    while queue:
        v = queue.popleft()
        for w, eid, direction in adjacency.get(v, ()):
            if w in seen:
                continue
            seen.add(w)
            parent[w] = (v, eid, direction)
            if w == destination:
                path: list[tuple[EdgeID, FlowDirection]] = []
                cur = w
                while cur != origin:
                    prev, peid, pdir = parent[cur]
                    path.append((peid, pdir))
                    cur = prev
                path.reverse()
                return path
            queue.append(w)
    return None


def _path_from_edge_ids(
    graph: Graph,
    origin: NodeID,
    destination: NodeID,
    edge_ids: tuple[EdgeID, ...],
) -> list[tuple[EdgeID, FlowDirection]] | None:
    """指定エッジ列を有向の連続経路として検証し、アーク列へ変換する。"""
    current = origin
    path: list[tuple[EdgeID, FlowDirection]] = []
    for edge_id in edge_ids:
        edge = graph.edge_of(edge_id)
        if edge is None or not edge.enabled:
            return None
        if current == edge.endpoint_a:
            direction, nxt = FlowDirection.A_TO_B, edge.endpoint_b
            allowed = edge.current_direction in (
                CurrentDirection.A_TO_B,
                CurrentDirection.BIDIRECTIONAL,
            )
        elif current == edge.endpoint_b:
            direction, nxt = FlowDirection.B_TO_A, edge.endpoint_a
            allowed = edge.current_direction in (
                CurrentDirection.B_TO_A,
                CurrentDirection.BIDIRECTIONAL,
            )
        else:
            return None
        if not allowed:
            return None
        path.append((edge_id, direction))
        current = nxt
    return path if current == destination else None


# --- グラフ加工ヘルパー（frozen dataclass の置換）---------------------------


def with_edge_danger(built: BuiltGraph, edge_id: str, capacity: float) -> BuiltGraph:
    """指定エッジに危険フラグと容量上限を立てた新しい ``BuiltGraph`` を返す"""
    eid = EdgeID(edge_id)
    new_edges = tuple(
        replace(e, danger_flag=True, danger_capacity=capacity) if e.edge_id == eid else e
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
        replace(n, danger_flag=True, danger_capacity=capacity) if n.node_id == nid else n
        for n in built.graph.nodes
    )
    return BuiltGraph(
        graph=Graph(nodes=new_nodes, edges=built.graph.edges),
        positions=built.positions,
    )
