from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from ..domain import EdgeID, Graph, NodeID
from ..domain.enums import CurrentDirection, FlowDirection, ObservationType
from ..domain.graph import Edge
from ..domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from ..domain.observations import ArcStagnation, ConfidenceFlag, Observations
from ..domain.references import Reference
from .config import ResolvedConfig
from .diagnostics import (
    DetectionWarning,
    DetectionWarningCode,
    HighStagnationEvidence,
    PunctureEvidence,
    QueueDiversityEvidence,
    QueueExpiredEvidence,
    QueueScoreEvidence,
    SurgeEvidence,
    TriggerEvidence,
)
from .state import (
    ArcWatchState,
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
    RetriggerEntry,
    WarmupState,
)

EPSILON_FLOW = 1e-6

_TARGET_PREFIX_EDGE = "edge:"
_TARGET_PREFIX_NODE = "node:"

# evaluate_cooldown の watched_edges 既定値（パラメータ既定式での呼び出しを避ける）
_NO_WATCHED_EDGES: frozenset[EdgeID] = frozenset()


class EventKind(str, Enum):
    DANGER_FLAG_UP = "DANGER_FLAG_UP"
    DANGER_FLAG_DOWN = "DANGER_FLAG_DOWN"
    DIRECTION_SWITCH = "DIRECTION_SWITCH"
    ADD_EDGE = "ADD_EDGE"
    ADD_NODE = "ADD_NODE"
    DISABLE = "DISABLE"
    ENABLE = "ENABLE"
    SCHEDULED_INFLOW = "SCHEDULED_INFLOW"
    SCHEDULED_ATTR_CHANGE = "SCHEDULED_ATTR_CHANGE"
    # 観測点構成の変更（追加・故障・交換）。受信対象はウォームアップを再開始し、
    # 当該リクエストでは履歴統計を使わず参照値フォールバックへ切替える
    SENSOR_SET_CHANGED = "SENSOR_SET_CHANGED"


@dataclass(frozen=True)
class Event:
    """
    ``"edge:<edge_id>"``: アーク対象
    ``"node:<node_id>"``: ノード対象
    """

    kind: EventKind
    target_id: str
    occurred_at: datetime
    # イベント付帯情報（例: SCHEDULED_INFLOW.expected_count）。None = 付帯情報なし
    params: tuple[tuple[str, object], ...] | None = None


@dataclass(frozen=True)
class MetricTriggerDetectionResult:
    triggered_edges: tuple[EdgeID, ...]
    fired_triggers: tuple[FiredTrigger, ...]
    evidences: tuple[TriggerEvidence, ...]
    new_state: DetectionState
    warnings: tuple[DetectionWarning, ...] = ()


@dataclass(frozen=True)
class _StagnationEval:
    # 停滞警戒 (a) の評価結果
    established: bool  # 両条件（p90 欠損時は (a).2 のみ）が M 分以上継続
    watch_since: datetime | None  # 条件継続の計時開始時刻（条件が破れれば None）
    percentile_breached: bool  # (a).1
    delta_breached: bool  # (a).2


