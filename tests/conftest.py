"""Shared fixtures and factory helpers for detection tests.

Detection は「組合せ発火（AND）」モデルである。あるアークが通常トリガーで発火するには

    established（停滞警戒 (a) が M 分継続） AND demand_warning（需要警戒 (b)）

の両方が成立する必要がある（ラインが存在しないアークのみ、停滞警戒単独の縮退発火）。

主な補助 fixture:

- ``make_line_samples``     … ライン流量系列（急増 (b).1 の入力）を生成する
- ``make_history``          … 停滞統計（p90 / recent_ma / baseline）と任意のライン流量を
                              束ねた ``HistoryDigest`` を組み立てる
- ``make_established_watch`` … 停滞警戒が M 分以上継続した ``ArcWatchState`` を生成する
- ``make_combined_firing``  … established 停滞 + ライン急増 の組合せ発火セット
                              ``(history, observations, previous_state)`` を返す
"""

from datetime import UTC, datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
)
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from flow_control.domain.observations import ArcScalarFlow, ArcStagnation, Observations

# 停滞量移動平均の平均は時刻に依存しないため固定タイムスタンプで表現する
_STAGNATION_SAMPLE_TS = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def edge_id() -> EdgeID:
    return EdgeID("e1")


@pytest.fixture
def basic_graph(edge_id: EdgeID) -> Graph:
    """1 本のベクトル型エッジを持つ最小グラフ

    ``time_resolution_s`` は既定値 60 秒
    急増検出窓は ``30 + 60/60 = 31`` 分。
    """
    n1, n2 = NodeID("n1"), NodeID("n2")
    return Graph(
        nodes=(
            Node(node_id=n1, kind=NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(node_id=n2, kind=NodeKind.GOAL, is_boundary=False, enabled=True),
        ),
        edges=(
            Edge(
                edge_id=edge_id,
                endpoint_a=n1,
                endpoint_b=n2,
                direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
                current_direction=CurrentDirection.BIDIRECTIONAL,
                enabled=True,
                observation_type=ObservationType.VECTOR,
            ),
        ),
    )


@pytest.fixture
def y_graph_edge_ids() -> tuple[EdgeID, EdgeID, EdgeID]:
    """Y 型グラフの 3 本のエッジ ID

    定義順は ``Graph.edges`` のタプル順 = ``enabled_edges()`` のイテレーション順と一致する
    """
    return EdgeID("e1"), EdgeID("e2"), EdgeID("e3")


@pytest.fixture
def y_graph(y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID]) -> Graph:
    """Y 型グラフ: 中心ノード ``nc`` から 3 本のエッジが末端ノード ``n1``/``n2``/``n3`` に伸びる

    - ノード: 4 (``nc`` 中心 + ``n1``/``n2``/``n3`` 末端、末端は入退出点)
    - エッジ: 3 (``e1``: nc-n1, ``e2``: nc-n2, ``e3``: nc-n3)
    - ``time_resolution_s`` は既定値 60 秒で急増検出窓は 31 分
    """
    e1, e2, e3 = y_graph_edge_ids
    nc = NodeID("nc")
    n1, n2, n3 = NodeID("n1"), NodeID("n2"), NodeID("n3")

    def _branch(edge_id: EdgeID, leaf: NodeID) -> Edge:
        return Edge(
            edge_id=edge_id,
            endpoint_a=nc,
            endpoint_b=leaf,
            direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
            current_direction=CurrentDirection.BIDIRECTIONAL,
            enabled=True,
            observation_type=ObservationType.VECTOR,
        )

    return Graph(
        nodes=(
            Node(node_id=nc, kind=NodeKind.GOAL, is_boundary=False, enabled=True),
            Node(node_id=n1, kind=NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(node_id=n2, kind=NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(node_id=n3, kind=NodeKind.GOAL, is_boundary=True, enabled=True),
        ),
        edges=(_branch(e1, n1), _branch(e2, n2), _branch(e3, n3)),
    )


@pytest.fixture
def surge_config() -> ResolvedConfig:
    """急増判定の閾値: 10 %/分（M=5 分, beta=1.0）"""
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=10.0,
        high_stagnation_duration_min=5.0,
        beta=1.0,
    )


@pytest.fixture
def high_stagnation_config() -> ResolvedConfig:
    """高停滞判定の閾値: M=5 分, beta=1.0

    急増判定の閾値は十分に高く設定し、需要警戒側（急増）が発火しないようにする。
    需要超過 (b).2 は theta_demand 既定 None のため無効。
    """
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=1_000.0,
        high_stagnation_duration_min=5.0,
        beta=1.0,
    )


