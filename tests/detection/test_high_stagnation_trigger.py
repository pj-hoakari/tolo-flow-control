"""Tests for the high stagnation trigger

高停滞トリガーテスト

ハイブリッド判定（数理§9.2）:
  (b).1 ``stagnation >= ArcHistoryStat.p90_stagnation``
  (b).2 ``stagnation - 直近停滞量移動平均 >= config.beta``
        直近移動平均は ``window_series.stagnation_samples`` から算出する

両方が ``config.high_stagnation_duration_min`` (M) 分以上継続したら発火する
片方のみ満たす場合は ``arc_watch_states`` に警戒状態（``ArcWatchState``）として記録する
"""

from datetime import datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import EdgeID, Graph
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import Observations


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
# 単一エッジ: 警戒状態の生成と発火条件
# ---------------------------------------------------------------------------


def test_records_watch_when_only_percentile_breached(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # stagnation=10, p90=5 → (b).1 満たす
    # baseline=9.5, beta=1.0 → 差分=0.5 < 1.0 で (b).2 不成立
    history = make_history_with_arc_stats((edge_id, 5.0, 9.5))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.percentile_breached is True
    assert watch.delta_breached is False


def test_records_watch_when_only_delta_breached(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # stagnation=10, p90=20 → (b).1 不成立
    # baseline=5, beta=1.0 → 差分=5 >= 1 で (b).2 満たす
    history = make_history_with_arc_stats((edge_id, 20.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.percentile_breached is False
    assert watch.delta_breached is True


def test_no_watch_when_neither_condition_satisfied(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # stagnation=1, p90=20, baseline=5 → どちらも不成立
    # 先行警戒状態なし → 警戒状態を生成しない
    history = make_history_with_arc_stats((edge_id, 20.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=1.0
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.watch_state_of(edge_id) is None


def test_records_watch_when_both_satisfied_but_duration_short(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # stagnation=10, p90=5, baseline=5, beta=1.0
    # 先行警戒状態: 両フラグ true、stagnation_watch_since = now - 1 分（M=5 分未満）
    # → 発火せず、警戒状態を保持する
    history = make_history_with_arc_stats((edge_id, 5.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=edge_id,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=1),
            ),
        )
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.percentile_breached is True
    assert watch.delta_breached is True


def test_fires_when_both_satisfied_for_m_minutes(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # 先行警戒状態: 両フラグ true、stagnation_watch_since = now - 6 分（M=5 分以上経過）
    # 直近観測も両条件を満たすため、発火する
    history = make_history_with_arc_stats((edge_id, 5.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=edge_id,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=6),
            ),
        )
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == (edge_id,)


def test_records_watch_start_when_both_first_become_satisfied(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # 先行警戒状態なし、今回両条件を初めて満たす
    # → 発火せず（継続時間=0）、stagnation_watch_since=now で警戒状態を新規記録
    history = make_history_with_arc_stats((edge_id, 5.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.percentile_breached is True
    assert watch.delta_breached is True
    assert watch.stagnation_watch_since == base_time


def test_clears_watch_when_conditions_no_longer_met(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history_with_arc_stats,
):
    # 先行警戒状態あり、しかし今回は両条件とも不成立
    # → 発火せず、警戒状態は解除される
    history = make_history_with_arc_stats((edge_id, 20.0, 5.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=1.0
    )
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=edge_id,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=2),
            ),
        )
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.watch_state_of(edge_id) is None


def test_does_not_fire_when_stagnation_observation_missing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_history_with_arc_stats,
):
    # 履歴は揃っているが、観測値に ArcStagnation が無い
    # → 評価不能、発火せず警戒状態も生成しない
    history = make_history_with_arc_stats((edge_id, 5.0, 5.0))
    observations = Observations(observed_at=base_time)

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.watch_state_of(edge_id) is None


def test_does_not_fire_when_history_stat_missing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
):
    # 観測値は揃っているが、当該エッジの ArcHistoryStat が無い
    # → 評価不能、発火せず警戒状態も生成しない
    history = HistoryDigest()
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=10.0
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.watch_state_of(edge_id) is None


# ---------------------------------------------------------------------------
# Y 型グラフ (3 エッジ) 上での複数エッジ判定
# ---------------------------------------------------------------------------


def _both_satisfied_setup(
    edge_ids: tuple[EdgeID, ...],
    stagnating_indices: set[int],
    base_time: datetime,
    make_history_with_arc_stats,
):
    """指定インデックスのエッジは両条件成立、それ以外は両条件不成立となる入力を組み立てる

    複数エッジに対する観測は ``arc_stagnations`` を連結した ``Observations`` として返す
    """
    stats: list[tuple[EdgeID, float | None, float | None]] = []
    stagnations = []
    from flow_control.domain.observations import ArcStagnation

    for i, eid in enumerate(edge_ids):
        if i in stagnating_indices:
            stats.append((eid, 5.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=10.0))
        else:
            stats.append((eid, 20.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=1.0))

    history = make_history_with_arc_stats(*stats)
    observations = Observations(
        observed_at=base_time, arc_stagnations=tuple(stagnations)
    )
    return history, observations


def test_y_graph_no_trigger_when_all_edges_calm(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    high_stagnation_config: ResolvedConfig,
    make_history_with_arc_stats,
):
    # 3 エッジすべて両条件不成立
    history, observations = _both_satisfied_setup(
        y_graph_edge_ids,
        stagnating_indices=set(),
        base_time=base_time,
        make_history_with_arc_stats=make_history_with_arc_stats,
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=DetectionState(),
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.arc_watch_states == ()


@pytest.mark.parametrize("stagnating_index", [0, 1, 2])
def test_y_graph_fires_only_on_stagnating_edge_after_m_minutes(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    high_stagnation_config: ResolvedConfig,
    make_history_with_arc_stats,
    stagnating_index: int,
):
    # 1 本のみ両条件成立、他 2 本は不成立
    # 当該エッジの先行警戒状態は M 分以上経過済みで、今回発火する
    history, observations = _both_satisfied_setup(
        y_graph_edge_ids,
        stagnating_indices={stagnating_index},
        base_time=base_time,
        make_history_with_arc_stats=make_history_with_arc_stats,
    )
    target = y_graph_edge_ids[stagnating_index]
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=target,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=6),
            ),
        )
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == (target,)


def test_y_graph_fires_on_multiple_stagnating_edges(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    high_stagnation_config: ResolvedConfig,
    make_history_with_arc_stats,
):
    # e1 / e3 が両条件成立、e2 は不成立
    # e1 / e3 はともに M 分以上の先行警戒状態を保持しており、両方発火する
    e1, _e2, e3 = y_graph_edge_ids
    history, observations = _both_satisfied_setup(
        y_graph_edge_ids,
        stagnating_indices={0, 2},
        base_time=base_time,
        make_history_with_arc_stats=make_history_with_arc_stats,
    )
    previous = DetectionState(
        arc_watch_states=(
            ArcWatchState(
                edge_id=e1,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=6),
            ),
            ArcWatchState(
                edge_id=e3,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=base_time - timedelta(minutes=6),
            ),
        )
    )

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert set(result.triggered_edges) == {e1, e3}
    assert len(result.triggered_edges) == 2  # 重複なし