def detect_metric_triggers(
    graph: Graph,
    observations: Observations,
    history_digest: HistoryDigest,
    previous_state: DetectionState,
    server_time: datetime,
    config: ResolvedConfig,
    references: Reference | None = None,
) -> MetricTriggerDetectionResult:
    triggered_edges: list[EdgeID] = []
    fired_triggers: list[FiredTrigger] = []
    evidences: list[TriggerEvidence] = []
    warnings: list[DetectionWarning] = []
    new_watch_states: list[ArcWatchState] = []

    for edge in graph.enabled_edges():
        # ウォームアップ中の対象はトリガー判定を停止
        if previous_state.is_in_warmup(_edge_target_key(edge.edge_id), server_time):
            continue

        observed_stagnation = observations.stagnation_of(edge.edge_id)
        history_stat = history_digest.stat_of(edge.edge_id)
        window = history_digest.window_series_of(edge.edge_id)
        previous_watch = previous_state.watch_state_of(edge.edge_id)

        # ── 需要警戒 (b).1 急増 ──
        # ライン通過（VECTOR arc_flows のエッジ合算）を入力とする。
        # ラインがないエッジでは停滞プロキシ傾きで代替する（SURGE_PROXY_FALLBACK）。
        line_flow_now = _current_line_flow(observations, edge.edge_id)
        line_samples = window.flow_samples if window is not None else ()
        line_present = bool(line_samples) or line_flow_now is not None
        surge_is_proxy = False
        if line_present:
            surge_rate = _slope_percent_per_min(
                _line_series(
                    line_samples,
                    line_flow_now,
                    observations.observed_at,
                    edge.time_resolution_s,
                    config.surge_evaluate_window_minute,
                    server_time,
                )
            )
        else:
            surge_rate = _slope_percent_per_min(
                _proxy_series(
                    window,
                    edge.time_resolution_s,
                    config.surge_evaluate_window_minute,
                    server_time,
                )
            )
            surge_is_proxy = surge_rate is not None
        surge_threshold = config.surge_rate_threshold_percent_per_min
        surge_breached = surge_rate is not None and surge_rate > surge_threshold

        # ── 需要警戒 (b).2 需要超過 ──
        # ρ̂ = λ̂ /(μ̂ + ε0)。λ̂ は前回リクエストの Forecasting 由来（arc_demand_digest）。
        lambda_hat = previous_state.demand_digest_of(edge.edge_id)
        mu_hat = _downstream_outflow_average(window, edge.current_direction)
        rho_hat: float | None = None
        demand_excess_breached = False
        if (
            config.theta_demand is not None
            and lambda_hat is not None
            and mu_hat is not None
        ):
            rho_hat = lambda_hat / (mu_hat + config.epsilon_0)
            demand_excess_breached = rho_hat > config.theta_demand

        demand_warning = surge_breached or demand_excess_breached

        # ── 停滞警戒 (a) ──
        baseline = _resolve_baseline(history_stat, edge, references, config)
        recent_ma = _recent_stagnation_average(window)
        p90 = history_stat.p90_stagnation if history_stat is not None else None
        stag = _evaluate_stagnation(
            observed_stagnation,
            p90,
            recent_ma,
            baseline,
            config.beta,
            previous_watch,
            config.high_stagnation_duration_min,
            server_time,
            config.epsilon_0,
        )

        demand_watch_since = _advance_watch_since(
            previous_watch.demand_watch_since if previous_watch is not None else None,
            demand_warning,
            server_time,
        )

        # ── 組合せ発火 (c) と縮退（ラインなし → 停滞警戒単独） ──
        degraded = False
        fired = False
        if stag.established:
            if line_present:
                fired = demand_warning
            else:
                fired = True
                degraded = True

        if surge_is_proxy:
            warnings.append(
                DetectionWarning(
                    code=DetectionWarningCode.SURGE_PROXY_FALLBACK,
                    occurred_at=server_time,
                    edge_id=edge.edge_id,
                )
            )

        if fired:
            stag_ratio = _stagnation_ratio(
                observed_stagnation, p90, recent_ma, baseline, config.beta, config.epsilon_0
            )
            demand_ratio = (
                None
                if degraded
                else _demand_ratio(
                    surge_breached,
                    surge_rate,
                    surge_threshold,
                    demand_excess_breached,
                    rho_hat,
                    config.theta_demand,
                )
            )
            score = stag_ratio if demand_ratio is None else max(stag_ratio, demand_ratio)
            fired_triggers.append(
                FiredTrigger(
                    kind=QueuedTriggerKind.HIGH_STAGNATION,
                    fired_at=server_time,
                    origin_edge_id=edge.edge_id,
                    score=score,
                    snapshot_ref=observations.snapshot_ref,
                )
            )
            triggered_edges.append(edge.edge_id)
            if observed_stagnation is not None and p90 is not None:
                evidences.append(
                    HighStagnationEvidence(
                        edge_id=edge.edge_id,
                        occurred_at=server_time,
                        stagnation=observed_stagnation.stagnation,
                        percentile_threshold=p90,
                        duration_min=config.high_stagnation_duration_min,
                    )
                )
            if surge_breached and not surge_is_proxy and surge_rate is not None:
                evidences.append(
                    SurgeEvidence(
                        edge_id=edge.edge_id,
                        occurred_at=server_time,
                        rate_percent_per_min=surge_rate,
                        threshold_percent_per_min=surge_threshold,
                    )
                )
            if degraded:
                warnings.append(
                    DetectionWarning(
                        code=DetectionWarningCode.DEGRADED_COMBINED_TRIGGER,
                        occurred_at=server_time,
                        edge_id=edge.edge_id,
                    )
                )
            # 発火 → クールタイム開始のため警戒状態はリセット（保持しない）
        else:
            next_watch = _build_watch_state(
                edge.edge_id, stag, surge_breached, demand_excess_breached, demand_watch_since
            )
            if next_watch is not None:
                new_watch_states.append(next_watch)

        # ── パンクトリガー (d)（前処理 P・独立） ──
        _detect_puncture(
            edge, observations, config, server_time, triggered_edges, fired_triggers, evidences
        )

    new_state = replace(previous_state, arc_watch_states=tuple(new_watch_states))

    return MetricTriggerDetectionResult(
        triggered_edges=tuple(triggered_edges),
        fired_triggers=tuple(fired_triggers),
        evidences=tuple(evidences),
        new_state=new_state,
        warnings=tuple(warnings),
    )