@pytest.fixture
def make_line_samples():
    """急増 (b).1 の入力となるライン流量系列 ``tuple[(datetime, float), ...]`` を生成する

    ``observed_at`` を最終点として ``step_minutes`` 間隔で ``sample_count`` 件を配置する。
    最終点（現在観測）まで含めて系列に入れるため、そのまま ``flow_samples`` に載せて
    最小二乗回帰の傾きを評価できる。
    """

    def _make(
        observed_at: datetime,
        *,
        sample_count: int,
        start_value: float,
        slope_per_min: float,
        step_minutes: float = 1.0,
    ) -> tuple[tuple[datetime, float], ...]:
        span = (sample_count - 1) * step_minutes
        start_time = observed_at - timedelta(minutes=span)
        return tuple(
            (
                start_time + timedelta(minutes=i * step_minutes),
                start_value + slope_per_min * (i * step_minutes),
            )
            for i in range(sample_count)
        )

    return _make


@pytest.fixture
def make_history():
    """停滞統計と任意のライン流量を束ねた ``HistoryDigest`` を組み立てる

    各エントリは ``(edge_id, p90_stagnation, recent_stagnation_ma, baseline_stagnation)``
    のタプルで指定する。

    - ``p90_stagnation`` は停滞警戒 (a).1 のパーセンタイル閾値（``None`` で (a).1 縮退）
    - ``recent_stagnation_ma`` は (a).2 の直近移動平均で ``stagnation_samples`` に展開する
      （``None`` なら系列を生成せず (a).2 は評価不能）
    - ``baseline_stagnation`` は (a).2 の相対分母 s̄_e（``ArcHistoryStat`` に格納）

    (a).2 は ``(s - recent_ma) / (baseline + eps) >= beta`` の相対判定であり、
    recent_ma と baseline は別の役割を持つため個別に与える。

    ライン流量は ``flow={edge_id: samples}`` で任意に付与する（急増 (b).1 の入力）。
    """

    def _make(
        *specs: tuple[EdgeID, float | None, float | None, float | None],
        flow: dict[EdgeID, tuple[tuple[datetime, float], ...]] | None = None,
    ) -> HistoryDigest:
        arc_stats: list[ArcHistoryStat] = []
        windows: list[ArcWindowSeries] = []
        for eid, p90, recent_ma, baseline in specs:
            arc_stats.append(
                ArcHistoryStat(
                    edge_id=eid,
                    p90_stagnation=p90,
                    baseline_stagnation=baseline,
                )
            )
            stagnation_samples = (
                ((_STAGNATION_SAMPLE_TS, recent_ma),) if recent_ma is not None else ()
            )
            flow_samples = flow.get(eid, ()) if flow is not None else ()
            windows.append(
                ArcWindowSeries(
                    edge_id=eid,
                    flow_samples=flow_samples,
                    stagnation_samples=stagnation_samples,
                )
            )
        return HistoryDigest(arc_stats=tuple(arc_stats), window_series=tuple(windows))

    return _make


