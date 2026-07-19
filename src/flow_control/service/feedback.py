"""FeedbackValues

各モジュールの中間結果から、外部が匿名化・集約・蓄積するためのフィードバック値。
本 Phase ではスキーマ（データ契約）のみを定義する。抽出ロジック（FeedbackExtractor）は
後続 Phase で実装する。各フィールドは独立で、欠落しても他に影響しない設計とする。
"""

from dataclasses import dataclass, field
from enum import Enum

from ..domain.enums import Mode
from ..forecasting.demand import NodeDemand
from ..forecasting.od import NodeResolution
from .config import OptimizationMode
from .diagnostics import Warning

FEEDBACK_SCHEMA_VERSION = "feedback/3"


@dataclass(frozen=True)
class ObjectiveValues:
    tau_star: float = 0.0
    throughput: float = 0.0


@dataclass(frozen=True)
class ReachabilityConstraints:
    local: bool = False
    boundary: bool = False  # 基本モードでは後段 BFS 合否


@dataclass(frozen=True)
class ComputeMeta:
    mode: Mode = Mode.CLOSED
    optimization_mode: OptimizationMode = OptimizationMode.LIGHTWEIGHT
    solver_phase1_ms: int = 0  # 基本モードでは配分 LP 合計の意味
    solver_phase2_ms: int = 0  # 基本モードでは貪欲探索合計の意味
    solver_phase1_status: str = ""  # 基本モードは "LIGHTWEIGHT"
    solver_phase2_status: str = ""
    reachability_constraints: ReachabilityConstraints = field(
        default_factory=ReachabilityConstraints
    )


@dataclass(frozen=True)
class TagObservation:
    attribute_tag: str
    eta_estimate: float
    edge_count: int = 0  # このタグで貢献したアーク数
    observation_span_min: float = 0.0


@dataclass(frozen=True)
class PredictionActualDiff:
    expected_tau_star: float
    actual_tau_star: float
    delta: float


@dataclass(frozen=True)
class ReferenceUsageReport:
    used_tags: tuple[str, ...] = ()
    used_default: bool = False
    used_edges_count: int = 0


@dataclass(frozen=True)
class QualityMetrics:
    vector_coverage_ratio: float = 0.0  # 0.0-1.0
    low_confidence_arc_ratio: float = 0.0
    history_completeness: float = 0.0


@dataclass(frozen=True)
class DetourMetrics:
    k_requested: int = 0  # 要求した k
    k_effective: int = 0  # 取得できた本数
    paths_actually_used_ratio: float = 0.0  # 0.0–1.0（最適解で f > 0 のパス比率）


class RestrictionReason(str, Enum):
    UNDRAINABLE_STAGNATION = "UNDRAINABLE_STAGNATION"
    RESIDUAL_TAU = "RESIDUAL_TAU"
    PUNCTURE = "PUNCTURE"
    NODE_DANGER_UPSTREAM = "NODE_DANGER_UPSTREAM"


@dataclass(frozen=True)
class RestrictionMetrics:
    proposed_count: int = 0
    by_reason: tuple[tuple[RestrictionReason, int], ...] = ()
    estimated_inflow_cut: float = 0.0  # 推定削減フロー量（人/分）
    undrainable_origin_ratio: float = 0.0


@dataclass(frozen=True)
class DirectionChangeSummary:
    convert: int = 0
    release: int = 0
    flip: int = 0


@dataclass(frozen=True)
class ForecastSummary:
    node_demand: tuple[NodeDemand, ...] = ()  # 点別の生成・吸収・通過・滞在
    reproduction_error: float = 0.0  # Step C のリンク再現残差
    estimation_resolution: tuple[NodeResolution, ...] = ()  # 点／区間ごとの推定解像度


@dataclass(frozen=True)
class AbDiff:
    enabled_extensions: tuple[str, ...] = ()  # shadow 実行で有効化された拡張コード
    shadow_tau_star: float = 0.0
    actual_tau_star: float = 0.0
    shadow_throughput: float = 0.0
    actual_throughput: float = 0.0
    diff_summary: str = ""


@dataclass(frozen=True, kw_only=True)
class FeedbackValues:
    schema_version: str = FEEDBACK_SCHEMA_VERSION
    compute_meta: ComputeMeta = field(default_factory=ComputeMeta)
    objective_values: ObjectiveValues = field(default_factory=ObjectiveValues)
    per_tag_observations: tuple[TagObservation, ...] = ()  # 属性タグ別 η_e 推定値
    prediction_actual_diff: PredictionActualDiff | None = None  # previous_result 有時
    reference_usage: ReferenceUsageReport = field(default_factory=ReferenceUsageReport)
    quality_metrics: QualityMetrics = field(default_factory=QualityMetrics)
    detour_metrics: DetourMetrics | None = None  # ロードマップ項目 C 連携
    restriction_metrics: RestrictionMetrics | None = None  # 機能2 有効時
    direction_change_summary: DirectionChangeSummary = field(
        default_factory=DirectionChangeSummary
    )  # 機能1
    ab_diff: AbDiff | None = None  # config.shadow_extensions が空でない場合のみ
    forecast_summary: ForecastSummary | None = None  # 需要予測サマリ
    warnings: tuple[Warning, ...] = ()
