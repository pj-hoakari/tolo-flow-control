from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..domain.graph import EdgeID, NodeID


class SolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"


class Phase2Status(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class ImportanceDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"
    NONE = "NONE"


class ProposedDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"
    BIDIRECTIONAL = "BIDIRECTIONAL"


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
    phase1_ms: int
    phase2_ms: int
    tau_star: float
    throughput: float


@dataclass(frozen=True)
class ConstraintReport:
    local_reachability_satisfied: bool
    boundary_reachability_satisfied: bool
    legal_fixed_violations: tuple[EdgeID, ...]
    fallback_to_previous: bool


@dataclass(frozen=True)
class OptimizeResult:
    optimization_result: OptimizationResult
    solver_stats: SolverStats
    constraint_report: ConstraintReport
