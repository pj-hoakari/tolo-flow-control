"""Diagnostics と、FeedbackValues と共有する Warning

本サービス処理の透過性を確保するための情報集合。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..domain.enums import Mode

DIAGNOSTICS_SCHEMA_VERSION = "diagnostics/2"


class WarningCode(str, Enum):
    RETRIGGER = "RETRIGGER"
    SIZE_NEAR_LIMIT = "SIZE_NEAR_LIMIT"
    CONSTRAINT_NEAR = "CONSTRAINT_NEAR"
    LOW_COVERAGE = "LOW_COVERAGE"
    FALLBACK_APPLIED = "FALLBACK_APPLIED"
    QUEUE_EXPIRED = "QUEUE_EXPIRED"  # キュー鮮度切れ破棄
    SOLVER_GIVEUP = "SOLVER_GIVEUP"  # 連続スキップ上限による再試行断念
    UNDRAINABLE_EDGE = "UNDRAINABLE_EDGE"  # 排出可能エッジ集合からの除外
    MANY_TRIGGER_ZONES = "MANY_TRIGGER_ZONES"  # 散在トリガーでゾーン上限到達（基本モード）
    LOW_CONFIDENCE_PROPOSAL = "LOW_CONFIDENCE_PROPOSAL"  # DISTANCE_PRIOR ゾーン由来の低信頼提案
    INSUFFICIENT_WINDOW_SAMPLES = "INSUFFICIENT_WINDOW_SAMPLES"  # 窓内有効サンプル不足
    SURGE_PROXY_FALLBACK = "SURGE_PROXY_FALLBACK"  # ラインなしで急増を停滞プロキシ傾き代替
    DEGRADED_COMBINED_TRIGGER = "DEGRADED_COMBINED_TRIGGER"  # 需要警戒全面縮退で停滞単独発火


@dataclass(frozen=True)
class Warning:
    code: WarningCode
    context: tuple[tuple[str, object], ...] = ()  # Map<string, any>


class TriggerEvidenceSource(str, Enum):
    SURGE = "SURGE"
    HIGH_STAGNATION = "HIGH_STAGNATION"
    PUNCTURE = "PUNCTURE"  # 前処理 P 由来
    DANGER = "DANGER"
    QUEUE_SCORE = "QUEUE_SCORE"
    QUEUE_DIVERSITY = "QUEUE_DIVERSITY"


@dataclass(frozen=True)
class TriggerEvidence:
    source: TriggerEvidenceSource
    occurred_at: datetime
    edge_id: str | None = None
    node_id: str | None = None
    metric_value: float | None = None  # 例：傾き %/分、停滞プロキシ
    threshold_value: float | None = None
    duration_min: float | None = None


class FallbackKind(str, Enum):
    REFERENCE_USED = "REFERENCE_USED"
    DEFAULT_ETA_USED = "DEFAULT_ETA_USED"
    PERCENTILE_DEGRADED = "PERCENTILE_DEGRADED"
    DIRECTION_PROPOSAL_HELD = "DIRECTION_PROPOSAL_HELD"
    PHASE2_SKIPPED = "PHASE2_SKIPPED"
    BUDGET_EXTENDED = "BUDGET_EXTENDED"
    FORECAST_PRIOR_DEGRADED = "FORECAST_PRIOR_DEGRADED"
    FORECAST_ARC_IMPUTED = "FORECAST_ARC_IMPUTED"
    INFEASIBLE_LP_RELAXED = "INFEASIBLE_LP_RELAXED"
    DETOUR_TRUNCATED = "DETOUR_TRUNCATED"
    # 以下は基本モード（軽量分解）由来
    LP_INFEASIBLE_HELD = "LP_INFEASIBLE_HELD"
    GREEDY_NO_IMPROVEMENT = "GREEDY_NO_IMPROVEMENT"
    LOCALIZATION_CAPPED = "LOCALIZATION_CAPPED"
    RESTRICTION_PROPOSED = "RESTRICTION_PROPOSED"


@dataclass(frozen=True)
class FallbackRecord:
    kind: FallbackKind
    reason: str
    affected_targets: tuple[str, ...] = ()  # edge_id / node_id / target_key


class StepKind(str, Enum):
    VALIDATION = "VALIDATION"
    MODE_DECISION = "MODE_DECISION"
    EVENTS_APPLY = "EVENTS_APPLY"
    DETECTION = "DETECTION"
    FORECASTING = "FORECASTING"
    DETOUR = "DETOUR"
    OPTIMIZATION = "OPTIMIZATION"
    FEEDBACK = "FEEDBACK"


class StepStatus(str, Enum):
    OK = "OK"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StepRecord:
    step: StepKind
    elapsed_ms: int
    status: StepStatus
    # 基本モードの OPTIMIZATION サブステップ（ASSIGN_LP / DIRECTION_GREEDY / RESTRICTION）を識別
    note: str | None = None


@dataclass(frozen=True)
class Diagnostics:
    mode: Mode = Mode.CLOSED
    warnings: tuple[Warning, ...] = ()
    trigger_evidences: tuple[TriggerEvidence, ...] = ()
    fallbacks_applied: tuple[FallbackRecord, ...] = ()
    steps_executed: tuple[StepRecord, ...] = ()
    degraded_short_tenant: bool = False  # 縮退モード適用有無
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION
