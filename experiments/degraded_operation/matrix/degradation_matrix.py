from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

pb = importlib.import_module("flow_control.rpc.generated.tolo.flow.v1.flow_pb2")
codec = importlib.import_module("flow_control.rpc.codec")
handler = importlib.import_module("flow_control.service.handler")
detector = importlib.import_module("flow_control.detection.detector")
triggers = importlib.import_module("flow_control.detection.triggers")
history_types = importlib.import_module("flow_control.domain.history")
obs = importlib.import_module("devtools.scenarios._observation")
graph_builder = importlib.import_module("devtools.graph_builder")

RESULTS = ROOT / "experiments" / "degraded_operation" / "results"
GRAPH = graph_builder.venue().graph
EDGE_IDS = tuple(edge.edge_id.value for edge in GRAPH.edges)
HOT = obs.HOT_EDGE
WARM = 30
RAMP = 20
CYCLES = WARM + RAMP
ONSET = WARM
CUT = ONSET + 3
PROBE = ONSET + 5
P90 = 1.5
BASELINE = 1.0
ETA = 0.5
LONG_SPAN_H = 24.0
SHORT_SPAN_H = 2.0
STALE = timedelta(minutes=10)
TIMELINES = ("surge", "stagnation_only", "flat")
TIMELINE_LABELS = {
    "surge": "急増＋停滞（発火すべき）",
    "stagnation_only": "停滞のみ上昇（発火すべきでない）",
    "flat": "平坦（発火すべきでない）",
}


def production_config() -> pb.ResolvedConfig:
    config = obs.observation_config()
    config.surge_rate_threshold_percent_per_min = 10
    config.fallback_eta = 0.25
    return config


CONFIG = production_config()


def timeline(kind: str) -> list[obs.Cycle]:
    cycles = []
    for index in range(CYCLES):
        ramp = max(0, index - ONSET + 1)
        hall_a = 10.0 * 1.4**ramp if kind == "surge" else 10.0
        hot_stagnation = 1.0 if kind == "flat" else 1.0 + 2.0 * ramp
        forward = {
            "e_in_j1": obs.THROUGH_FLOW + hall_a,
            HOT: hall_a,
            "e_j1_hallB": obs.THROUGH_FLOW,
            "e_hallB_j2": obs.THROUGH_FLOW,
            "e_j2_out": obs.THROUGH_FLOW,
        }
        routes = {
            edge: obs.RouteMeasurement(
                forward=forward.get(edge, 0.0),
                backward=0.0,
                stagnation=hot_stagnation if edge == HOT else 1.0,
            )
            for edge in EDGE_IDS
        }
        cycles.append(
            obs.Cycle(
                server_time=obs.DEFAULT_TIME - obs.WINDOW * (CYCLES - 1 - index),
                routes=routes,
                occupancy_delta={"hallA": hall_a, "hallB": 0.0},
            )
        )
    return cycles


def base_request(cycles: Sequence[obs.Cycle], index: int) -> pb.OptimizeRequest:
    history = obs._history(GRAPH, cycles[:index])
    history.completeness = 0.0
    history.arc_stats.extend(
        pb.ArcHistoryStat(
            edge_id=edge,
            p90_stagnation=P90,
            baseline_stagnation=BASELINE,
            flow_sensitivity_eta=ETA,
            available_span_hours=LONG_SPAN_H,
        )
        for edge in EDGE_IDS
    )
    request = obs.observation_request(
        GRAPH, cycles[index], history, CONFIG, pb.DetectionState(), None, omit_zero_flows=False
    )
    request.event_context.CopyFrom(
        pb.EventContext(term=pb.EVENT_TERM_LONG, available_history_hours=720.0)
    )
    return request


def _keep(field, predicate) -> None:
    kept = [item for item in field if predicate(item)]
    del field[:]
    field.extend(kept)


def _series(request: pb.OptimizeRequest, edge: str):
    return next((s for s in request.history_digest.window_series if s.edge_id == edge), None)


def _hot_flows(request: pb.OptimizeRequest) -> list:
    return [flow for flow in request.observations.arc_flows if flow.edge_id == HOT]


def _hot_stagnation(request: pb.OptimizeRequest):
    return next((s for s in request.observations.arc_stagnations if s.edge_id == HOT), None)


def _before(cycles: Sequence[obs.Cycle], index: int):
    limit = cycles[index].server_time
    return lambda sample: sample.at.ToDatetime(tzinfo=UTC) < limit


