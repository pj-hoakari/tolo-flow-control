"""サービス境界層

外部と交換する I/O 契約（Request / Response / TenantContext / Verdict /
Diagnostics / FeedbackValues）と、マージ済み設定の統一 ResolvedConfig を定義する。
"""

from .config import OptimizationMode, ResolvedConfig, ThroughputWeights
from .context import TenantCategory, TenantContext
from .diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    Diagnostics,
    FallbackKind,
    FallbackRecord,
    StepKind,
    StepRecord,
    StepStatus,
    TriggerEvidence,
    TriggerEvidenceSource,
    Warning,
    WarningCode,
)
from .feedback import (
    FEEDBACK_SCHEMA_VERSION,
    AbDiff,
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
    RestrictionMetrics,
    RestrictionReason,
    TagObservation,
)
from .messages import REQUEST_SCHEMA_VERSION, Request, Response
from .verdict import Verdict

__all__ = [
    "DIAGNOSTICS_SCHEMA_VERSION",
    "FEEDBACK_SCHEMA_VERSION",
    "REQUEST_SCHEMA_VERSION",
    "AbDiff",
    "ComputeMeta",
    "DetourMetrics",
    "Diagnostics",
    "DirectionChangeSummary",
    "FallbackKind",
    "FallbackRecord",
    "FeedbackValues",
    "ForecastSummary",
    "ObjectiveValues",
    "OptimizationMode",
    "PredictionActualDiff",
    "QualityMetrics",
    "ReachabilityConstraints",
    "ReferenceUsageReport",
    "Request",
    "ResolvedConfig",
    "Response",
    "RestrictionMetrics",
    "RestrictionReason",
    "StepKind",
    "StepRecord",
    "StepStatus",
    "TagObservation",
    "TenantCategory",
    "TenantContext",
    "ThroughputWeights",
    "TriggerEvidence",
    "TriggerEvidenceSource",
    "Verdict",
    "Warning",
    "WarningCode",
]
