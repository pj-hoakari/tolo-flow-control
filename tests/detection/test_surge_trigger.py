"""Tests for the surge component of the combined (AND) trigger

急増（需要警戒 (b).1）テスト

組合せ発火モデルでは、急増は「需要警戒」の一系統に過ぎず、単独では発火しない。
発火には ``established 停滞（(a)）AND demand_warning（(b)）`` の両立が必要である。

急増率はライン流量の系列（``ArcWindowSeries.flow_samples`` ＋ 現在点 ``arc_flows``）から
最小二乗回帰の傾きを自己平均で正規化した %/分で評価する。スカラー流量（``arc_scalar_flows``）
は急増には用いない（パンク専用）。

本ファイルでは主に「急増が発火成立/不成立へ与える影響」を検証する:
  - 急増のみ（停滞なし） → 非発火
  - 急増 ＋ established 停滞 → 発火（kind=HIGH_STAGNATION, SurgeEvidence 付与）
  - established 停滞 ＋ 急増なし → 非発火（AND 否定）・警戒保持
  - スカラー流量は急増に使わない
  - サンプル不足・閾値未満・平均≈0 では急増不成立
"""

from datetime import datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import SurgeEvidence
from flow_control.detection.state import DetectionState, QueuedTriggerKind
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import EdgeID, FlowDirection, Graph
from flow_control.domain.observations import (
    ArcFlow,
    ArcScalarFlow,
    ArcStagnation,
    Observations,
)
from flow_control.domain.history import HistoryDigest


def _run(
    *,
    graph: Graph,
    history: HistoryDigest,
    observations: Observations,
    previous_state: DetectionState,
    server_time: datetime,
    config: ResolvedConfig,
):
    return detect_metric_triggers(
        graph=graph,
        observations=observations,
        history_digest=history,
        previous_state=previous_state,
        server_time=server_time,
        config=config,
    )


# ---------------------------------------------------------------------------
# 急増単独では発火しない（需要警戒は組合せの片翼）
# ---------------------------------------------------------------------------


def test_surge_alone_does_not_fire(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
):
    # ライン急増（rate≈22 %/分 > 10）は成立するが、停滞警戒が無いため発火しない
    line = make_line_samples(
        base_time, sample_count=11, start_value=0.0, slope_per_min=10.0
    )
    history = make_history((edge_id, None, None, None), flow={edge_id: line})
    observations = Observations(observed_at=base_time)

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()
    assert result.fired_triggers == ()


def test_surge_with_established_stagnation_fires(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
):
    # established 停滞 ＋ ライン急増 → 組合せ発火する
    history, observations, previous = make_combined_firing(edge_id, base_time)

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == (edge_id,)
    assert len(result.fired_triggers) == 1
    # 組合せ発火の kind は SURGE ではなく HIGH_STAGNATION
    assert result.fired_triggers[0].kind == QueuedTriggerKind.HIGH_STAGNATION
    # 急増が成立しラインが存在するため SurgeEvidence が付与される
    surge_evidences = [e for e in result.evidences if isinstance(e, SurgeEvidence)]
    assert len(surge_evidences) == 1
    assert surge_evidences[0].rate_percent_per_min > 10.0


def test_established_stagnation_without_surge_does_not_fire(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_stagnation_observation,
    make_established_watch,
):
    # established 停滞 はあるが、ラインは平坦で急増せず、需要超過も無効（theta_demand None）
    # → demand_warning 偽で発火しない（AND 否定）。ラインが存在するため縮退もしない
    flat_line = make_line_samples(
        base_time, sample_count=11, start_value=100.0, slope_per_min=0.0
    )
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: flat_line})
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=15.0
    )
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),)
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()
    # 停滞警戒は保持される
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.percentile_breached is True
    assert watch.delta_breached is True


def test_scalar_flow_is_not_used_for_surge(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_stagnation_observation,
    make_established_watch,
):
    # ラインは平坦だがスカラー流量を高値で与える。スカラーは急増に使わないため
    # 急増は成立せず、established 停滞があっても発火しない
    flat_line = make_line_samples(
        base_time, sample_count=11, start_value=100.0, slope_per_min=0.0
    )
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: flat_line})
    stagnation_obs = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=15.0
    )
    observations = Observations(
        observed_at=base_time,
        arc_stagnations=stagnation_obs.arc_stagnations,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=9_999.0),),
    )
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),)
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()


