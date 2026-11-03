"""Tests for the stagnation component of the combined (AND) trigger

停滞警戒（(a)）と組合せ発火テスト

停滞警戒 (a) は 2 条件からなり、M 分以上継続したとき established となる:
  (a).1 パーセンタイル:  ``s >= p90``（p90 が None なら省略＝縮退）
  (a).2 相対増分:        ``(s - recent_ma) / (baseline + eps) >= beta``
        recent_ma は ``window_series.stagnation_samples`` の平均（なければ baseline）、
        baseline は ``ArcHistoryStat.baseline_stagnation``（なければ窓の平均）。
        どちらもなければ (a).2 は判定不能で、停滞警戒は成立しない

established は片方だけでは成立せず、両条件（p90 欠損時は (a).2 のみ）が M 分継続した
ときに成立する。継続は先行 ``ArcWatchState.stagnation_watch_since`` で計時する。

発火は組合せ（AND）: ``established AND demand_warning`` で発火する。
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import (
    HighStagnationEvidence,
    PartialCombinedTrigger,
    SurgeEvidence,
)
from flow_control.detection.state import (
    ArcWatchState,
    DetectionState,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import EdgeID, Graph
from flow_control.domain.element_state import Judgement, assess_elements
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import ArcStagnation, ConfidenceFlag, Observations

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
        element_states=assess_elements(graph, observations, history, server_time),
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


def test_history_stat_missing_pauses_the_watch_without_firing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_established_watch,
):
    # 観測は揃っているが履歴統計も窓も無い
    # → 基準停滞量が決まらず (a).2 は判定不能 → 発火せず、継続中の警戒はそのまま持ち越す
    history = HistoryDigest()
    observations = make_stagnation_observation(edge_id, observed_at=base_time, stagnation=10.0)
    previous = DetectionState(arc_watch_states=(make_established_watch(edge_id, base_time),))

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=high_stagnation_config,
    )

    assert result.triggered_edges == ()
    assert result.new_state.arc_watch_states == (
        replace(previous.arc_watch_states[0], stagnation_paused_at=base_time),
    )


@pytest.mark.parametrize(
    ("flag", "observed_ago_min"),
    [(ConfidenceFlag.HOLD, 0), (ConfidenceFlag.OK, 3)],
    ids=["hold", "stale"],
)
def test_undeterminable_cycle_pauses_the_persistence_timer(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_combined_firing,
    flag: ConfidenceFlag,
    observed_ago_min: int,
):
    started = base_time - timedelta(minutes=5)
    history = make_history((edge_id, 5.0, 5.0, 5.0))
    first = _run(
        graph=basic_graph,
        history=history,
        observations=Observations(
            observed_at=started, arc_stagnations=(ArcStagnation(edge_id, 15.0),)
        ),
        previous_state=DetectionState(),
        server_time=started,
        config=surge_config,
    )
    paused_at = base_time - timedelta(minutes=2)
    paused = _run(
        graph=basic_graph,
        history=history,
        observations=Observations(
            observed_at=paused_at - timedelta(minutes=observed_ago_min),
            arc_stagnations=(ArcStagnation(edge_id, 1.0, confidence_flag=flag),),
        ),
        previous_state=first.new_state,
        server_time=paused_at,
        config=surge_config,
    )
    resumed_history, resumed_observations, _ = make_combined_firing(edge_id, base_time)
    resumed = _run(
        graph=basic_graph,
        history=resumed_history,
        observations=resumed_observations,
        previous_state=paused.new_state,
        server_time=base_time,
        config=surge_config,
    )

    assert paused.new_state.watch_state_of(edge_id) == ArcWatchState(
        edge_id,
        percentile_breached=True,
        delta_breached=True,
        stagnation_watch_since=started,
        stagnation_paused_at=paused_at,
    )
    assert resumed.triggered_edges == ()
    resumed_watch = resumed.new_state.watch_state_of(edge_id)
    assert resumed_watch is not None
    assert resumed_watch.stagnation_watch_since == base_time - timedelta(minutes=3)
    assert resumed_watch.stagnation_paused_at is None


_HOLDS = "holds"
_UNDETERMINABLE = "undeterminable"
_CALM = "calm"
_INVALID = "invalid"
_UNOBSERVED = "unobserved"


def _firing_minutes(
    *,
    graph: Graph,
    edge_id: EdgeID,
    config: ResolvedConfig,
    make_combined_firing,
    cycles: list[tuple[int, str]],
) -> list[int]:
    state = DetectionState()
    fired: list[int] = []
    for minute, kind in cycles:
        now = _TS + timedelta(minutes=minute)
        history, observations, _ = make_combined_firing(
            edge_id, now, stagnation=1.0 if kind == _CALM else 15.0
        )
        if kind == _UNDETERMINABLE:
            observations = Observations(
                observed_at=now,
                arc_stagnations=(
                    ArcStagnation(edge_id, 15.0, confidence_flag=ConfidenceFlag.HOLD),
                ),
            )
        elif kind == _INVALID:
            observations = Observations(
                observed_at=now,
                arc_stagnations=(
                    ArcStagnation(edge_id, 15.0, confidence_flag=ConfidenceFlag.INVALID),
                ),
            )
        elif kind == _UNOBSERVED:
            observations = Observations(observed_at=now)
        result = _run(
            graph=graph,
            history=history,
            observations=observations,
            previous_state=state,
            server_time=now,
            config=config,
        )
        state = result.new_state
        if edge_id in result.triggered_edges:
            fired.append(minute)
    return fired


def test_unobserved_gap_does_not_count_toward_persistence(
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
):
    cycles = [(0, _HOLDS), *((m, _UNDETERMINABLE) for m in range(1, 10)), (10, _HOLDS)]

    assert (
        _firing_minutes(
            graph=basic_graph,
            edge_id=edge_id,
            config=surge_config,
            make_combined_firing=make_combined_firing,
            cycles=cycles,
        )
        == []
    )


def test_persistence_accumulates_only_observed_holding_across_a_pause(
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
):
    cycles = [
        *((m, _HOLDS) for m in range(4)),
        (4, _UNDETERMINABLE),
        (5, _UNDETERMINABLE),
        *((m, _HOLDS) for m in range(6, 10)),
    ]

    assert _firing_minutes(
        graph=basic_graph,
        edge_id=edge_id,
        config=surge_config,
        make_combined_firing=make_combined_firing,
        cycles=cycles,
    ) == [7]


@pytest.mark.parametrize(
    "gap",
    [
        [(m, _UNDETERMINABLE) for m in range(1, 8)],
        [(1, _UNDETERMINABLE)],
    ],
    ids=["expires_while_paused", "expires_on_resume"],
)
def test_pause_longer_than_m_restarts_the_persistence_timer(
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
    gap: list[tuple[int, str]],
):
    cycles = [(0, _HOLDS), *gap, *((m, _HOLDS) for m in range(8, 15))]

    assert _firing_minutes(
        graph=basic_graph,
        edge_id=edge_id,
        config=surge_config,
        make_combined_firing=make_combined_firing,
        cycles=cycles,
    ) == [13]


@pytest.mark.parametrize("breaking", [_CALM, _INVALID, _UNOBSERVED])
def test_breaking_cycle_after_a_pause_restarts_the_persistence_timer(
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
    breaking: str,
):
    cycles = [
        *((m, _HOLDS) for m in range(3)),
        (3, _UNDETERMINABLE),
        (4, breaking),
        *((m, _HOLDS) for m in range(5, 12)),
    ]

    assert _firing_minutes(
        graph=basic_graph,
        edge_id=edge_id,
        config=surge_config,
        make_combined_firing=make_combined_firing,
        cycles=cycles,
    ) == [10]


@pytest.mark.parametrize("invalid", [True, False], ids=["invalid", "unobserved"])
def test_out_of_scope_cycle_resets_the_persistence_timer(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_history,
    make_combined_firing,
    invalid: bool,
):
    started = base_time - timedelta(minutes=5)
    history = make_history((edge_id, 5.0, 5.0, 5.0))
    first = _run(
        graph=basic_graph,
        history=history,
        observations=Observations(
            observed_at=started, arc_stagnations=(ArcStagnation(edge_id, 15.0),)
        ),
        previous_state=DetectionState(),
        server_time=started,
        config=surge_config,
    )
    reset_at = base_time - timedelta(minutes=2)
    reset = _run(
        graph=basic_graph,
        history=history,
        observations=Observations(
            observed_at=reset_at,
            arc_stagnations=(
                (ArcStagnation(edge_id, 1.0, confidence_flag=ConfidenceFlag.INVALID),)
                if invalid
                else ()
            ),
        ),
        previous_state=first.new_state,
        server_time=reset_at,
        config=surge_config,
    )
    resumed_history, resumed_observations, _ = make_combined_firing(edge_id, base_time)
    resumed = _run(
        graph=basic_graph,
        history=resumed_history,
        observations=resumed_observations,
        previous_state=reset.new_state,
        server_time=base_time,
        config=surge_config,
    )

    assert first.new_state.watch_state_of(edge_id) is not None
    assert reset.new_state.watch_state_of(edge_id) is None
    assert resumed.triggered_edges == ()


@pytest.mark.parametrize("scale", [0.1, 1.0, 10.0])
def test_window_mean_is_the_baseline_when_history_has_none(
    scale: float,
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    make_established_watch,
):
    history = make_history((edge_id, None, 5.0 * scale, None))
    previous = DetectionState(arc_watch_states=(make_established_watch(edge_id, base_time),))

    def run(stagnation: float):
        return _run(
            graph=basic_graph,
            history=history,
            observations=make_stagnation_observation(
                edge_id, observed_at=base_time, stagnation=stagnation * scale
            ),
            previous_state=previous,
            server_time=base_time,
            config=high_stagnation_config,
        )

    calm = run(8.0)
    assert calm.warnings == ()
    assert calm.new_state.watch_state_of(edge_id) is None
    assert run(15.0).warnings == (PartialCombinedTrigger(edge_id, Judgement.HIGH_STAGNATION),)


def test_history_baseline_replaces_recent_average_when_window_is_empty(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    make_established_watch,
):
    history = make_history((edge_id, 5.0, None, 5.0))
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

    assert result.warnings == (PartialCombinedTrigger(edge_id, Judgement.HIGH_STAGNATION),)


# ---------------------------------------------------------------------------
# 組合せ発火（established AND demand_warning）
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
    # established だがラインは平坦（急増なし） → demand_warning 偽で非発火
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


def test_no_line_holds_stagnation_without_firing(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    high_stagnation_config: ResolvedConfig,
    make_stagnation_observation,
    make_history,
    make_established_watch,
):
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

    assert result.triggered_edges == ()
    assert result.warnings == (PartialCombinedTrigger(edge_id, Judgement.HIGH_STAGNATION),)
    assert [e for e in result.evidences if isinstance(e, SurgeEvidence)] == []
    watch = result.new_state.watch_state_of(edge_id)
    assert watch is not None
    assert watch.stagnation_watch_since is not None


def test_p90_missing_uses_delta_only(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
    surge_config: ResolvedConfig,
    make_combined_firing,
):
    history, observations, previous = make_combined_firing(edge_id, base_time, p90=None)

    result = _run(
        graph=basic_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == (edge_id,)
    assert [e for e in result.evidences if isinstance(e, HighStagnationEvidence)] == []


# ---------------------------------------------------------------------------
# Y 型グラフ (3 エッジ): 複数エッジでの組合せ発火
# ---------------------------------------------------------------------------


def _stagnation_setup(
    edge_ids: tuple[EdgeID, ...],
    stagnating_indices: set[int],
    base_time: datetime,
    make_history,
    make_line_samples,
):
    """指定インデックスは両条件成立、他は不成立となる入力を返す。全エッジのラインは急増する"""
    specs: list[tuple[EdgeID, float | None, float | None, float | None]] = []
    stagnations: list[ArcStagnation] = []
    for i, eid in enumerate(edge_ids):
        if i in stagnating_indices:
            specs.append((eid, 5.0, 5.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=15.0))
        else:
            specs.append((eid, 20.0, 5.0, 5.0))
            stagnations.append(ArcStagnation(edge_id=eid, stagnation=1.0))
    line = make_line_samples(base_time, sample_count=11, start_value=0.0, slope_per_min=10.0)
    history = make_history(*specs, flow=dict.fromkeys(edge_ids, line))
    observations = Observations(observed_at=base_time, arc_stagnations=tuple(stagnations))
    return history, observations


def test_y_graph_no_trigger_when_all_edges_calm(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    high_stagnation_config: ResolvedConfig,
    make_history,
    make_line_samples,
):
    history, observations = _stagnation_setup(
        y_graph_edge_ids, set(), base_time, make_history, make_line_samples
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
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
    stagnating_index: int,
):
    history, observations = _stagnation_setup(
        y_graph_edge_ids, {stagnating_index}, base_time, make_history, make_line_samples
    )
    target = y_graph_edge_ids[stagnating_index]
    previous = DetectionState(arc_watch_states=(make_established_watch(target, base_time),))

    result = _run(
        graph=y_graph,
        history=history,
        observations=observations,
        previous_state=previous,
        server_time=base_time,
        config=surge_config,
    )

    assert result.triggered_edges == (target,)


def test_y_graph_fires_on_multiple_stagnating_edges(
    base_time: datetime,
    y_graph: Graph,
    y_graph_edge_ids: tuple[EdgeID, EdgeID, EdgeID],
    surge_config: ResolvedConfig,
    make_history,
    make_line_samples,
    make_established_watch,
):
    e1, _e2, e3 = y_graph_edge_ids
    history, observations = _stagnation_setup(
        y_graph_edge_ids, {0, 2}, base_time, make_history, make_line_samples
    )
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
        config=surge_config,
    )

    assert set(result.triggered_edges) == {e1, e3}
    assert len(result.triggered_edges) == 2  # 重複なし
