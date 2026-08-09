"""Tests for the stagnation component of the combined (AND) trigger

停滞警戒（(a)）と組合せ発火テスト

停滞警戒 (a) は 2 条件からなり、M 分以上継続したとき established となる:
  (a).1 パーセンタイル:  ``s >= p90``（p90 が None なら省略＝縮退）
  (a).2 相対増分:        ``(s - recent_ma) / (baseline + eps) >= beta``
        recent_ma は ``window_series.stagnation_samples`` の平均、
        baseline は ``ArcHistoryStat.baseline_stagnation``（別の役割の値）

established は片方だけでは成立せず、両条件（p90 欠損時は (a).2 のみ）が M 分継続した
ときに成立する。継続は先行 ``ArcWatchState.stagnation_watch_since`` で計時する。

発火は組合せ（AND）:
  - ライン有り: ``established AND demand_warning`` で発火
  - ライン無し: ``established`` 単独で縮退発火（DEGRADED_COMBINED_TRIGGER 警告）
"""

from datetime import UTC, datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import (
    DetectionWarningCode,
    HighStagnationEvidence,
    SurgeEvidence,
)
from flow_control.detection.state import (
    ArcDemandDigestEntry,
    ArcWatchState,
    DetectionState,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import EdgeID, FlowDirection, Graph
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from flow_control.domain.observations import ArcStagnation, Observations

_TS = datetime(2026, 1, 1, tzinfo=UTC)


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
# 警戒状態（ArcWatchState）の生成: 各条件の成立/不成立
# ---------------------------------------------------------------------------


def test_records_watch_when_only_percentile_breached(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
):
    # stagnation=10, p90=5 → (a).1 成立
    # recent_ma=9, baseline=5 → (10-9)/5=0.2 < 1.0 で (a).2 不成立
    history = make_history((edge_id, 5.0, 9.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=10.0)

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
    make_history,
):
    # stagnation=15, p90=20 → (a).1 不成立
    # recent_ma=5, baseline=5 → (15-5)/5=2.0 >= 1.0 で (a).2 成立
    history = make_history((edge_id, 20.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)

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
    make_history,
):
    # stagnation=1, p90=20, recent_ma=5, baseline=5 → どちらも不成立
    history = make_history((edge_id, 20.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=1.0)

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


@pytest.mark.parametrize(
    ("stagnation", "expect_delta"),
    [
        (9.0, False),  # (9-0)/10 = 0.9 < 1.0
        (11.0, True),  # (11-0)/10 = 1.1 >= 1.0
    ],
)
def test_delta_relative_threshold_boundary(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    stagnation: float,
    expect_delta: bool,
):
    # (a).2 は (s - recent_ma)/(baseline + eps) >= beta の相対判定
    # recent_ma=0, baseline=10, beta=1.0 → 閾値は s>=10
    # p90 は十分高くして (a).1 は成立させない（delta フラグのみ検証）
    history = make_history((edge_id, 100.0, 0.0, 10.0))
    observations = make_stagnation_observation(
        edge_id, observed_at=base_time, stagnation=stagnation
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
    if expect_delta:
        assert watch is not None
        assert watch.delta_breached is True
    else:
        # どちらの条件も満たさないため警戒状態は生成されない
        assert watch is None


def test_records_watch_start_when_both_first_become_satisfied(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
):
    # 先行警戒なし、今回両条件を初めて満たす
    # → 発火せず（継続時間=0）、stagnation_watch_since=now で警戒を新規記録
    history = make_history((edge_id, 5.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)

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


def test_records_watch_when_both_satisfied_but_duration_short(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
):
    # 両条件成立、先行 watch_since = now - 1 分（M=5 分未満）
    # → established に至らず発火せず、警戒（継続計時）を保持する
    history = make_history((edge_id, 5.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
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
    # 継続計時は先行値を引き継ぐ
    assert watch.stagnation_watch_since == base_time - timedelta(minutes=1)


def test_clears_watch_when_conditions_no_longer_met(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
):
    # 先行警戒あり、今回は両条件とも不成立 → 発火せず、警戒は解除される
    history = make_history((edge_id, 20.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=1.0)
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
    make_history,
):
    # 履歴は揃っているが観測に ArcStagnation が無い → 評価不能、発火も警戒生成もしない
    history = make_history((edge_id, 5.0, 5.0, 5.0))
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
    # 観測は揃っているが履歴統計が無い
    # → p90 欠損で (a).1 は縮退、recent_ma も無く (a).2 も評価不能 → 発火も警戒もなし
    history = HistoryDigest()
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=10.0)

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
# 組合せ発火（established AND demand_warning）とラインなし縮退発火
# ---------------------------------------------------------------------------


def test_combined_fires_with_line_surge(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
):
    # established 停滞 ＋ ライン急増 → 組合せ発火（縮退ではない）
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
    assert result.fired_triggers[0].kind == QueuedTriggerKind.HIGH_STAGNATION
    # ラインが存在する正規発火のため縮退警告は付かない
    assert result.warnings == ()
    stag = [e for e in result.evidences if isinstance(e, HighStagnationEvidence)]
    assert len(stag) == 1
    assert stag[0].percentile_threshold == 5.0


def test_no_fire_when_established_but_no_demand_and_line_present(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_stagnation_observation,
    make_established_watch,
):
    # established だがラインは平坦（急増なし）・需要超過も無効 → demand_warning 偽で非発火
    # ラインが存在するため縮退もしない。警戒は保持される（AND 否定）
    flat_line = make_line_samples(base_time, sample_count=11, start_value=100.0, slope_per_min=0.0)
    history = make_history((edge_id, 5.0, 5.0, 5.0), flow={edge_id: flat_line})
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
    previous = DetectionState(arc_watch_states=(make_established_watch(edge_id, base_time),))

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == ()
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.stagnation_watch_since is not None


def test_degraded_fire_when_no_line_and_established(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    make_established_watch,
):
    # ラインが全く無いエッジは established 単独で縮退発火し、DEGRADED_COMBINED_TRIGGER を積む
    history = make_history((edge_id, 5.0, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
    previous = DetectionState(arc_watch_states=(make_established_watch(edge_id, base_time),))

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == (edge_id,)
    assert result.fired_triggers[0].kind == QueuedTriggerKind.HIGH_STAGNATION
    codes = {w.code for w in result.warnings}
    assert DetectionWarningCode.DEGRADED_COMBINED_TRIGGER in codes
    # 縮退発火では急増根拠は付かない
    assert [e for e in result.evidences if isinstance(e, SurgeEvidence)] == []


def test_p90_missing_uses_delta_only_and_degraded_fires(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    make_established_watch,
):
    # p90 欠損 → (a).1 省略、(a).2 のみで established。ラインなしで縮退発火する
    # p90 が無いため HighStagnationEvidence は付与されない
    history = make_history((edge_id, None, 5.0, 5.0))
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
    previous = DetectionState(arc_watch_states=(make_established_watch(edge_id, base_time),))

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == (edge_id,)
    assert [e for e in result.evidences if isinstance(e, HighStagnationEvidence)] == []
    codes = {w.code for w in result.warnings}
    assert DetectionWarningCode.DEGRADED_COMBINED_TRIGGER in codes


def test_fires_on_demand_excess(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_stagnation_observation,
    make_established_watch,
):
    # established 停滞 ＋ 需要超過 (b).2（ρ̂ = λ̂/(μ̂+eps) > theta_demand）→ 組合せ発火
    # ラインは平坦で急増しないため、発火根拠は需要超過側
    flat_line = tuple((base_time - timedelta(minutes=10 - i), 100.0) for i in range(11))
    window = ArcWindowSeries(
        edge_id=edge_id,
        flow_samples=flat_line,
        stagnation_samples=((_TS, 5.0),),
        directional_flow_samples=((FlowDirection.A_TO_B, ((_TS, 10.0),)),),
    )
    history = HistoryDigest(
        arc_stats=(ArcHistoryStat(edge_id=edge_id, p90_stagnation=5.0, baseline_stagnation=5.0),),
        window_series=(window,),
    )
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),),
        # λ̂ = 100, μ̂ = 10 → ρ̂ = 10 > theta_demand=2
        arc_demand_digest=(ArcDemandDigestEntry(edge_id=edge_id, demand=100.0),),
    )
    config = ResolvedConfig(
        surge_rate_threshold_percent_per_min=1_000.0,  # 急増は成立させない
        high_stagnation_duration_min=5.0,
        beta=1.0,
        theta_demand=2.0,
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=config,
    )

    assert result.triggered_edges == (edge_id,)
    assert result.fired_triggers[0].kind == QueuedTriggerKind.HIGH_STAGNATION
    # 需要超過での発火のため急増根拠は付かない
    assert [e for e in result.evidences if isinstance(e, SurgeEvidence)] == []
    # 発火根拠に停滞（p90 あり）が含まれる
    assert [e for e in result.evidences if isinstance(e, HighStagnationEvidence)]


def test_demand_excess_disabled_without_theta_demand(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    make_stagnation_observation,
    make_established_watch,
):
    # theta_demand 未設定なら需要超過は無効。established＋平坦ライン→非発火
    flat_line = tuple((base_time - timedelta(minutes=10 - i), 100.0) for i in range(11))
    window = ArcWindowSeries(
        edge_id=edge_id,
        flow_samples=flat_line,
        stagnation_samples=((_TS, 5.0),),
        directional_flow_samples=((FlowDirection.A_TO_B, ((_TS, 10.0),)),),
    )
    history = HistoryDigest(
        arc_stats=(ArcHistoryStat(edge_id=edge_id, p90_stagnation=5.0, baseline_stagnation=5.0),),
        window_series=(window,),
    )
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=15.0)
    previous = DetectionState(
        arc_watch_states=(make_established_watch(edge_id, base_time),),
        arc_demand_digest=(ArcDemandDigestEntry(edge_id=edge_id, demand=100.0),),
    )
    config = ResolvedConfig(
        surge_rate_threshold_percent_per_min=1_000.0,
        high_stagnation_duration_min=5.0,
        beta=1.0,
        theta_demand=None,  # 需要超過を無効化
    )

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=config,
    )

    assert result.triggered_edges == ()


# ---------------------------------------------------------------------------
# Y 型グラフ (3 エッジ): 複数エッジでの established 縮退発火
# ---------------------------------------------------------------------------


def _stagnation_setup(
    edge_ids: tuple[EdgeID, ...],
    stagnating_indices: set[int],
    base_time: datetime,
    make_history,
):
    """指定インデックスは両条件成立、他は不成立となるライン無し入力を返す

    ライン無しのため established なエッジは縮退発火する。
    """
    specs: list[tuple[EdgeID, float | None, float | None, float | None]] = []
    stagnations: list[ArcStagnation] = []
    for i, eid in enumerate(edge_ids):
        if i in stagnating_indices:
            specs.append((eid, 5.0, 5.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=15.0))
        else:
            specs.append((eid, 20.0, 5.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=1.0))
    history = make_history(*specs)
    observations = Observations(observed_at=base_time, arc_stagnations=tuple(stagnations))
    return history, observations


def test_y_graph_no_trigger_when_all_edges_calm(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    high_stagnation_config: ResolvedConfig,
    make_history,
):
    history, observations = _stagnation_setup(y_graph_edge_ids, set(), base_time, make_history)

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
    make_history,
    make_established_watch,
    stagnating_index: int,
):
    # 1 本のみ両条件成立で M 分継続 → 縮退発火（ライン無し）
    history, observations = _stagnation_setup(
        y_graph_edge_ids, {stagnating_index}, base_time, make_history
    )
    target = y_graph_edge_ids[stagnating_index]
    previous = DetectionState(arc_watch_states=(make_established_watch(target, base_time),))

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
    make_history,
    make_established_watch,
):
    e1, _e2, e3 = y_graph_edge_ids
    history, observations = _stagnation_setup(y_graph_edge_ids, {0, 2}, base_time, make_history)
    previous = DetectionState(
        arc_watch_states=(
            make_established_watch(e1, base_time),
            make_established_watch(e3, base_time),
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