def _drop_hot_window_from(request: pb.OptimizeRequest, cycles, index: int) -> None:
    series = _series(request, HOT)
    if series is not None:
        _keep(series.flow_samples, _before(cycles, index))
        _keep(series.stagnation_samples, _before(cycles, index))


def alter_none(request, index, cycles) -> None:
    pass


def alter_no_history(request, index, cycles) -> None:
    del request.history_digest.arc_stats[:]
    del request.history_digest.window_series[:]


def alter_short_span(request, index, cycles) -> None:
    for stat in request.history_digest.arc_stats:
        stat.ClearField("p90_stagnation")
        stat.ClearField("baseline_stagnation")
        stat.ClearField("flow_sensitivity_eta")
        stat.available_span_hours = SHORT_SPAN_H


def alter_empty_window(request, index, cycles) -> None:
    del request.history_digest.window_series[:]


def alter_restart(request, index, cycles) -> None:
    restarted = _before(cycles, ONSET)
    for series in request.history_digest.window_series:
        _keep(series.flow_samples, lambda sample: not restarted(sample))
        _keep(series.stagnation_samples, lambda sample: not restarted(sample))


def alter_no_line(request, index, cycles) -> None:
    _keep(request.observations.arc_flows, lambda flow: flow.edge_id != HOT)
    series = _series(request, HOT)
    if series is not None:
        del series.flow_samples[:]


def alter_no_line_zero(request, index, cycles) -> None:
    for flow in _hot_flows(request):
        flow.flow_rate = 0.0
    series = _series(request, HOT)
    if series is not None:
        for sample in series.flow_samples:
            sample.value = 0.0


def alter_intermittent_0(request, index, cycles) -> None:
    series = _series(request, HOT)
    if series is not None:
        del series.flow_samples[:]


def alter_intermittent_1(request, index, cycles) -> None:
    series = _series(request, HOT)
    if series is not None and len(series.flow_samples) > 1:
        last = pb.TimedValue()
        last.CopyFrom(series.flow_samples[-1])
        del series.flow_samples[:]
        series.flow_samples.append(last)


def _on_five_minute_grid(sample) -> bool:
    return sample.at.ToDatetime(tzinfo=UTC).minute % 5 == 0


def alter_sparse(request, index, cycles) -> None:
    series = _series(request, HOT)
    if series is not None:
        _keep(series.flow_samples, _on_five_minute_grid)
        _keep(series.stagnation_samples, _on_five_minute_grid)


def alter_point_missing(request, index, cycles) -> None:
    _keep(request.observations.arc_flows, lambda flow: flow.edge_id != HOT)
    _keep(request.observations.arc_stagnations, lambda s: s.edge_id != HOT)
    _keep(request.history_digest.window_series, lambda s: s.edge_id != HOT)
    _keep(request.history_digest.arc_stats, lambda s: s.edge_id != HOT)


def alter_node_missing(request, index, cycles) -> None:
    del request.observations.node_occupancies[:]


def alter_invalid(request, index, cycles) -> None:
    if index < CUT:
        return
    for flow in _hot_flows(request):
        flow.flow_rate = 0.0
        flow.confidence_flag = pb.CONFIDENCE_FLAG_INVALID
    _keep(request.observations.arc_stagnations, lambda s: s.edge_id != HOT)
    _drop_hot_window_from(request, cycles, CUT)


def alter_hold_flag(request, index, cycles) -> None:
    if index < CUT:
        return
    for flow in _hot_flows(request):
        flow.confidence_flag = pb.CONFIDENCE_FLAG_HOLD
    _hot_stagnation(request).confidence_flag = pb.CONFIDENCE_FLAG_HOLD


def alter_hold_frozen(request, index, cycles) -> None:
    if index < CUT:
        return
    held = cycles[CUT - 1].routes[HOT]
    for flow in _hot_flows(request):
        flow.flow_rate = (
            held.forward if flow.direction == pb.FLOW_DIRECTION_A_TO_B else held.backward
        )
        flow.confidence_flag = pb.CONFIDENCE_FLAG_HOLD
    stagnation = _hot_stagnation(request)
    stagnation.stagnation = held.stagnation
    stagnation.confidence_flag = pb.CONFIDENCE_FLAG_HOLD
    _drop_hot_window_from(request, cycles, CUT)


def alter_dropout(request, index, cycles) -> None:
    if index < CUT:
        return
    _keep(request.observations.arc_flows, lambda flow: flow.edge_id != HOT)
    _keep(request.observations.arc_stagnations, lambda s: s.edge_id != HOT)
    _drop_hot_window_from(request, cycles, CUT)