def _current_line_flow(observations: Observations, edge_id: EdgeID) -> float | None:
    # エッジ合算のライン通過（両方向 arc_flows の和）。ラインなし／全て INVALID なら None
    total = 0.0
    found = False
    for arc_flow in observations.arc_flows:
        if arc_flow.edge_id == edge_id and arc_flow.confidence_flag != ConfidenceFlag.INVALID:
            total += arc_flow.flow_rate
            found = True
    return total if found else None


def _line_series(
    line_samples: tuple[tuple[datetime, float], ...],
    line_flow_now: float | None,
    observed_at: datetime,
    edge_resolution_s: float,
    evaluate_window_minute: float,
    server_time: datetime,
) -> list[tuple[datetime, float]]:
    window_minute = evaluate_window_minute + edge_resolution_s / 60.0
    window_start_time = server_time - timedelta(minutes=window_minute)
    series = [(t, v) for (t, v) in line_samples if t >= window_start_time]
    if line_flow_now is not None and observed_at >= window_start_time:
        series.append((observed_at, line_flow_now))
    return series


def _proxy_series(
    window: ArcWindowSeries | None,
    edge_resolution_s: float,
    evaluate_window_minute: float,
    server_time: datetime,
) -> list[tuple[datetime, float]]:
    # ラインなし縮退：停滞プロキシ系列の傾きで急増を代替する
    if window is None:
        return []
    window_minute = evaluate_window_minute + edge_resolution_s / 60.0
    window_start_time = server_time - timedelta(minutes=window_minute)
    return [(t, v) for (t, v) in window.stagnation_samples if t >= window_start_time]


