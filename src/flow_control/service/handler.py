"""RequestHandler / Orchestration implementation specified in design v0."""

from __future__ import annotations

import math
import time
from dataclasses import replace

from ..detection import DetectionResult, VerdictHint, detect
from ..detection.config import ResolvedConfig as DetectionConfig
from ..detection.state import DetectionState, QueuedTrigger, QueuedTriggerKind
from ..detour_routing import route_detour
from ..detour_routing.config import ResolvedConfig as DetourConfig
from ..domain.enums import Mode
from ..forecasting import forecast
from ..forecasting.config import ResolvedConfig as ForecastConfig
from ..optimization import optimize
from ..optimization.config import OptimizationMode as ModuleOptimizationMode
from ..optimization.config import ResolvedConfig as OptimizationConfig
from ..optimization.results import OptimizationResult, SolverStatus
from .config import ResolvedConfig as ServiceConfig
from .diagnostics import Diagnostics, StepKind, StepRecord, StepStatus, Warning, WarningCode
from .feedback import FeedbackValues
from .feedback_extractor import extract_feedback
from .messages import REQUEST_SCHEMA_VERSION, Request, Response
from .verdict import Verdict

GRAPH_NODE_LIMIT = 10
GRAPH_EDGE_LIMIT = 50
BUFFER_SEC = 60.0
MIN_OPT_BUDGET = 30.0


def handle_request(req: Request) -> Response:
    """Run one stateless Detection → Forecasting → Detour → Optimization cycle."""
    started = time.perf_counter()
    validation_errors = _validation_errors(req)
    if validation_errors:
        return _response(req, Verdict.ERROR_INVALID_INPUT, req.detection_state, started,
                         diagnostics=Diagnostics(steps_executed=(_step(StepKind.VALIDATION, started),)))
    if len(req.graph.nodes) > GRAPH_NODE_LIMIT or len(req.graph.edges) > GRAPH_EDGE_LIMIT:
        return _response(req, Verdict.ERROR_SIZE_EXCEEDED, req.detection_state, started,
                         diagnostics=Diagnostics(steps_executed=(_step(StepKind.VALIDATION, started),)))

    mode = Mode.OPEN if req.graph.boundary_nodes() else Mode.CLOSED
    steps = [_step(StepKind.VALIDATION, started), _step(StepKind.MODE_DECISION, started)]
    detection_started = time.perf_counter()
    detection = detect(
        req.graph, req.observations, req.history_digest, req.detection_state, req.events,
        _detection_config(req.config), req.server_time, req.references,
    )
    steps.append(_step(StepKind.DETECTION, detection_started))
    warnings = _detection_warnings(detection)

    early_verdict = _verdict_of(detection.verdict_hint)
    if early_verdict is not None:
        return _response(
            req, early_verdict, finalize_detection_state(detection, early_verdict, req), started,
            diagnostics=Diagnostics(mode=mode, warnings=warnings, steps_executed=tuple(steps)),
        )

    final_retry = req.detection_state.consecutive_skip_count >= req.config.max_consecutive_skips
    opt_cap = req.config.lightweight_opt_budget_sec if req.config.optimization_mode.value == "LIGHTWEIGHT" else req.config.milp_time_limit_sec
    cycle_budget = req.config.forecasting_budget_sec + req.config.detour_budget_sec + opt_cap + BUFFER_SEC
    if final_retry:
        cycle_budget *= 2

    forecast_started = time.perf_counter()
    forecast_result = forecast(
        req.graph, detection.effective_snapshot, req.history_digest, req.references,
        detection.triggered_edges, _forecast_config(req.config), mode,
    )
    steps.append(_step(StepKind.FORECASTING, forecast_started))
    detour_started = time.perf_counter()
    detour_result = route_detour(req.graph, detection.triggered_edges, forecast_result, _detour_config(req.config), mode)
    steps.append(_step(StepKind.DETOUR, detour_started))

    remaining = cycle_budget - (time.perf_counter() - started) - BUFFER_SEC
    opt_budget = min(max(MIN_OPT_BUDGET, remaining), opt_cap * (2 if final_retry else 1))
    optimization_started = time.perf_counter()
    optimize_result = optimize(
        req.graph, detection.effective_snapshot, forecast_result, detour_result,
        req.history_digest, req.previous_result, _optimization_config(req.config),
        req.config.solver_seed, opt_budget, mode,
        triggered_edges=detection.triggered_edges, triggered_nodes=detection.triggered_nodes,
    )
    steps.append(_step(StepKind.OPTIMIZATION, optimization_started))
    if optimize_result.optimization_result.solver_status is SolverStatus.TIMEOUT:
        if final_retry:
            warnings += (Warning(WarningCode.SOLVER_GIVEUP),)
        return _response(
            req, Verdict.SKIPPED_TIME, finalize_detection_state(detection, Verdict.SKIPPED_TIME, req), started,
            diagnostics=Diagnostics(mode=mode, warnings=warnings, steps_executed=tuple(steps)),
        )

    feedback_started = time.perf_counter()
    feedback = extract_feedback(forecast_result, detour_result, optimize_result, req.previous_result,
                                req.history_digest, req.config, mode)
    steps.append(_step(StepKind.FEEDBACK, feedback_started))
    state = _with_demand_digest(finalize_detection_state(detection, Verdict.OPTIMIZED, req), forecast_result)
    return _response(
        req, Verdict.OPTIMIZED, state, started, feedback=feedback,
        optimization_result=optimize_result.optimization_result,
        diagnostics=Diagnostics(mode=mode, warnings=warnings, steps_executed=tuple(steps)),
    )