def test_surge_below_threshold_with_stagnation_does_not_fire(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_stagnation_observation,
    make_established_watch,
):
    # 100 → 105 を 10 分で増加。slope=0.5/min, mean≈102.5 → rate≈0.49 %/min < 10
    # established 停滞があっても急増不成立で発火しない
    line = make_line_samples(
        base_time, sample_count=11, start_value=100.0, slope_per_min=0.5
    )
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: line})
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=15.0
    )
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),)
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()


def test_surge_insufficient_samples_with_stagnation_does_not_fire(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_stagnation_observation,
    make_established_watch,
):
    # ライン系列 1 点のみでは傾きを算出できず急増不成立
    # established 停滞があっても発火しない
    line = make_line_samples(
        base_time, sample_count=1, start_value=100.0, slope_per_min=0.0
    )
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: line})
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=15.0
    )
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),)
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()


def test_surge_uses_current_arc_flow_point(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
):
    # 現在点は arc_flows（両方向合算）でも供給できる。履歴 + 現在点で急増を評価する
    # 履歴は 0 → 90（10 点, base_time-10..base_time-1 分）
    history_line = make_line_samples(
        base_time - timedelta(minutes=1),
        sample_count=10,
        start_value=0.0,
        slope_per_min=10.0,
    )
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: history_line})
    # 現在点 100 を arc_flows（A_TO_B 60 + B_TO_A 40 = 100）で供給
    observations = Observations(
        observed_at=base_time,
        arc_stagnations=(ArcStagnation(edge_id=edge_id, stagnation=15.0),),
        arc_flows=(
            ArcFlow(edge_id=edge_id, direction=FlowDirection.A_TO_B, flow_rate=60.0),
            ArcFlow(edge_id=edge_id, direction=FlowDirection.B_TO_A, flow_rate=40.0),
        ),
    )
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),)
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == (edge_id,)


# ---------------------------------------------------------------------------
# Y 型グラフ (3 エッジ) 上での複数エッジ組み合わせ
# ---------------------------------------------------------------------------


def _combined_setup(
    edge_ids: tuple[EdgeID, ...],
    firing_indices: set[int],
    base_time: datetime,
    make_history,
    make_line_samples,
    make_established_watch,
):
    """指定インデックスのエッジは組合せ発火成立、他は静穏（平坦・停滞なし）となる入力を返す

    ``(history, observations, previous_state)`` を返す。
    """
    specs: list[tuple[EdgeID, float | None, float | None, float | None]] = []
    flow: dict[EdgeID, tuple[tuple[datetime, float], ...]] = {}
    stagnations: list[ArcStagnation] = []
    watch_states = []
    for i, eid in enumerate(edge_ids):
        if i in firing_indices:
            specs.append((eid, 5.0, 5.0, 5.0))
            flow[eid] = make_line_samples(
                base_time, sample_count=11, start_value=0.0, slope_per_min=10.0
            )
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=15.0))
            watch_states.append(make_established_watch(eid, base_time))
        else:
            specs.append((eid, None, None, None))
            flow[eid] = make_line_samples(
                base_time, sample_count=11, start_value=100.0, slope_per_min=0.0
            )
    history = make_history(*specs, flow=flow)
    observations = Observations(
        observed_at=base_time, arc_stagnations=tuple(stagnations)
    )
    previous = DetectionState(arc_watch_states=tuple(watch_states))
    return history, observations, previous


def test_y_graph_no_trigger_when_all_edges_calm(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
):
    history, observations, previous = _combined_setup(
        y_graph_edge_ids, set(), base_time, make_history, make_line_samples,
        make_established_watch,
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()


@pytest.mark.parametrize("firing_index", [0, 1, 2])
def test_y_graph_fires_only_on_combined_edge(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
    firing_index: int,
):
    history, observations, previous = _combined_setup(
        y_graph_edge_ids, {firing_index}, base_time, make_history, make_line_samples,
        make_established_watch,
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == (y_graph_edge_ids[firing_index],)


def test_y_graph_returns_all_combined_edges_when_multiple_qualify(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
):
    e1, _e2, e3 = y_graph_edge_ids
    history, observations, previous = _combined_setup(
        y_graph_edge_ids, {0, 2}, base_time, make_history, make_line_samples,
        make_established_watch,
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert set(result.triggered_edges) == {e1, e3}
    assert len(result.triggered_edges) == 2  # 重複なし