@pytest.fixture
def make_established_watch():
    """停滞警戒 (a) が M 分以上継続した ``ArcWatchState`` を生成する

    ``minutes_elapsed`` は ``stagnation_watch_since`` から ``base_time`` までの経過分。
    既定 6 分は M=5 分を上回るため、当該サイクルでも条件が成立すれば発火する。
    """

    def _make(
        edge_id: EdgeID,
        base_time: datetime,
        *,
        minutes_elapsed: float = 6.0,
    ) -> ArcWatchState:
        return ArcWatchState(
            edge_id=edge_id,
            percentile_breached=True,
            delta_breached=True,
            stagnation_watch_since=base_time - timedelta(minutes=minutes_elapsed),
        )

    return _make


@pytest.fixture
def make_stagnation_observation():
    """``observed_at`` 時点の単一 ``ArcStagnation`` を持つ ``Observations`` を生成する"""

    def _make(
        edge_id: EdgeID,
        *,
        observed_at: datetime,
        stagnation: float,
    ) -> Observations:
        return Observations(
            observed_at=observed_at,
            arc_stagnations=(ArcStagnation(edge_id=edge_id, stagnation=stagnation),),
        )

    return _make


@pytest.fixture
def make_combined_firing(make_history, make_line_samples, make_established_watch):
    """組合せ発火（established 停滞 + ライン急増）の入力一式を組み立てる

    ``(history, observations, previous_state)`` を返す。既定値は

    - ライン: 0 起点・傾き 10/分（mean=45, rate≈22 %/分 > surge 閾値 10）で急増成立
    - 停滞: p90=5, recent_ma=5, baseline=5, 観測停滞=15
            → (a).1 (15>=5) と (a).2 ((15-5)/5=2.0>=1.0) が成立
    - 先行警戒: 両フラグ true, watch_since = base_time - 6 分（M=5 分超）

    → surge 閾値 10・M=5 分・beta=1.0・theta_demand None の構成で組合せ発火する。
    """

    def _make(
        edge_id: EdgeID,
        base_time: datetime,
        *,
        surge_slope: float = 10.0,
        sample_count: int = 11,
        snapshot_ref: str | None = None,
        stagnation: float = 15.0,
        p90: float | None = 5.0,
        recent_ma: float | None = 5.0,
        baseline: float | None = 5.0,
        extra_watch: tuple[ArcWatchState, ...] = (),
    ) -> tuple[HistoryDigest, Observations, DetectionState]:
        line = make_line_samples(
            base_time,
            sample_count=sample_count,
            start_value=0.0,
            slope_per_min=surge_slope,
        )
        history = make_history((edge_id, p90, recent_ma, baseline), flow={edge_id: line})
        observations = Observations(
            observed_at=base_time,
            snapshot_ref=snapshot_ref,
            arc_stagnations=(ArcStagnation(edge_id=edge_id, stagnation=stagnation),),
        )
        previous = DetectionState(
            arc_watch_states=(make_established_watch(edge_id, base_time), *extra_watch)
        )
        return history, observations, previous

    return _make


@pytest.fixture
def make_flat_line_history(make_history, make_line_samples):
    """急増しない平坦なライン流量のみを持つ ``HistoryDigest`` を生成する

    停滞統計は与えないため停滞警戒は評価不能。need「静穏（発火なし）」入力に使う。
    """

    def _make(
        edge_id: EdgeID,
        base_time: datetime,
        *,
        value: float = 100.0,
        sample_count: int = 11,
    ) -> HistoryDigest:
        line = make_line_samples(
            base_time,
            sample_count=sample_count,
            start_value=value,
            slope_per_min=0.0,
        )
        return make_history((edge_id, None, None, None), flow={edge_id: line})

    return _make


@pytest.fixture
def make_scalar_observation():
    """``observed_at`` 時点の単一 ``ArcScalarFlow`` を持つ ``Observations`` を生成する（パンク用）"""

    def _make(
        edge_id: EdgeID,
        *,
        observed_at: datetime,
        observed_count: float,
    ) -> Observations:
        return Observations(
            observed_at=observed_at,
            arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=observed_count),),
        )

    return _make