def _slope_percent_per_min(
    series: list[tuple[datetime, float]],
) -> float | None:
    # 最小二乗フィットの傾きを自己平均で正規化した変化率 %/分。算出不能なら None
    if len(series) < 2:
        return None
    (first_time, _) = series[0]
    xs = [(t - first_time).total_seconds() / 60.0 for (t, _) in series]
    ys = [v for (_, v) in series]
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    num = sum((x - x_mean) * (y - y_mean) for (x, y) in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den < EPSILON_FLOW or y_mean < EPSILON_FLOW:
        return None
    return (num / den / y_mean) * 100.0


def _downstream_outflow_average(
    window: ArcWindowSeries | None,
    current_direction: CurrentDirection,
) -> float | None:
    # 排出実績 μ̂_e：現在の流下方向のライン流出カウント直近平均
    if window is None or window.directional_flow_samples is None:
        return None
    wanted: FlowDirection | None
    if current_direction == CurrentDirection.A_TO_B:
        wanted = FlowDirection.A_TO_B
    elif current_direction == CurrentDirection.B_TO_A:
        wanted = FlowDirection.B_TO_A
    else:
        wanted = None  # BIDIRECTIONAL は両方向を合算平均する
    values: list[float] = []
    for direction, samples in window.directional_flow_samples:
        if wanted is None or direction == wanted:
            values.extend(v for (_, v) in samples)
    if not values:
        return None
    return statistics.mean(values)


def _resolve_baseline(
    history_stat: ArcHistoryStat | None,
    edge: Edge,
    references: Reference | None,
    config: ResolvedConfig,
) -> float:
    # (a).2 の基準停滞量 s̄_e：履歴 → 属性タグ別参照値 → config フォールバックの順で決定
    if history_stat is not None and history_stat.baseline_stagnation is not None:
        return history_stat.baseline_stagnation
    if references is not None:
        for tag in edge.attribute_tags:
            tag_ref = references.tag_reference_of(tag)
            if (
                tag_ref is not None
                and tag_ref.baseline_stagnation is not None
                and tag_ref.sample_count >= config.min_reference_sample_count
            ):
                return tag_ref.baseline_stagnation
    return config.fallback_baseline_stagnation


def _recent_stagnation_average(
    history_series: ArcWindowSeries | None,
) -> float | None:
    # (a).2 用の直近停滞プロキシ移動平均。stagnation_samples が空なら None
    if history_series is None or not history_series.stagnation_samples:
        return None
    return statistics.mean(v for (_, v) in history_series.stagnation_samples)


def _evaluate_stagnation(
    observed_stagnation: ArcStagnation | None,
    p90: float | None,
    recent_ma: float | None,
    baseline: float,
    beta: float,
    previous_watch: ArcWatchState | None,
    high_stagnation_duration_min: float,
    server_time: datetime,
    epsilon_0: float,
) -> _StagnationEval:
    if observed_stagnation is None:
        return _StagnationEval(False, None, False, False)

    stagnation = observed_stagnation.stagnation
    # (a).1: 観測停滞量が p90 以上（p90 欠損時は縮退で省略）
    percentile_available = p90 is not None
    percentile_breached = percentile_available and stagnation >= p90
    # (a).2: 相対増分が基準停滞量比で beta 以上
    delta_breached = (
        recent_ma is not None
        and (stagnation - recent_ma) / (baseline + epsilon_0) >= beta
    )

    condition_now = (
        (percentile_breached and delta_breached)
        if percentile_available
        else delta_breached
    )
    if not condition_now:
        # 条件が破れたら計時をリセット（フラグは診断用に返す）
        return _StagnationEval(False, None, percentile_breached, delta_breached)

    # 条件継続中：前サイクルから計時を引き継ぐ
    if previous_watch is not None and previous_watch.stagnation_watch_since is not None:
        watch_since = previous_watch.stagnation_watch_since
    else:
        watch_since = server_time
    elapsed_minutes = (server_time - watch_since).total_seconds() / 60.0
    established = elapsed_minutes >= high_stagnation_duration_min
    return _StagnationEval(established, watch_since, percentile_breached, delta_breached)


def _build_watch_state(
    edge_id: EdgeID,
    stag: _StagnationEval,
    surge_breached: bool,
    demand_excess_breached: bool,
    demand_watch_since: datetime | None,
) -> ArcWatchState | None:
    if not (
        stag.percentile_breached
        or stag.delta_breached
        or stag.watch_since is not None
        or surge_breached
        or demand_excess_breached
        or demand_watch_since is not None
    ):
        return None
    return ArcWatchState(
        edge_id=edge_id,
        percentile_breached=stag.percentile_breached,
        delta_breached=stag.delta_breached,
        stagnation_watch_since=stag.watch_since,
        surge_breached=surge_breached,
        demand_excess_breached=demand_excess_breached,
        demand_watch_since=demand_watch_since,
    )


def _advance_watch_since(
    previous_since: datetime | None,
    condition_now: bool,
    server_time: datetime,
) -> datetime | None:
    if not condition_now:
        return None
    return previous_since if previous_since is not None else server_time


def _stagnation_ratio(
    observed_stagnation: ArcStagnation | None,
    p90: float | None,
    recent_ma: float | None,
    baseline: float,
    beta: float,
    epsilon_0: float,
) -> float:
    # 組合せ発火の停滞系スコア。p90 ありは s/p90、縮退時は相対増分/β
    if observed_stagnation is None:
        return 1.0
    s = observed_stagnation.stagnation
    if p90 is not None and p90 > EPSILON_FLOW:
        return s / p90
    if recent_ma is not None and beta > EPSILON_FLOW:
        return ((s - recent_ma) / (baseline + epsilon_0)) / beta
    return 1.0


def _demand_ratio(
    surge_breached: bool,
    surge_rate: float | None,
    surge_threshold: float,
    demand_excess_breached: bool,
    rho_hat: float | None,
    theta_demand: float | None,
) -> float | None:
    # 組合せ発火の需要系スコア。急増・需要超過のうち成立したものの最大値
    candidates: list[float] = []
    if surge_breached and surge_rate is not None and surge_threshold > EPSILON_FLOW:
        candidates.append(surge_rate / surge_threshold)
    if (
        demand_excess_breached
        and rho_hat is not None
        and theta_demand is not None
        and theta_demand > EPSILON_FLOW
    ):
        candidates.append(rho_hat / theta_demand)
    return max(candidates) if candidates else None


def _detect_puncture(
    edge: Edge,
    observations: Observations,
    config: ResolvedConfig,
    server_time: datetime,
    triggered_edges: list[EdgeID],
    fired_triggers: list[FiredTrigger],
    evidences: list[TriggerEvidence],
) -> None:
    # スカラー型のパンク前処理。capacity_hint 未設定では発火しない（ノーハーム）
    if not config.puncture_trigger_enabled:
        return
    if edge.observation_type != ObservationType.SCALAR or edge.capacity_hint is None:
        return
    scalar = observations.scalar_flow_of(edge.edge_id)
    if scalar is None or scalar.confidence_flag == ConfidenceFlag.INVALID:
        return
    threshold = config.puncture_ratio_threshold * edge.capacity_hint
    if threshold <= EPSILON_FLOW or scalar.observed_count < threshold:
        return
    fired_triggers.append(
        FiredTrigger(
            kind=QueuedTriggerKind.PUNCTURE,
            fired_at=server_time,
            origin_edge_id=edge.edge_id,
            score=scalar.observed_count / threshold,
            snapshot_ref=observations.snapshot_ref,
        )
    )
    if edge.edge_id not in triggered_edges:
        triggered_edges.append(edge.edge_id)
    evidences.append(
        PunctureEvidence(
            edge_id=edge.edge_id,
            occurred_at=server_time,
            observed_count=scalar.observed_count,
            capacity_threshold=threshold,
        )
    )


@dataclass(frozen=True)
class ManualTriggerDetectionResult:
    triggered_edges: tuple[EdgeID, ...]
    triggered_nodes: tuple[NodeID, ...]


def detect_manual_triggers(
    events: tuple[Event, ...],
) -> ManualTriggerDetectionResult:
    triggered_edges: list[EdgeID] = []
    triggered_nodes: list[NodeID] = []
    seen_edges: set[EdgeID] = set()
    seen_nodes: set[NodeID] = set()

    for event in events:
        if event.kind != EventKind.DANGER_FLAG_UP:
            continue
        if event.target_id.startswith(_TARGET_PREFIX_EDGE):
            edge_id = EdgeID(event.target_id[len(_TARGET_PREFIX_EDGE) :])
            if edge_id not in seen_edges:
                seen_edges.add(edge_id)
                triggered_edges.append(edge_id)
        elif event.target_id.startswith(_TARGET_PREFIX_NODE):
            node_id = NodeID(event.target_id[len(_TARGET_PREFIX_NODE) :])
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                triggered_nodes.append(node_id)

    return ManualTriggerDetectionResult(
        triggered_edges=tuple(triggered_edges),
        triggered_nodes=tuple(triggered_nodes),
    )


class VerdictHint(str, Enum):
    TRIGGERED = "TRIGGERED"
    QUEUED = "QUEUED"
    SKIPPED_COOLDOWN = "SKIPPED_COOLDOWN"
    SKIPPED_WARMUP = "SKIPPED_WARMUP"
    NO_TRIGGER = "NO_TRIGGER"


@dataclass(frozen=True)
class FiredTrigger:
    kind: QueuedTriggerKind
    fired_at: datetime
    origin_edge_id: EdgeID | None = None
    origin_node_id: NodeID | None = None
    score: float = 1.0
    snapshot_ref: str | None = None  # 検出時の観測スナップショット識別子


@dataclass(frozen=True)
class CooldownDecision:
    verdict: VerdictHint
    triggered_edges: tuple[EdgeID, ...]
    triggered_nodes: tuple[NodeID, ...]
    new_state: DetectionState
    evidences: tuple[TriggerEvidence, ...] = ()
    # 発火副作用（cooldown_until 更新・キュー消化）を含まない遷移候補
    # 発火しない verdict では new_state と等価
    abort_state: DetectionState | None = None


def evaluate_cooldown(
    previous_state: DetectionState,
    fired_triggers: tuple[FiredTrigger, ...],
    server_time: datetime,
    config: ResolvedConfig,
    watched_edges: frozenset[EdgeID] = _NO_WATCHED_EDGES,
) -> CooldownDecision:
    # watched_edges: 現時点で停滞警戒（パーセンタイル超過または相対増分超過）を満たすエッジ集合（鮮度ガード用）
    danger_triggers = tuple(
        t for t in fired_triggers if t.kind == QueuedTriggerKind.DANGER
    )
    normal_triggers = tuple(
        t for t in fired_triggers if t.kind != QueuedTriggerKind.DANGER
    )

    if previous_state.is_in_cooldown(server_time):
        if danger_triggers:
            # 危険フラグはクールタイム中でも即時発火
            # abort: 発火副作用なし（cooldown・キュー据え置き，危険フラグはキューに積まない）
            decision = _fire(
                previous_state,
                server_time,
                config,
                previous_state.trigger_queue,
                fired_triggers,
            )
            return replace(decision, abort_state=previous_state)
        if normal_triggers:
            merged_queue = _merge_into_queue(
                previous_state.trigger_queue, normal_triggers
            )
            if _queue_exceeds_score(merged_queue, config) or _queue_is_diverse(
                merged_queue, config
            ):
                # スコア超過 or 多様性超過
                queue_evidences = _queue_fire_evidences(
                    merged_queue, config, server_time
                )
                decision = _fire(
                    previous_state,
                    server_time,
                    config,
                    merged_queue,
                    evidences=queue_evidences,
                )
                # abort: キュー追加は副作用でない（消化はしない）・cooldown 据え置き
                abort = replace(previous_state, trigger_queue=merged_queue)
                return replace(decision, abort_state=abort)
            queued_state = replace(previous_state, trigger_queue=merged_queue)
            return CooldownDecision(
                VerdictHint.QUEUED, (), (), queued_state, abort_state=queued_state
            )
        # クールタイム中，トリガーなし
        return CooldownDecision(
            VerdictHint.SKIPPED_COOLDOWN,
            (),
            (),
            previous_state,
            abort_state=previous_state,
        )

    # クールタイム外，新規トリガーがあれば発火（キュー残も統合）
    if fired_triggers:
        # abort: 発火トリガーはキューに積まない（再キューは finalize の責務）・cooldown 据え置き
        decision = _fire(
            previous_state,
            server_time,
            config,
            previous_state.trigger_queue,
            fired_triggers,
        )
        return replace(decision, abort_state=previous_state)

    # 新規トリガーなし・キュー残あり → 鮮度ガード付きの統合発火
    if previous_state.trigger_queue:
        if _queue_fresh(
            previous_state.trigger_queue, watched_edges, server_time, config
        ):
            # abort: キュー消化しない・cooldown 据え置き
            decision = _fire(
                previous_state,
                server_time,
                config,
                previous_state.trigger_queue,
            )
            return replace(decision, abort_state=previous_state)
        # 鮮度切れ → キューを破棄し QUEUE_EXPIRED を記録して未検出
        # 破棄は発火副作用ではないため abort も同じく破棄済み
        dropped_state = replace(previous_state, trigger_queue=())
        expired_evidence = QueueExpiredEvidence(
            occurred_at=server_time,
            dropped_count=len(previous_state.trigger_queue),
        )
        return CooldownDecision(
            VerdictHint.NO_TRIGGER,
            (),
            (),
            dropped_state,
            (expired_evidence,),
            abort_state=dropped_state,
        )

    return CooldownDecision(
        VerdictHint.NO_TRIGGER, (), (), previous_state, abort_state=previous_state
    )


def _fire(
    previous_state: DetectionState,
    server_time: datetime,
    config: ResolvedConfig,
    *origin_sources: tuple[_TriggerOrigin, ...],
    evidences: tuple[TriggerEvidence, ...] = (),
) -> CooldownDecision:
    triggered_edges = _distinct_origin_edges(origin_sources)
    triggered_nodes = _distinct_origin_nodes(origin_sources)
    cooldown_until = server_time + timedelta(minutes=config.cooldown_duration_min)
    new_state = replace(previous_state, cooldown_until=cooldown_until, trigger_queue=())
    return CooldownDecision(
        VerdictHint.TRIGGERED, triggered_edges, triggered_nodes, new_state, evidences
    )


def _queue_fresh(
    queue: tuple[QueuedTrigger, ...],
    watched_edges: frozenset[EdgeID],
    server_time: datetime,
    config: ResolvedConfig,
) -> bool:
    # 鮮度ガード
    # X 分は queue_freshness_min、未設定なら cooldown_duration_min / 2
    if not queue:
        return False
    x_min = (
        config.queue_freshness_min
        if config.queue_freshness_min is not None
        else config.cooldown_duration_min / 2.0
    )
    latest_fired = max(entry.last_fired_at for entry in queue)
    if server_time - latest_fired <= timedelta(minutes=x_min):
        return True
    # キュー対象アークのいずれかが現時点で停滞警戒（パーセンタイル超過または相対増分超過）を満たすか
    return any(
        entry.origin_edge_id in watched_edges
        for entry in queue
        if entry.origin_edge_id is not None
    )


def _queue_fire_evidences(
    queue: tuple[QueuedTrigger, ...],
    config: ResolvedConfig,
    server_time: datetime,
) -> tuple[TriggerEvidence, ...]:
    evidences: list[TriggerEvidence] = []
    if _queue_exceeds_score(queue, config):
        total = sum(entry.accumulated_score for entry in queue)
        evidences.append(
            QueueScoreEvidence(
                occurred_at=server_time,
                accumulated_score=total,
                score_threshold=config.queue_score_threshold,
            )
        )
    if _queue_is_diverse(queue, config):
        distinct = len(
            {
                entry.origin_edge_id
                for entry in queue
                if entry.origin_edge_id is not None
            }
        )
        evidences.append(
            QueueDiversityEvidence(
                occurred_at=server_time,
                distinct_origin_count=distinct,
                diversity_threshold=config.queue_diversity_threshold,
            )
        )
    return tuple(evidences)


def _merge_into_queue(
    queue: tuple[QueuedTrigger, ...],
    normal_triggers: tuple[FiredTrigger, ...],
) -> tuple[QueuedTrigger, ...]:
    merged: list[QueuedTrigger] = list(queue)
    for trigger in normal_triggers:
        index = _find_same_route(merged, trigger)
        if index is None:
            merged.append(
                QueuedTrigger(
                    kind=trigger.kind,
                    first_fired_at=trigger.fired_at,
                    last_fired_at=trigger.fired_at,
                    accumulated_score=trigger.score,
                    origin_edge_id=trigger.origin_edge_id,
                    origin_node_id=trigger.origin_node_id,
                    snapshot_ref=trigger.snapshot_ref,
                )
            )
        else:
            existing = merged[index]
            merged[index] = QueuedTrigger(
                kind=existing.kind,
                first_fired_at=existing.first_fired_at,
                last_fired_at=trigger.fired_at,
                accumulated_score=existing.accumulated_score + trigger.score,
                origin_edge_id=existing.origin_edge_id,
                origin_node_id=existing.origin_node_id,
                snapshot_ref=trigger.snapshot_ref,  # last_fired_at と整合
            )
    return tuple(merged)


def _find_same_route(queue: list[QueuedTrigger], trigger: FiredTrigger) -> int | None:
    for index, entry in enumerate(queue):
        if (
            entry.origin_edge_id == trigger.origin_edge_id
            and entry.origin_node_id == trigger.origin_node_id
        ):
            return index
    return None


def _queue_exceeds_score(
    queue: tuple[QueuedTrigger, ...], config: ResolvedConfig
) -> bool:
    total = sum(entry.accumulated_score for entry in queue)
    return total > config.queue_score_threshold


def _queue_is_diverse(queue: tuple[QueuedTrigger, ...], config: ResolvedConfig) -> bool:
    distinct_edges = {
        entry.origin_edge_id for entry in queue if entry.origin_edge_id is not None
    }
    return len(distinct_edges) > config.queue_diversity_threshold


# origin_edge_id / origin_node_id を持つトリガー (QueuedTrigger / FiredTrigger) の共通形
class _TriggerOrigin(Protocol):
    @property
    def origin_edge_id(self) -> EdgeID | None: ...
    @property
    def origin_node_id(self) -> NodeID | None: ...


def _distinct_origin_edges(
    origin_sources: tuple[tuple[_TriggerOrigin, ...], ...],
) -> tuple[EdgeID, ...]:
    seen: set[EdgeID] = set()
    ordered: list[EdgeID] = []
    for source in origin_sources:
        for item in source:
            edge_id = item.origin_edge_id
            if edge_id is not None and edge_id not in seen:
                seen.add(edge_id)
                ordered.append(edge_id)
    return tuple(ordered)


def _distinct_origin_nodes(
    origin_sources: tuple[tuple[_TriggerOrigin, ...], ...],
) -> tuple[NodeID, ...]:
    seen: set[NodeID] = set()
    ordered: list[NodeID] = []
    for source in origin_sources:
        for item in source:
            node_id = item.origin_node_id
            if node_id is not None and node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
    return tuple(ordered)


def _edge_target_key(edge_id: EdgeID) -> str:
    return f"{_TARGET_PREFIX_EDGE}{edge_id.value}"


def _node_target_key(node_id: NodeID) -> str:
    return f"{_TARGET_PREFIX_NODE}{node_id.value}"


# 新規登場／有効化／観測点構成変更でウォームアップを開始するイベント種別
_WARMUP_EVENT_KINDS = (
    EventKind.ENABLE,
    EventKind.ADD_EDGE,
    EventKind.ADD_NODE,
    EventKind.SENSOR_SET_CHANGED,
)


def apply_warmup_events(
    previous_state: DetectionState,
    events: tuple[Event, ...],
    server_time: datetime,
    config: ResolvedConfig,
) -> DetectionState:
    # ENABLE/ADD_* を受けた対象に server_time + warmup_duration を設定
    # DISABLE を受けた対象は warmup エントリを削除
    warmup_until = server_time + timedelta(minutes=config.warmup_duration_min)
    warmup_map = {w.target_key: w.until for w in previous_state.warmup_states}
    for event in events:
        if event.kind in _WARMUP_EVENT_KINDS:
            warmup_map[event.target_id] = warmup_until
        elif event.kind == EventKind.DISABLE:
            _ = warmup_map.pop(event.target_id, None)

    if warmup_map == {w.target_key: w.until for w in previous_state.warmup_states}:
        return previous_state

    warmup_states = tuple(
        WarmupState(target_key=key, until=until) for key, until in warmup_map.items()
    )
    return replace(previous_state, warmup_states=warmup_states)


# 状態変化としてクールタイムをリセットするスケジュールイベント種別
_SCHEDULED_EVENT_KINDS = (
    EventKind.SCHEDULED_INFLOW,
    EventKind.SCHEDULED_ATTR_CHANGE,
)


def apply_scheduled_events(
    previous_state: DetectionState,
    events: tuple[Event, ...],
) -> DetectionState:
    # スケジュールイベントはクールタイムをリセットする，キューは保持
    has_scheduled = any(event.kind in _SCHEDULED_EVENT_KINDS for event in events)
    if not has_scheduled or previous_state.cooldown_until is None:
        return previous_state
    return replace(previous_state, cooldown_until=None)


def all_targets_in_warmup(
    state: DetectionState,
    graph: Graph,
    server_time: datetime,
) -> bool:
    # 有効なアーク・ノード全対象がウォームアップ中か
    # 対象ゼロは False
    target_keys = [_edge_target_key(e.edge_id) for e in graph.enabled_edges()]
    target_keys += [_node_target_key(n.node_id) for n in graph.enabled_nodes()]
    if not target_keys:
        return False
    return all(state.is_in_warmup(key, server_time) for key in target_keys)


def has_danger_event(events: tuple[Event, ...]) -> bool:
    return any(event.kind == EventKind.DANGER_FLAG_UP for event in events)


def update_retrigger_counts(
    previous_counts: tuple[RetriggerEntry, ...],
    graph: Graph,
    normal_trigger_edges: tuple[EdgeID, ...],
    watch_states: tuple[ArcWatchState, ...],
    server_time: datetime,
    config: ResolvedConfig,
) -> tuple[RetriggerEntry, ...]:
    # 再発火カウントのリセット
    # 手動トリガーはカウント対象外
    fired_edges = list(dict.fromkeys(normal_trigger_edges))  # 出現順・重複排除
    fired_set = set(fired_edges)
    watched = {
        watch.edge_id
        for watch in watch_states
        if watch.percentile_breached or watch.delta_breached
    }
    enabled_edges = {edge.edge_id for edge in graph.enabled_edges()}

    entries: dict[EdgeID, RetriggerEntry] = {}
    for entry in previous_counts:
        edge_id = entry.edge_id
        if edge_id not in enabled_edges:
            # グラフ削除／無効化 → エントリ削除
            continue

        fired_this_cycle = edge_id in fired_set
        different_origin = bool(fired_set - {edge_id})

        if different_origin and not fired_this_cycle:
            # 別アーク起点発火 → 当該アークのカウントをリセット
            entries[edge_id] = RetriggerEntry(
                edge_id=edge_id, last_fired_at=entry.last_fired_at
            )
        elif not fired_this_cycle and edge_id not in watched:
            quiet_cycles = entry.quiet_cycles + 1
            if quiet_cycles >= config.retrigger_reset_quiet_cycles:
                # 連続沈静化 → リセット
                entries[edge_id] = RetriggerEntry(
                    edge_id=edge_id, last_fired_at=entry.last_fired_at
                )
            else:
                entries[edge_id] = RetriggerEntry(
                    edge_id=edge_id,
                    count=entry.count,
                    quiet_cycles=quiet_cycles,
                    last_fired_at=entry.last_fired_at,
                )
        elif fired_this_cycle:
            entries[edge_id] = RetriggerEntry(
                edge_id=edge_id,
                count=entry.count + 1,
                quiet_cycles=0,
                last_fired_at=server_time,
            )
        else:
            # 発火せず警戒中かつ別起点発火なし → カウント維持
            entries[edge_id] = entry

    # 初回発火のアーク（既存エントリなし）は count=1 で登録
    for edge_id in fired_edges:
        if edge_id in entries or edge_id not in enabled_edges:
            continue
        entries[edge_id] = RetriggerEntry(
            edge_id=edge_id, count=1, quiet_cycles=0, last_fired_at=server_time
        )

    return tuple(entries.values())


def apply_danger_flag_down(
    previous_state: DetectionState,
    events: tuple[Event, ...],
) -> DetectionState:
    # DANGER_FLAG_DOWN を受けたアークの既存の再発火カウントリセット
    # 立ち下げ自体は発火扱いとしない
    # クールタイムリセットも行わない
    cleared_edges = {
        EdgeID(event.target_id[len(_TARGET_PREFIX_EDGE) :])
        for event in events
        if event.kind == EventKind.DANGER_FLAG_DOWN
        and event.target_id.startswith(_TARGET_PREFIX_EDGE)
    }
    if not cleared_edges:
        return previous_state

    changed = False
    updated: list[RetriggerEntry] = []
    for entry in previous_state.arc_retrigger_counts:
        if entry.edge_id in cleared_edges and (entry.count or entry.quiet_cycles):
            updated.append(
                RetriggerEntry(edge_id=entry.edge_id, last_fired_at=entry.last_fired_at)
            )
            changed = True
        else:
            updated.append(entry)

    if not changed:
        return previous_state
    return replace(previous_state, arc_retrigger_counts=tuple(updated))