def alter_stale(request, index, cycles) -> None:
    request.observations.observed_at.CopyFrom(obs._timestamp(cycles[index].server_time - STALE))


def alter_short_term(request, index, cycles) -> None:
    request.event_context.CopyFrom(
        pb.EventContext(term=pb.EVENT_TERM_SHORT, available_history_hours=1.0)
    )


@dataclass(frozen=True)
class Condition:
    key: str
    label: str
    alter: Callable[[pb.OptimizeRequest, int, Sequence[obs.Cycle]], None]
    probe: Callable[[pb.OptimizeRequest], bool]
    spec_fire: bool | None
    spec_stagnation_only: bool
    spec: str
    spec_short_tenant: bool = False


def _hot_window_stops_at_cut(request) -> bool:
    series = _series(request, HOT)
    if series is None or not series.flow_samples:
        return False
    gap = request.server_time.ToDatetime(tzinfo=UTC) - series.flow_samples[-1].at.ToDatetime(
        tzinfo=UTC
    )
    return gap == obs.WINDOW * (PROBE - CUT + 1)


def _hot_series_len(request, attr: str) -> int:
    series = _series(request, HOT)
    return -1 if series is None else len(getattr(series, attr))


CONDITIONS = (
    Condition(
        "base",
        "長期履歴あり（基準）",
        alter_none,
        lambda r: True,
        True,
        False,
        "§9.2.3 停滞警戒∧急増で発火",
    ),
    Condition(
        "no_history",
        "履歴なし（統計も直近窓もなし）",
        alter_no_history,
        lambda r: not r.history_digest.arc_stats and not r.history_digest.window_series,
        None,
        False,
        "§9.2.4 は P90 欠損だけを扱い、直近窓の欠落を定めない",
    ),
    Condition(
        "short_span",
        "履歴スパン 4 時間未満（p90/baseline/eta が null）",
        alter_short_span,
        lambda r: all(not s.HasField("p90_stagnation") for s in r.history_digest.arc_stats),
        True,
        False,
        "§9.2.4 履歴不足 / §9.3: (a).2 だけで停滞警戒を判定して発火",
    ),
    Condition(
        "empty_window",
        "長期統計あり・直近窓が常に空",
        alter_empty_window,
        lambda r: bool(r.history_digest.arc_stats) and not r.history_digest.window_series,
        None,
        False,
        "定めなし（§9.2.4 は P90 欠損時の縮退だけ）",
    ),
    Condition(
        "restart",
        "急増開始時に再起動（直近窓が空から 1 分ずつ戻る）",
        alter_restart,
        lambda r: 0 < _hot_series_len(r, "flow_samples") <= PROBE - ONSET,
        True,
        False,
        "定めなし。窓が戻れば §9.2.3 で発火するはず",
    ),
    Condition(
        "no_line",
        "急増エッジにラインなし（arc_flows を送らない）",
        alter_no_line,
        lambda r: not _hot_flows(r) and _hot_series_len(r, "flow_samples") == 0,
        True,
        True,
        "§9.2.4 ラインなし: 停滞警戒単独の縮退発火（DEGRADED_COMBINED_TRIGGER）、§9.1 SURGE_PROXY_FALLBACK",
    ),
    Condition(
        "no_line_zero",
        "急増エッジにラインなし（Observation の形: 0 人/分を送る）",
        alter_no_line_zero,
        lambda r: all(f.flow_rate == 0 for f in _hot_flows(r)) and len(_hot_flows(r)) == 2,
        True,
        True,
        "§9.2.4 ラインなし（入力上は 0 人/分のラインと区別できない）",
    ),
    Condition(
        "intermittent_0",
        "間欠ライン（今回値あり・窓の流量 0 点）",
        alter_intermittent_0,
        lambda r: _hot_series_len(r, "flow_samples") == 0 and bool(_hot_flows(r)),
        None,
        False,
        "定めなし（§9.1 は窓の系列を前提にする）",
    ),
    Condition(
        "intermittent_1",
        "間欠ライン（今回値あり・窓の流量 1 点）",
        alter_intermittent_1,
        lambda r: _hot_series_len(r, "flow_samples") == 1 and bool(_hot_flows(r)),
        True,
        False,
        "§9.1 窓内の点で傾きを求める（今回値と合わせて 2 点）",
    ),
    Condition(
        "sparse",
        "疎なライン（窓の点を 5 分に 1 点へ間引く）",
        alter_sparse,
        lambda r: 0 < _hot_series_len(r, "flow_samples") <= 7,
        True,
        False,
        "§9.1 窓内の点で傾きを求める",
    ),
    Condition(
        "point_missing",
        "観測点なし（急増エッジが無観測）",
        alter_point_missing,
        lambda r: not _hot_flows(r) and _series(r, HOT) is None,
        False,
        False,
        "§9.2.4 カメラなし: 警戒・発火なし",
    ),
    Condition(
        "node_missing",
        "ノード占有なし",
        alter_node_missing,
        lambda r: not r.observations.node_occupancies,
        True,
        False,
        "§9.2 は検知にノード占有を使わない（発火は変わらない）",
    ),
    Condition(
        "invalid",
        "急増エッジが INVALID（急増開始 +3 分から。Observation の形）",
        alter_invalid,
        lambda r: (
            all(f.confidence_flag == pb.CONFIDENCE_FLAG_INVALID for f in _hot_flows(r))
            and _hot_stagnation(r) is None
            and _hot_window_stops_at_cut(r)
        ),
        False,
        False,
        "要件 §5.6 / 設計 §3: INVALID の値は使わない（§9.2.4 カメラなし相当）",
    ),
    Condition(
        "hold_flag",
        "急増エッジが HOLD（フラグのみ。値は実測のまま）",
        alter_hold_flag,
        lambda r: _hot_stagnation(r).confidence_flag == pb.CONFIDENCE_FLAG_HOLD,
        True,
        False,
        "要件 §5.6: HOLD は低信頼として扱うが値は使う",
    ),
    Condition(
        "hold_frozen",
        "急増エッジが HOLD（Observation の形: 値を凍結し窓から外す）",
        alter_hold_frozen,
        lambda r: (
            _hot_stagnation(r).confidence_flag == pb.CONFIDENCE_FLAG_HOLD
            and _hot_window_stops_at_cut(r)
        ),
        None,
        False,
        "要件 §5.6 / 設計 §3.5: 低信頼として使い、窓には含めない。発火可否は定めない",
    ),
    Condition(
        "dropout",
        "端末脱落（急増開始 +3 分から今回値なし・窓も途切れる）",
        alter_dropout,
        lambda r: not _hot_flows(r) and _hot_window_stops_at_cut(r),
        False,
        False,
        "連携 §2.2.7: 欠損は HOLD/INVALID で届く前提。今回値なしはカメラなし相当（§9.2.4）",
    ),
    Condition(
        "stale",
        "観測が 10 分古い（observed_at だけ遅れる）",
        alter_stale,
        lambda r: (
            r.server_time.ToDatetime(tzinfo=UTC) - r.observations.observed_at.ToDatetime(tzinfo=UTC)
            == STALE
        ),
        None,
        False,
        "定めなし（observed_at の鮮度規則はない）",
    ),
    Condition(
        "short_term",
        "短期テナント（term=SHORT・available_history_hours=1）",
        alter_short_term,
        lambda r: r.event_context.term == pb.EVENT_TERM_SHORT,
        True,
        False,
        "§9.3 / 設計 §4.5: (a).2 のみ・degraded_short_tenant=true・ウォームアップ 15 分",
        spec_short_tenant=True,
    ),
)