def finalize_detection_state(det: DetectionResult, verdict: Verdict, req: Request) -> DetectionState:
    """Commit Detection's transition candidate according to module design §4.9."""
    if verdict is Verdict.OPTIMIZED:
        return replace(det.new_state, consecutive_skip_count=0)
    if verdict is not Verdict.SKIPPED_TIME:
        return det.new_state
    if req.detection_state.consecutive_skip_count >= req.config.max_consecutive_skips:
        return replace(det.abort_state, trigger_queue=(), consecutive_skip_count=0)
    return replace(
        det.abort_state,
        trigger_queue=det.abort_state.trigger_queue + _requeued_triggers(det, req),
        consecutive_skip_count=req.detection_state.consecutive_skip_count + 1,
    )


def _requeued_triggers(det: DetectionResult, req: Request) -> tuple[QueuedTrigger, ...]:
    return tuple(
        QueuedTrigger(QueuedTriggerKind.SURGE, req.server_time, req.server_time, origin_edge_id=edge_id,
                      snapshot_ref=det.effective_snapshot.snapshot_ref)
        for edge_id in det.triggered_edges
    ) + tuple(
        QueuedTrigger(QueuedTriggerKind.DANGER, req.server_time, req.server_time, origin_node_id=node_id,
                      snapshot_ref=det.effective_snapshot.snapshot_ref)
        for node_id in det.triggered_nodes
    )


def _with_demand_digest(state: DetectionState, forecast_result: object) -> DetectionState:
    # ForecastResult currently exposes node demand and OD demand, but not the
    # edge-arrival demand lambda_hat required by DetectionState.  Preserve the
    # previous digest rather than writing an unrelated quantity such as eta.
    # The adapter is deliberately isolated here for the Forecasting contract's
    # future edge-demand output.
    del forecast_result
    return state


def _response(req: Request, verdict: Verdict, state: DetectionState, started: float, *,
              diagnostics: Diagnostics, feedback: FeedbackValues | None = None,
              optimization_result: OptimizationResult | None = None) -> Response:
    return Response(request_id=req.request_id, verdict=verdict, updated_detection_state=state,
                    feedback_values=feedback or FeedbackValues(), diagnostics=diagnostics,
                    optimization_result=optimization_result, elapsed_ms=int((time.perf_counter() - started) * 1000))


def _step(step: StepKind, started: float) -> StepRecord:
    return StepRecord(step=step, elapsed_ms=int((time.perf_counter() - started) * 1000), status=StepStatus.OK)


def _verdict_of(hint: VerdictHint) -> Verdict | None:
    return {
        VerdictHint.QUEUED: Verdict.QUEUED,
        VerdictHint.SKIPPED_COOLDOWN: Verdict.SKIPPED_COOLDOWN,
        VerdictHint.SKIPPED_WARMUP: Verdict.SKIPPED_WARMUP,
        VerdictHint.NO_TRIGGER: Verdict.SKIPPED_NO_TRIGGER,
    }.get(hint)


def _detection_warnings(det: DetectionResult) -> tuple[Warning, ...]:
    result: list[Warning] = []
    for item in det.warnings:
        code = WarningCode[item.code.value]
        result.append(Warning(code=code, context=(("edge_id", item.edge_id.value if item.edge_id else ""),)))
    return tuple(result)


