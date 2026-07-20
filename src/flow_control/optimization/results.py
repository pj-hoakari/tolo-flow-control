from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..domain.graph import EdgeID, NodeID


class SolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    LIGHTWEIGHT = "LIGHTWEIGHT"


class Phase2Status(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"
    LIGHTWEIGHT = "LIGHTWEIGHT"


class ImportanceDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"
    NONE = "NONE"


class ProposedDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class DirectionChangeType(str, Enum):
    CONVERT_ONEWAY = "CONVERT_ONEWAY"
    RELEASE_ONEWAY = "RELEASE_ONEWAY"
    FLIP_ONEWAY = "FLIP_ONEWAY"
    KEEP = "KEEP"


class RestrictionAction(str, Enum):
    CLOSE = "CLOSE"
    LIMIT = "LIMIT"
    RESUME = "RESUME"


class RestrictionReason(str, Enum):
    UNDRAINABLE_STAGNATION = "UNDRAINABLE_STAGNATION"
    RESIDUAL_TAU = "RESIDUAL_TAU"
    PUNCTURE = "PUNCTURE"
    NODE_DANGER_UPSTREAM = "NODE_DANGER_UPSTREAM"
    # 需要が容量を構造的に超過（フォールバックのスラック使用）
    OVERLOAD = "OVERLOAD"


class BoundaryAction(str, Enum):
    PAUSE_INGRESS = "PAUSE_INGRESS"
    PAUSE_EGRESS = "PAUSE_EGRESS"
    RESUME = "RESUME"


@dataclass(frozen=True)
class RouteImportance:
    edge_id: EdgeID
    direction: ImportanceDirection
    importance: float  # 0.0-1.0（最大フローで正規化）
    valid_until_next_trigger: bool = True


@dataclass(frozen=True)
class DirectionProposal:
    edge_id: EdgeID
    proposed_direction: ProposedDirection
    confidence: float = 1.0  # v0 では固定値
    change_type: DirectionChangeType = DirectionChangeType.KEEP


@dataclass(frozen=True)
class RestrictionProposal:
    edge_id: EdgeID
    action: RestrictionAction
    limit_value: float | None
    reason: RestrictionReason
    confidence: float = 1.0
    scope_note: str = "operator review required"


@dataclass(frozen=True)
class BoundaryControl:
    node_id: NodeID
    action: BoundaryAction
    reason: str


@dataclass(frozen=True)
class ObjectiveValues:
    tau_star: float = 0.0
    throughput: float = 0.0


@dataclass(frozen=True)
class OptimizationResult:
    route_importance: tuple[RouteImportance, ...] = ()
    direction_proposal: tuple[DirectionProposal, ...] = ()
    restriction_proposal: tuple[RestrictionProposal, ...] = ()
    boundary_control: tuple[BoundaryControl, ...] = ()
    objective_values: ObjectiveValues = field(default_factory=ObjectiveValues)
    solver_status: SolverStatus = SolverStatus.OPTIMAL
    solved_at: datetime | None = None
    seed: int = 0


@dataclass(frozen=True)
class SolverStats:
    solver_name: str
    phase1_status: SolverStatus
    phase2_status: Phase2Status
    # 軽量モードでは「モデル構築＋配分 LP 求解の合計」を再解釈して格納する互換フィールド
    phase1_ms: int
    phase2_ms: int
    tau_star: float
    throughput: float
    # 配分 LP 求解時間の合計（ベースライン＋貪欲候補＋フォールバック）
    assign_lp_ms: int = 0
    greedy_iterations: int = 0
    zones_processed: int = 0
    tau_residual: float = 0.0
    # モデル構築時間の合計（軽量モード。求解と並ぶ支配的コストのため独立計上）
    build_ms: int = 0
    # 貪欲探索の所要合計（候補の構築＋求解＋検査）
    greedy_ms: int = 0
    # 予算枯渇により貪欲探索を打ち切ったか
    greedy_truncated: bool = False
    # ゾーン数が max_trigger_zones を超え重大度上位のみ処理したか（LOCALIZATION_CAPPED 相当）
    localization_capped: bool = False
    # Forecasting から受けた OD ペア数（delta_min カット前）
    od_pairs_input: int = 0
    # delta_min カット後に最適化へ入ったコモディティ数
    commodities_used: int = 0
    # OD はあったのに delta_min で全カットされた（発火したのに提案が空になる主因）
    demand_all_cut: bool = False


@dataclass(frozen=True)
class ConstraintReport:
    local_reachability_satisfied: bool
    boundary_reachability_satisfied: bool
    legal_fixed_violations: tuple[EdgeID, ...]
    # 前回結果（previous_result）の内容を返しているか（差し戻し）
    fallback_to_previous: bool
    # 劣化経路（方向固定・容量スラック LP）による新提案か。
    # fallback_to_previous と独立で、「劣化した新提案」と「前回への差し戻し」を区別する
    degraded_mode: bool = False


@dataclass(frozen=True)
class OptimizeResult:
    optimization_result: OptimizationResult
    solver_stats: SolverStats
    constraint_report: ConstraintReport