@contextmanager
def patched_detect_metric_triggers(wrap) -> Iterator[None]:
    if wrap is None:
        yield
        return
    with patch.object(detector, "detect_metric_triggers", wrap(detector.detect_metric_triggers)):
        yield


def prototype_d5_baseline_reference(inner):
    def call(**kwargs):
        digest = kwargs["history_digest"]
        series = list(digest.window_series)
        for edge in kwargs["graph"].enabled_edges():
            stat = digest.stat_of(edge.edge_id)
            window = digest.window_series_of(edge.edge_id)
            if stat is None or stat.baseline_stagnation is None:
                continue
            if window is not None and window.stagnation_samples:
                continue
            synthetic = ((kwargs["server_time"], stat.baseline_stagnation),)
            if window is None:
                series.append(
                    history_types.ArcWindowSeries(edge.edge_id, stagnation_samples=synthetic)
                )
            else:
                series[series.index(window)] = replace(window, stagnation_samples=synthetic)
        return inner(**{**kwargs, "history_digest": replace(digest, window_series=tuple(series))})

    return call


def prototype_d6_lineless_fallback(inner):
    def call(**kwargs):
        observations = kwargs["observations"]
        digest = kwargs["history_digest"]
        config = kwargs["config"]
        blind = set()
        for edge in kwargs["graph"].enabled_edges():
            now = triggers._current_line_flow(observations, edge.edge_id)
            window = digest.window_series_of(edge.edge_id)
            samples = window.flow_samples if window is not None else ()
            if not samples and now is None:
                continue
            series = triggers._line_series(
                samples,
                now,
                observations.observed_at,
                edge.time_resolution_s,
                config.surge_evaluate_window_minute,
                kwargs["server_time"],
            )
            if triggers._slope_percent_per_min(series) is None:
                blind.add(edge.edge_id)
        lineless_observations = replace(
            observations,
            arc_flows=tuple(f for f in observations.arc_flows if f.edge_id not in blind),
        )
        lineless_digest = replace(
            digest,
            window_series=tuple(
                replace(w, flow_samples=()) if w.edge_id in blind else w
                for w in digest.window_series
            ),
        )
        return inner(
            **{**kwargs, "observations": lineless_observations, "history_digest": lineless_digest}
        )

    return call


