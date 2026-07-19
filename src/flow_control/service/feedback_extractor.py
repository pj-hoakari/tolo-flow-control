"""FeedbackExtractor Step.

外部 I/O を持たず、各 Step の結果だけをサービス境界の FeedbackValues に写像する。
"""

from __future__ import annotations

from collections import Counter

from ..detour_routing import DetourResult
from ..domain.enums import Mode
from ..domain.history import HistoryDigest
from ..forecasting import ForecastResult
from ..optimization import DirectionChangeType, OptimizeResult
from ..optimization.results import OptimizationResult
from .config import ResolvedConfig
from .feedback import (
    ComputeMeta,
    DetourMetrics,
    DirectionChangeSummary,
    FeedbackValues,
    ForecastSummary,
    ObjectiveValues,
    PredictionActualDiff,
    QualityMetrics,
    ReachabilityConstraints,
    ReferenceUsageReport,
    TagObservation,
)


def extract_feedback(
    forecast_result: ForecastResult,
    detour_result: DetourResult,
    optimize_result: OptimizeResult,
    previous_result: OptimizationResult | None,
    history_digest: HistoryDigest,
    config: ResolvedConfig,
    mode: Mode,
) -> FeedbackValues:
    """Extract the v0 feedback contract from completed module results."""
    result = optimize_result.optimization_result
    stats = optimize_result.solver_stats
    report = optimize_result.constraint_report
    fallback = forecast_result.fallback_usage

    tags = tuple(
        TagObservation(attribute_tag=item.edge_id.value, eta_estimate=item.eta, edge_count=1)
        for item in forecast_result.arc_flow_sensitivity
    )
    changes = Counter(proposal.change_type for proposal in result.direction_proposal)
    previous_objective = previous_result.objective_values if previous_result is not None else None
    prediction_diff = None
    if previous_objective is not None:
        prediction_diff = PredictionActualDiff(
            expected_tau_star=previous_objective.tau_star,
            actual_tau_star=result.objective_values.tau_star,
            delta=result.objective_values.tau_star - previous_objective.tau_star,
        )

    effective_paths = sum(item.k_effective for item in detour_result.detour_sets)
    return FeedbackValues(
        compute_meta=ComputeMeta(
            mode=mode,
            optimization_mode=config.optimization_mode,
            solver_phase1_ms=stats.phase1_ms,
            solver_phase2_ms=stats.phase2_ms,
            solver_phase1_status=stats.phase1_status.value,
            solver_phase2_status=stats.phase2_status.value,
            reachability_constraints=ReachabilityConstraints(
                local=report.local_reachability_satisfied,
                boundary=report.boundary_reachability_satisfied,
            ),
        ),
        objective_values=ObjectiveValues(
            tau_star=result.objective_values.tau_star,
            throughput=result.objective_values.throughput,
        ),
        per_tag_observations=tags,
        prediction_actual_diff=prediction_diff,
        reference_usage=ReferenceUsageReport(
            used_tags=tuple(item.attribute_tag for item in fallback.reference_sample_counts),
            used_default=bool(fallback.used_default_edges),
            used_edges_count=len(fallback.used_reference_edges),
        ),
        quality_metrics=QualityMetrics(
            vector_coverage_ratio=_coverage_ratio(forecast_result),
            low_confidence_arc_ratio=0.0,
            history_completeness=history_digest.completeness,
        ),
        detour_metrics=DetourMetrics(
            k_requested=config.k_shortest_paths,
            k_effective=effective_paths,
            paths_actually_used_ratio=0.0,
        ),
        direction_change_summary=DirectionChangeSummary(
            convert=changes[DirectionChangeType.CONVERT_ONEWAY],
            release=changes[DirectionChangeType.RELEASE_ONEWAY],
            flip=changes[DirectionChangeType.FLIP_ONEWAY],
        ),
        forecast_summary=ForecastSummary(
            node_demand=forecast_result.node_demand,
            reproduction_error=forecast_result.reproduction_error,
            estimation_resolution=forecast_result.estimation_resolution,
        ),
    )


def _coverage_ratio(result: ForecastResult) -> float:
    if not result.node_confidence:
        return 0.0
    covered = sum(1 for item in result.node_confidence if item.confidence > 0.0)
    return covered / len(result.node_confidence)