def _validation_errors(req: Request) -> tuple[str, ...]:
    errors: list[str] = []
    if req.schema_version != REQUEST_SCHEMA_VERSION or not req.request_id or not req.tenant_context.tenant_id:
        errors.append("request metadata")
    node_ids = [node.node_id for node in req.graph.nodes]
    edge_ids = [edge.edge_id for edge in req.graph.edges]
    node_set, edge_set = set(node_ids), set(edge_ids)
    if len(node_set) != len(node_ids) or len(edge_set) != len(edge_ids):
        errors.append("duplicate graph id")
    if any(edge.endpoint_a not in node_set or edge.endpoint_b not in node_set for edge in req.graph.edges):
        errors.append("edge endpoint")
    cfg = req.config
    positive = (cfg.forecasting_budget_sec, cfg.detour_budget_sec, cfg.lightweight_opt_budget_sec,
                cfg.milp_time_limit_sec, cfg.puncture_ratio_threshold)
    if (cfg.cooldown_duration_min < 10 or any(not math.isfinite(value) or value <= 0 for value in positive)
            or cfg.max_consecutive_skips < 1 or not 0 <= cfg.confidence_weight_floor <= 1
            or cfg.k_shortest_paths < 1 or cfg.local_radius_hops < 1 or cfg.max_trigger_zones < 1
            or cfg.greedy_improve_margin < 0):
        errors.append("config range")
    return tuple(errors)


def _detection_config(cfg: ServiceConfig) -> DetectionConfig:
    return DetectionConfig(
        surge_rate_threshold_percent_per_min=cfg.surge_rate_threshold_percent_per_min,
        high_stagnation_duration_min=cfg.high_stagnation_duration_min, beta=cfg.beta,
        theta_demand=cfg.theta_demand, cooldown_duration_min=cfg.cooldown_duration_min,
        queue_score_threshold=cfg.queue_score_threshold, queue_diversity_threshold=cfg.queue_diversity_threshold,
        queue_freshness_min=cfg.queue_freshness_min, warmup_duration_min=cfg.warmup_duration_min,
        retrigger_warning_threshold=cfg.retrigger_warning_threshold,
        retrigger_reset_quiet_cycles=cfg.retrigger_reset_quiet_cycles,
        max_consecutive_skips=cfg.max_consecutive_skips, puncture_trigger_enabled=cfg.puncture_trigger_enabled,
        puncture_ratio_threshold=cfg.puncture_ratio_threshold,
        fallback_baseline_stagnation=cfg.fallback_baseline_stagnation,
        min_reference_sample_count=cfg.min_reference_sample_count, epsilon_0=cfg.epsilon_0,
    )


def _forecast_config(cfg: ServiceConfig) -> ForecastConfig:
    return ForecastConfig(
        min_reference_sample_count=cfg.min_reference_sample_count, fallback_eta=cfg.fallback_eta,
        gravity_alpha=cfg.gravity_alpha, delta_min=cfg.delta_min,
        transit_time_prior_sec=cfg.transit_time_prior_sec, dwell_time_prior_sec=cfg.dwell_time_prior_sec,
        ipf_max_iter=cfg.ipf_max_iter, ipf_tolerance=cfg.ipf_tolerance, epsilon_0=cfg.epsilon_0,
    )


def _detour_config(cfg: ServiceConfig) -> DetourConfig:
    return DetourConfig(k_shortest=cfg.k_shortest_paths)


def _optimization_config(cfg: ServiceConfig) -> OptimizationConfig:
    return OptimizationConfig(
        optimization_mode=ModuleOptimizationMode(cfg.optimization_mode.value), local_radius_hops=cfg.local_radius_hops,
        max_trigger_zones=cfg.max_trigger_zones, greedy_improve_margin=cfg.greedy_improve_margin,
        lightweight_opt_budget_sec=cfg.lightweight_opt_budget_sec,
        restriction_proposal_enabled=cfg.restriction_proposal_enabled, tau_danger_threshold=cfg.tau_danger_threshold,
        solver_seed=cfg.solver_seed, milp_time_limit_sec=cfg.milp_time_limit_sec, epsilon=cfg.epsilon,
        epsilon_0=cfg.epsilon_0, big_m_factor=cfg.big_m_factor, delta_min=cfg.delta_min,
        confidence_weight_floor=cfg.confidence_weight_floor, throughput_target_edges=cfg.throughput_target_edges,
        fallback_baseline_stagnation=cfg.fallback_baseline_stagnation, mip_rel_gap=cfg.mip_rel_gap,
    )