def prototype_both(inner):
    return prototype_d5_baseline_reference(prototype_d6_lineless_fallback(inner))


VARIANTS = {
    "baseline": None,
    "D5": prototype_d5_baseline_reference,
    "D6": prototype_d6_lineless_fallback,
    "D5+D6": prototype_both,
}


def _stable(response: pb.OptimizeResponse) -> bytes:
    copy = pb.OptimizeResponse()
    copy.CopyFrom(response)
    copy.elapsed_ms = 0
    for step in copy.diagnostics.steps_executed:
        step.elapsed_ms = 0
    copy.feedback_values.compute_meta.solver_phase1_ms = 0
    copy.feedback_values.compute_meta.solver_phase2_ms = 0
    return copy.SerializeToString(deterministic=True)


def run(condition: Condition, kind: str, variant: str) -> dict:
    cycles = timeline(kind)
    state = pb.DetectionState()
    previous = None
    detections: list = []
    original_detect = handler.detect

    def spy(*args, **kwargs):
        result = original_detect(*args, **kwargs)
        detections.append(result)
        return result

    verdicts: list[str] = []
    warnings: set[str] = set()
    flags = {"percentile": False, "delta": False, "surge": False}
    triggered: list[str] = []
    altered = False
    fallbacks = 0
    short_tenant = False
    demand_digest = 0
    fired_response = None
    digest = hashlib.sha256()
    with patch.object(handler, "detect", spy), patched_detect_metric_triggers(VARIANTS[variant]):
        for index in range(CYCLES):
            request = base_request(cycles, index)
            reference = request.SerializeToString(deterministic=True)
            condition.alter(request, index, cycles)
            altered = altered or request.SerializeToString(deterministic=True) != reference
            if kind == "surge" and index == PROBE:
                assert condition.probe(request), (
                    f"{condition.key}: 条件が意図どおりに入力を変えていない"
                )
            request.detection_state.CopyFrom(state)
            if previous is not None:
                request.previous_result.CopyFrom(previous)
            response = codec.encode_response(handler.handle_request(codec.decode_request(request)))
            digest.update(_stable(response))
            verdict = pb.Verdict.Name(response.verdict).removeprefix("VERDICT_")
            verdicts.append(verdict)
            warnings.update(pb.WarningCode.Name(w.code) for w in response.diagnostics.warnings)
            fallbacks += len(response.diagnostics.fallbacks_applied)
            short_tenant = short_tenant or response.diagnostics.degraded_short_tenant
            for watch in response.updated_detection_state.arc_watch_states:
                if watch.edge_id == HOT:
                    flags["percentile"] |= watch.percentile_breached
                    flags["delta"] |= watch.delta_breached
                    flags["surge"] |= watch.surge_breached
            for evidence in detections[-1].evidences:
                if getattr(evidence, "edge_id", None) is not None and evidence.edge_id.value == HOT:
                    flags["surge"] |= type(evidence).__name__ == "SurgeEvidence"
                    flags["percentile"] |= type(evidence).__name__ == "HighStagnationEvidence"
            demand_digest = max(
                demand_digest, len(response.updated_detection_state.arc_demand_digest.entries)
            )
            state = response.updated_detection_state
            previous = (
                response.optimization_result if response.HasField("optimization_result") else None
            )
            if verdict == "OPTIMIZED":
                triggered = [edge.value for edge in detections[-1].triggered_edges]
                fired_response = response
                break
    assert condition.key == "base" or altered, f"{condition.key}: 入力が基準と同一のまま"
    first = len(verdicts) - 1 if fired_response is not None else None
    return {
        "condition": condition.key,
        "timeline": kind,
        "variant": variant,
        "first_optimized_cycle": None if first is None else first + 1,
        "minutes_after_onset": None if first is None else first - ONSET,
        "verdict_counts": dict(sorted(Counter(verdicts).items())),
        "verdicts": verdicts,
        "triggered_edges": triggered,
        "diagnostics_warnings": sorted(warnings),
        "hot_edge_alerts_seen": flags,
        "fallbacks_applied": fallbacks,
        "degraded_short_tenant": short_tenant,
        "lambda_hat_entries_max": demand_digest,
        "at_fire": None if fired_response is None else _at_fire(fired_response),
        "response_digest": digest.hexdigest(),
    }


def _at_fire(response: pb.OptimizeResponse) -> dict:
    result = response.optimization_result
    feedback = response.feedback_values
    return {
        "solver_status": pb.SolverStatus.Name(result.solver_status).removeprefix("SOLVER_STATUS_"),
        "route_importance": len(result.route_importance),
        "detour_paths": len(result.detour_paths),
        "direction_changes": sum(
            1 for d in result.direction_proposal if d.change_type != pb.DIRECTION_CHANGE_TYPE_KEEP
        ),
        "proposal_non_empty": bool(result.route_importance or result.detour_paths),
        "throughput": round(feedback.objective_values.throughput, 6),
        "estimation_resolution": dict(
            sorted(
                Counter(
                    pb.ODResolutionMode.Name(item.mode).removeprefix("OD_RESOLUTION_MODE_")
                    for item in feedback.forecast_summary.estimation_resolution
                ).items()
            )
        ),
        "imputed_arcs": sorted(
            arc
            for item in feedback.forecast_summary.estimation_resolution
            for arc in item.imputed_arcs
        ),
        "reference_used_default": feedback.reference_usage.used_default,
        "low_confidence_arc_ratio": feedback.quality_metrics.low_confidence_arc_ratio,
        "feedback_warnings": len(feedback.warnings),
    }


def judge(condition: Condition, runs: dict[str, dict]) -> dict:
    fired = runs["surge"]["first_optimized_cycle"] is not None
    false_alarm_stagnation = runs["stagnation_only"]["first_optimized_cycle"] is not None
    false_alarm_flat = runs["flat"]["first_optimized_cycle"] is not None
    if condition.spec_fire is None:
        surge_match = "仕様外"
    else:
        ok = fired == condition.spec_fire and (
            runs["surge"]["degraded_short_tenant"] == condition.spec_short_tenant
        )
        surge_match = "一致" if ok else "不一致"
    control_ok = false_alarm_stagnation == condition.spec_stagnation_only and not false_alarm_flat
    return {
        "fired": fired,
        "silent_miss": not fired,
        "false_alarm_stagnation_only": false_alarm_stagnation,
        "false_alarm_flat": false_alarm_flat,
        "surge_match": surge_match,
        "control_match": "一致" if control_ok else "不一致",
    }


def assert_premises(matrix: dict) -> None:
    base = matrix["baseline"]["base"]
    assert base["surge"]["first_optimized_cycle"] is not None, "基準: 急増で発火しない"
    assert base["stagnation_only"]["first_optimized_cycle"] is None, "基準: 停滞のみで誤発火"
    assert base["flat"]["first_optimized_cycle"] is None, "基準: 平坦で誤発火"
    short = matrix["baseline"]["short_term"]["surge"]
    assert short["response_digest"] == base["surge"]["response_digest"], (
        "短期テナント: event_context を変えると応答が変わった（D4 の前提が崩れた）"
    )


def _cell(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "あり" if value else "なし"
    if isinstance(value, dict):
        return ", ".join(f"{k}:{v}" for k, v in value.items()) or "-"
    if isinstance(value, list):
        return ", ".join(value) or "-"
    return str(value)


def _fire_cell(record: dict) -> str:
    if record["first_optimized_cycle"] is None:
        return "発火せず"
    return f"{record['first_optimized_cycle']}（+{record['minutes_after_onset']} 分）"


def _flags_cell(record: dict) -> str:
    seen = record["hot_edge_alerts_seen"]
    return "/".join(
        mark if seen[key] else "-"
        for key, mark in (("percentile", "P"), ("delta", "Δ"), ("surge", "急"))
    )


NOTES = [
    "",
    "## Observation から見えない信号",
    "",
    "tolo-observation は verdict、`updated_detection_state`、`optimization_result`、`feedback_values` を保存し、`Diagnostics` を捨てる。",
    "",
    "- `SURGE_PROXY_FALLBACK` と `DEGRADED_COMBINED_TRIGGER` は `Diagnostics.warnings` にしか出ないので、Observation からは見えない。",
    "- `fallbacks_applied`、`trigger_evidences`、`degraded_short_tenant` は Observation が捨てる以前に、`handle_request` が詰めない。",
    "- `feedback_values.warnings` は空のまま、`quality_metrics.low_confidence_arc_ratio` は 0.0 固定である。HOLD/INVALID を送っても feedback には現れない。",
    "- feedback から読めるのは `estimation_resolution` の解像度と補完アーク、`reference_usage.used_default` だけである。",
    "",
    "## 入力の作り方で注意する点",
    "",
    "- 端末脱落の行は依頼どおり今回値を送らない形にした。Observation の `NewSnapshot` は欠損 15 分以内を HOLD（最後の値を保持）、それより長いと INVALID として送るので、本番の形は HOLD（凍結）と INVALID の行に当たる。",
    "- HOLD（凍結）の行は急増開始 +3 分から最後まで HOLD のままにした。本番では 15 分で INVALID に変わるが、HOLD の間に一度も発火していないので結論は変わらない。",
    "- 古い観測の行は `observed_at` だけを 10 分戻し、値は今回のものを使った。値ごと 10 分遅れる場合は、基準の発火が 10 分遅れるだけになる（推測。未実行）。",
    "- `devtools/observation_shaped_request.md` は、両方向の `ArcFlow` を送ると OD が空になり throughput が 0 になると書く。今回は両方向を送っても throughput は発火時の急増エッジ流量に等しかった（原因は未調査）。発火が遅い行で INFEASIBLE になるのは、`e_in_j1` の需要が capacity_hint 80 を超えるためと推測する。",
    "- ラインなし（0 人/分）の行は、ラインのない観測点でも Observation が `RouteScore` の両方向 0 を送るという推測に基づく（`appendArcObservations` は常に 2 本の `ArcFlow` を足す）。",
    "",
]


def render(matrix: dict, verdicts: dict) -> str:
    every = [run for rows in matrix.values() for runs in rows.values() for run in runs.values()]
    lines = [
        "# 縮退入力ごとの Flow エンジンの出力",
        "",
        "`uv run python experiments/degraded_operation/matrix/degradation_matrix.py` が生成する。",
        "手で編集しない。",
        "",
        "## 条件",
        "",
        (
            f"- グラフは devtools の `venue`、急増エッジは `{HOT}`。1 分ごとに {CYCLES} サイクルを "
            "`decode_request` → `handle_request` に通し、`updated_detection_state` と `optimization_result` を次へ渡す。"
        ),
        (
            f"- 平坦 {WARM} サイクルのあと {ONSET + 1} サイクル目から急増する。"
            "「+N 分」は急増開始からの経過で、初回 OPTIMIZED で打ち切る。"
        ),
        (
            "- 設定は tolo-observation `defaultFlowConfig()`（急増閾値 10%/分、fallback_eta 0.25）。"
            "devtools の `observation_config()` は急増閾値 50 で、本番と食い違う。"
        ),
        (
            "- 入力の形は本番に合わせた。両方向の `ArcFlow` を常に送る、`completeness=0`、"
            "`references` 空、`theta_demand` なし、`directional_flow_samples` なし、全エッジ VECTOR。"
        ),
        (
            f"- 長期統計は p90={P90}、baseline={BASELINE}、eta={ETA}、スパン {LONG_SPAN_H} 時間。"
            "基準の event_context は LONG・720 時間。"
        ),
        "- 対照は 2 本。停滞のみ上昇（流量は平坦）と、全て平坦。どちらも発火すべきでない。",
        "",
        "## 現状（プロトタイプなし）",
        "",
        (
            "列の意味。P/Δ/急 は急増エッジで (a).1・(a).2・急増が一度でも成立したか。"
            "警告は `Diagnostics.warnings` で、tolo-observation は捨てる。"
        ),
        "",
        (
            "| 条件 | 急増: 初回 OPTIMIZED | 発火エッジ | P/Δ/急 | 警告（Observation では不可視） "
            "| 対照 誤発火（停滞のみ / 平坦） | degraded_short_tenant | 仕様の期待 | 急増 | 対照 |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        runs = matrix["baseline"][condition.key]
        surge = runs["surge"]
        judged = verdicts["baseline"][condition.key]
        lines.append(
            f"| {condition.label} | {_fire_cell(surge)} | {_cell(surge['triggered_edges'])} "
            f"| {_flags_cell(surge)} | {_cell(surge['diagnostics_warnings'])} "
            f"| {_cell(judged['false_alarm_stagnation_only'])} / {_cell(judged['false_alarm_flat'])} "
            f"| {_cell(surge['degraded_short_tenant'])} | {condition.spec} "
            f"| {judged['surge_match']} | {judged['control_match']} |"
        )
    lines += [
        "",
        "## 発火したサイクルの提案（急増の行のみ）",
        "",
        (
            f"全 {len(every)} 実行で `fallbacks_applied` は計 {sum(r['fallbacks_applied'] for r in every)} 件、"
            f"`arc_demand_digest`（λ̂）の件数は最大 {max(r['lambda_hat_entries_max'] for r in every)} 件だった。"
        ),
        "",
        (
            "| 条件 | solver | route_importance | detour_paths | 方向変更 | throughput "
            "| estimation_resolution | 補完アーク | 参照値の既定使用 | low_confidence_arc_ratio |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        fire = matrix["baseline"][condition.key]["surge"]["at_fire"]
        if fire is None:
            continue
        lines.append(
            f"| {condition.label} | {fire['solver_status']} | {fire['route_importance']} "
            f"| {fire['detour_paths']} | {fire['direction_changes']} | {fire['throughput']} "
            f"| {_cell(fire['estimation_resolution'])} | {_cell(fire['imputed_arcs'])} "
            f"| {_cell(fire['reference_used_default'])} | {fire['low_confidence_arc_ratio']} |"
        )
    lines += [
        "",
        "## プロトタイプ適用後に変わった行",
        "",
        (
            "- D5: 直近窓に停滞サンプルがなく、履歴統計に baseline_stagnation があるとき、それを直近平均の代わりに使う。"
            "baseline がなければ従来どおり (a).2 を不成立とする。"
        ),
        "- D6: ラインがあるのに傾きを計算できないとき、そのエッジをラインなし規則で判定する。",
        "- D6 の「傾きを計算できない」には流量平均が 0 のエッジも入る。試作は急増エッジに限らず、流量 0 の全エッジをラインなし規則に回す。停滞が上がれば単独で発火するので、停滞のみの対照で誤発火が出る。窓の点が 2 点未満のときだけに絞れば、この誤発火は出ないはずである（推測。未実行）。",
        "- どちらも `detection.detector.detect_metric_triggers` を入力書換えのラッパーで差し替えた試作で、src は変えていない。",
        "",
        "| 試作 | 条件 | 系列 | 現状 | 試作後 |",
        "|---|---|---|---|---|",
    ]
    changed = 0
    for variant in ("D5", "D6", "D5+D6"):
        for condition in CONDITIONS:
            for kind in TIMELINES:
                before = matrix["baseline"][condition.key][kind]
                after = matrix[variant][condition.key][kind]
                if before["first_optimized_cycle"] == after["first_optimized_cycle"]:
                    continue
                changed += 1
                lines.append(
                    f"| {variant} | {condition.label} | {TIMELINE_LABELS[kind]} "
                    f"| {_fire_cell(before)} | {_fire_cell(after)} |"
                )
    if not changed:
        lines.append("| - | 変化なし | - | - | - |")
    lines += NOTES
    return "\n".join(lines)


def main() -> None:
    matrix: dict = {}
    verdicts: dict = {}
    for variant in VARIANTS:
        matrix[variant] = {}
        verdicts[variant] = {}
        for condition in CONDITIONS:
            runs = {kind: run(condition, kind, variant) for kind in TIMELINES}
            matrix[variant][condition.key] = runs
            verdicts[variant][condition.key] = judge(condition, runs)
        if variant == "baseline":
            assert_premises(matrix)
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "setup": {
            "graph": "venue",
            "hot_edge": HOT,
            "cycles": CYCLES,
            "onset_cycle": ONSET + 1,
            "cut_cycle": CUT + 1,
            "probe_cycle": PROBE + 1,
            "surge_threshold_percent_per_min": CONFIG.surge_rate_threshold_percent_per_min,
            "arc_stats": {"p90": P90, "baseline": BASELINE, "eta": ETA, "span_h": LONG_SPAN_H},
        },
        "conditions": [
            {
                "key": c.key,
                "label": c.label,
                "spec": c.spec,
                "spec_fire": c.spec_fire,
                "spec_stagnation_only": c.spec_stagnation_only,
                "spec_short_tenant": c.spec_short_tenant,
            }
            for c in CONDITIONS
        ],
        "judgement": verdicts,
        "runs": matrix,
    }
    (RESULTS / "degradation_matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "degradation_matrix.md").write_text(render(matrix, verdicts), encoding="utf-8")
    print(render(matrix, verdicts))


if __name__ == "__main__":
    main()
