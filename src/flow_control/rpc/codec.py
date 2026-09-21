from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import cast

from google.protobuf import empty_pb2, timestamp_pb2
from google.protobuf.message import Message

from flow_control.detection.state import (
    ArcDemandDigestEntry,
    ArcWatchState,
    DetectionState,
    QueuedTrigger,
    QueuedTriggerKind,
    RetriggerEntry,
    WarmupState,
)
from flow_control.detection.triggers import Event, EventKind
from flow_control.domain.enums import (
    CurrentDirection,
    DirectionConstraint,
    FlowDirection,
    Mode,
    NodeKind,
    ObservationType,
)
from flow_control.domain.graph import Edge, EdgeID, Graph, Node, NodeID
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from flow_control.domain.observations import (
    ArcFlow,
    ArcScalarFlow,
    ArcStagnation,
    ConfidenceFlag,
    NodeOccupancy,
    Observations,
    StagnationDerivation,
    TurningObservation,
)
from flow_control.domain.references import (
    Reference,
    TagReference,
    ThresholdDefaults,
    ThresholdSet,
)
from flow_control.forecasting.demand import NodeDemand
from flow_control.forecasting.od import NodeResolution, ODResolutionMode, ODResolutionReason
from flow_control.optimization.results import (
    BoundaryAction,
    BoundaryControl,
    DetourPathProposal,
    DirectionChangeType,
    DirectionProposal,
    ImportanceDirection,
    OptimizationResult,
    ProposedDirection,
    RestrictionAction,
    RestrictionProposal,
    RouteImportance,
    SolverStatus,
)
from flow_control.optimization.results import ObjectiveValues as OptimizationObjectiveValues
from flow_control.optimization.results import RestrictionReason as OptimizationRestrictionReason
from flow_control.rpc.generated.tolo.flow.v1 import flow_pb2 as pb
from flow_control.service.config import OptimizationMode, ResolvedConfig, ThroughputWeights
from flow_control.service.context import TenantCategory, TenantContext
from flow_control.service.diagnostics import (
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
from flow_control.service.feedback import (
    AbDiff,
    ComputeMeta,
    DetourMetrics,
    DirectionChangeSummary,
    FeedbackValues,
    ForecastSummary,
    PredictionActualDiff,
    QualityMetrics,
    ReachabilityConstraints,
    ReferenceUsageReport,
    RestrictionMetrics,
    TagObservation,
)
from flow_control.service.feedback import ObjectiveValues as FeedbackObjectiveValues
from flow_control.service.feedback import RestrictionReason as FeedbackRestrictionReason
from flow_control.service.messages import Request, Response
from flow_control.service.verdict import Verdict


def _enum_to_wire[K, W](value: Enum, mapping: Mapping[K, W], name: str) -> W:
    try:
        return mapping[cast(K, value)]
    except KeyError as exc:
        raise ValueError(f"unknown {name}: {value!r}") from exc


def _enum_from_wire[K, E: Enum](value: int, mapping: Mapping[K, E], name: str) -> E:
    try:
        return mapping[cast(K, value)]
    except KeyError as exc:
        raise ValueError(f"unknown {name}: {value}") from exc


def _required(message: Message, field: str) -> object:
    descriptor = message.DESCRIPTOR.fields_by_name[field]
    if descriptor.has_presence and not message.HasField(field):
        raise ValueError(f"missing {field}")
    return cast(object, getattr(message, field))


def _required_string(message: Message, field: str) -> str:
    value = _required(message, field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"empty {field}")
    return value


def _optional_string(message: Message, field: str) -> str | None:
    if not message.HasField(field):
        return None
    value = cast(object, getattr(message, field))
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    return value


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"non-finite {name}")
    return value


def _datetime(value: datetime, name: str) -> timestamp_pb2.Timestamp:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"naive {name}")
    result = timestamp_pb2.Timestamp()
    result.FromDatetime(value.astimezone(UTC))
    return result


def _decode_datetime(value: timestamp_pb2.Timestamp, name: str) -> datetime:
    try:
        return value.ToDatetime(tzinfo=UTC)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc


def _copy_timestamp(target: Message, field: str, value: datetime, name: str) -> None:
    cast(Message, getattr(target, field)).CopyFrom(_datetime(value, name))


def _decode_required_datetime(message: Message, field: str) -> datetime:
    return _decode_datetime(cast(timestamp_pb2.Timestamp, _required(message, field)), field)


def _decode_optional_datetime(message: Message, field: str) -> datetime | None:
    if not message.HasField(field):
        return None
    return _decode_datetime(cast(timestamp_pb2.Timestamp, getattr(message, field)), field)


_NODE_KIND_TO_WIRE = {
    NodeKind.GOAL: pb.NODE_KIND_GOAL,
    NodeKind.GOAL_TRANSIT_MIXED: pb.NODE_KIND_GOAL_TRANSIT_MIXED,
    NodeKind.TRANSIT_ONLY: pb.NODE_KIND_TRANSIT_ONLY,
}
_NODE_KIND_FROM_WIRE = {v: k for k, v in _NODE_KIND_TO_WIRE.items()}
_DIRECTION_CONSTRAINT_TO_WIRE = {
    DirectionConstraint.BIDIRECTIONAL_PRIOR: pb.DIRECTION_CONSTRAINT_BIDIRECTIONAL_PRIOR,
    DirectionConstraint.ONEWAY_A_TO_B_PRIOR: pb.DIRECTION_CONSTRAINT_ONEWAY_A_TO_B_PRIOR,
    DirectionConstraint.ONEWAY_B_TO_A_PRIOR: pb.DIRECTION_CONSTRAINT_ONEWAY_B_TO_A_PRIOR,
    DirectionConstraint.LEGAL_FIXED_A_TO_B: pb.DIRECTION_CONSTRAINT_LEGAL_FIXED_A_TO_B,
    DirectionConstraint.LEGAL_FIXED_B_TO_A: pb.DIRECTION_CONSTRAINT_LEGAL_FIXED_B_TO_A,
    DirectionConstraint.LEGAL_FIXED_BIDIRECTIONAL: pb.DIRECTION_CONSTRAINT_LEGAL_FIXED_BIDIRECTIONAL,
}
_DIRECTION_CONSTRAINT_FROM_WIRE = {v: k for k, v in _DIRECTION_CONSTRAINT_TO_WIRE.items()}
_CURRENT_DIRECTION_TO_WIRE = {
    CurrentDirection.A_TO_B: pb.CURRENT_DIRECTION_A_TO_B,
    CurrentDirection.B_TO_A: pb.CURRENT_DIRECTION_B_TO_A,
    CurrentDirection.BIDIRECTIONAL: pb.CURRENT_DIRECTION_BIDIRECTIONAL,
}
_CURRENT_DIRECTION_FROM_WIRE = {v: k for k, v in _CURRENT_DIRECTION_TO_WIRE.items()}
_OBSERVATION_TYPE_TO_WIRE = {
    ObservationType.VECTOR: pb.OBSERVATION_TYPE_VECTOR,
    ObservationType.SCALAR: pb.OBSERVATION_TYPE_SCALAR,
}
_OBSERVATION_TYPE_FROM_WIRE = {v: k for k, v in _OBSERVATION_TYPE_TO_WIRE.items()}
_FLOW_DIRECTION_TO_WIRE = {
    FlowDirection.A_TO_B: pb.FLOW_DIRECTION_A_TO_B,
    FlowDirection.B_TO_A: pb.FLOW_DIRECTION_B_TO_A,
}
_FLOW_DIRECTION_FROM_WIRE = {v: k for k, v in _FLOW_DIRECTION_TO_WIRE.items()}
_CONFIDENCE_FLAG_TO_WIRE = {
    ConfidenceFlag.OK: pb.CONFIDENCE_FLAG_OK,
    ConfidenceFlag.HOLD: pb.CONFIDENCE_FLAG_HOLD,
    ConfidenceFlag.INVALID: pb.CONFIDENCE_FLAG_INVALID,
}
_CONFIDENCE_FLAG_FROM_WIRE = {v: k for k, v in _CONFIDENCE_FLAG_TO_WIRE.items()}
_STAGNATION_DERIVATION_TO_WIRE = {
    StagnationDerivation.BASIC: pb.STAGNATION_DERIVATION_BASIC,
    StagnationDerivation.REFINED: pb.STAGNATION_DERIVATION_REFINED,
}
_STAGNATION_DERIVATION_FROM_WIRE = {v: k for k, v in _STAGNATION_DERIVATION_TO_WIRE.items()}
_TENANT_CATEGORY_TO_WIRE = {
    TenantCategory.SHORT_TERM: pb.TENANT_CATEGORY_SHORT_TERM,
    TenantCategory.LONG_TERM: pb.TENANT_CATEGORY_LONG_TERM,
}
_TENANT_CATEGORY_FROM_WIRE = {v: k for k, v in _TENANT_CATEGORY_TO_WIRE.items()}
_OPTIMIZATION_MODE_TO_WIRE = {
    OptimizationMode.LIGHTWEIGHT: pb.OPTIMIZATION_MODE_LIGHTWEIGHT,
    OptimizationMode.STRICT: pb.OPTIMIZATION_MODE_STRICT,
}
_OPTIMIZATION_MODE_FROM_WIRE = {v: k for k, v in _OPTIMIZATION_MODE_TO_WIRE.items()}
_VERDICT_TO_WIRE = {
    Verdict.OPTIMIZED: pb.VERDICT_OPTIMIZED,
    Verdict.QUEUED: pb.VERDICT_QUEUED,
    Verdict.SKIPPED_NO_TRIGGER: pb.VERDICT_SKIPPED_NO_TRIGGER,
    Verdict.SKIPPED_COOLDOWN: pb.VERDICT_SKIPPED_COOLDOWN,
    Verdict.SKIPPED_WARMUP: pb.VERDICT_SKIPPED_WARMUP,
    Verdict.SKIPPED_TIME: pb.VERDICT_SKIPPED_TIME,
    Verdict.ERROR_SIZE_EXCEEDED: pb.VERDICT_ERROR_SIZE_EXCEEDED,
    Verdict.ERROR_INVALID_INPUT: pb.VERDICT_ERROR_INVALID_INPUT,
}
_VERDICT_FROM_WIRE = {v: k for k, v in _VERDICT_TO_WIRE.items()}
_QUEUED_TRIGGER_KIND_TO_WIRE = {
    QueuedTriggerKind.SURGE: pb.QUEUED_TRIGGER_KIND_SURGE,
    QueuedTriggerKind.HIGH_STAGNATION: pb.QUEUED_TRIGGER_KIND_HIGH_STAGNATION,
    QueuedTriggerKind.PUNCTURE: pb.QUEUED_TRIGGER_KIND_PUNCTURE,
    QueuedTriggerKind.DANGER: pb.QUEUED_TRIGGER_KIND_DANGER,
}
_QUEUED_TRIGGER_KIND_FROM_WIRE = {v: k for k, v in _QUEUED_TRIGGER_KIND_TO_WIRE.items()}
_EVENT_KIND_TO_WIRE = {
    EventKind.DANGER_FLAG_UP: pb.EVENT_KIND_DANGER_FLAG_UP,
    EventKind.DANGER_FLAG_DOWN: pb.EVENT_KIND_DANGER_FLAG_DOWN,
    EventKind.DIRECTION_SWITCH: pb.EVENT_KIND_DIRECTION_SWITCH,
    EventKind.ADD_EDGE: pb.EVENT_KIND_ADD_EDGE,
    EventKind.ADD_NODE: pb.EVENT_KIND_ADD_NODE,
    EventKind.DISABLE: pb.EVENT_KIND_DISABLE,
    EventKind.ENABLE: pb.EVENT_KIND_ENABLE,
    EventKind.SCHEDULED_INFLOW: pb.EVENT_KIND_SCHEDULED_INFLOW,
    EventKind.SCHEDULED_ATTR_CHANGE: pb.EVENT_KIND_SCHEDULED_ATTR_CHANGE,
    EventKind.SENSOR_SET_CHANGED: pb.EVENT_KIND_SENSOR_SET_CHANGED,
}
_EVENT_KIND_FROM_WIRE = {v: k for k, v in _EVENT_KIND_TO_WIRE.items()}
_MODE_TO_WIRE = {Mode.OPEN: pb.MODE_OPEN, Mode.CLOSED: pb.MODE_CLOSED}
_MODE_FROM_WIRE = {v: k for k, v in _MODE_TO_WIRE.items()}
_RESTRICTION_REASON_TO_WIRE = {
    OptimizationRestrictionReason.UNDRAINABLE_STAGNATION: pb.RESTRICTION_REASON_UNDRAINABLE_STAGNATION,
    OptimizationRestrictionReason.RESIDUAL_TAU: pb.RESTRICTION_REASON_RESIDUAL_TAU,
    OptimizationRestrictionReason.PUNCTURE: pb.RESTRICTION_REASON_PUNCTURE,
    OptimizationRestrictionReason.NODE_DANGER_UPSTREAM: pb.RESTRICTION_REASON_NODE_DANGER_UPSTREAM,
    OptimizationRestrictionReason.OVERLOAD: pb.RESTRICTION_REASON_OVERLOAD,
}
_RESTRICTION_REASON_FROM_WIRE = {v: k for k, v in _RESTRICTION_REASON_TO_WIRE.items()}
_SOLVER_STATUS_TO_WIRE = {
    SolverStatus.OPTIMAL: pb.SOLVER_STATUS_OPTIMAL,
    SolverStatus.FEASIBLE: pb.SOLVER_STATUS_FEASIBLE,
    SolverStatus.INFEASIBLE: pb.SOLVER_STATUS_INFEASIBLE,
    SolverStatus.TIMEOUT: pb.SOLVER_STATUS_TIMEOUT,
    SolverStatus.LIGHTWEIGHT: pb.SOLVER_STATUS_LIGHTWEIGHT,
}
_SOLVER_STATUS_FROM_WIRE = {v: k for k, v in _SOLVER_STATUS_TO_WIRE.items()}
_IMPORTANCE_DIRECTION_TO_WIRE = {
    ImportanceDirection.A_TO_B: pb.IMPORTANCE_DIRECTION_A_TO_B,
    ImportanceDirection.B_TO_A: pb.IMPORTANCE_DIRECTION_B_TO_A,
    ImportanceDirection.NONE: pb.IMPORTANCE_DIRECTION_NONE,
}
_IMPORTANCE_DIRECTION_FROM_WIRE = {v: k for k, v in _IMPORTANCE_DIRECTION_TO_WIRE.items()}
_PROPOSED_DIRECTION_TO_WIRE = {
    ProposedDirection.A_TO_B: pb.PROPOSED_DIRECTION_A_TO_B,
    ProposedDirection.B_TO_A: pb.PROPOSED_DIRECTION_B_TO_A,
    ProposedDirection.BIDIRECTIONAL: pb.PROPOSED_DIRECTION_BIDIRECTIONAL,
}
_PROPOSED_DIRECTION_FROM_WIRE = {v: k for k, v in _PROPOSED_DIRECTION_TO_WIRE.items()}
_DIRECTION_CHANGE_TYPE_TO_WIRE = {
    DirectionChangeType.CONVERT_ONEWAY: pb.DIRECTION_CHANGE_TYPE_CONVERT_ONEWAY,
    DirectionChangeType.RELEASE_ONEWAY: pb.DIRECTION_CHANGE_TYPE_RELEASE_ONEWAY,
    DirectionChangeType.FLIP_ONEWAY: pb.DIRECTION_CHANGE_TYPE_FLIP_ONEWAY,
    DirectionChangeType.KEEP: pb.DIRECTION_CHANGE_TYPE_KEEP,
}
_DIRECTION_CHANGE_TYPE_FROM_WIRE = {v: k for k, v in _DIRECTION_CHANGE_TYPE_TO_WIRE.items()}
_RESTRICTION_ACTION_TO_WIRE = {
    RestrictionAction.CLOSE: pb.RESTRICTION_ACTION_CLOSE,
    RestrictionAction.LIMIT: pb.RESTRICTION_ACTION_LIMIT,
    RestrictionAction.RESUME: pb.RESTRICTION_ACTION_RESUME,
}
_RESTRICTION_ACTION_FROM_WIRE = {v: k for k, v in _RESTRICTION_ACTION_TO_WIRE.items()}
_BOUNDARY_ACTION_TO_WIRE = {
    BoundaryAction.PAUSE_INGRESS: pb.BOUNDARY_ACTION_PAUSE_INGRESS,
    BoundaryAction.PAUSE_EGRESS: pb.BOUNDARY_ACTION_PAUSE_EGRESS,
    BoundaryAction.RESUME: pb.BOUNDARY_ACTION_RESUME,
}
_BOUNDARY_ACTION_FROM_WIRE = {v: k for k, v in _BOUNDARY_ACTION_TO_WIRE.items()}
_WARNING_CODE_TO_WIRE = {
    WarningCode.RETRIGGER: pb.WARNING_CODE_RETRIGGER,
    WarningCode.SIZE_NEAR_LIMIT: pb.WARNING_CODE_SIZE_NEAR_LIMIT,
    WarningCode.CONSTRAINT_NEAR: pb.WARNING_CODE_CONSTRAINT_NEAR,
    WarningCode.LOW_COVERAGE: pb.WARNING_CODE_LOW_COVERAGE,
    WarningCode.FALLBACK_APPLIED: pb.WARNING_CODE_FALLBACK_APPLIED,
    WarningCode.QUEUE_EXPIRED: pb.WARNING_CODE_QUEUE_EXPIRED,
    WarningCode.SOLVER_GIVEUP: pb.WARNING_CODE_SOLVER_GIVEUP,
    WarningCode.UNDRAINABLE_EDGE: pb.WARNING_CODE_UNDRAINABLE_EDGE,
    WarningCode.MANY_TRIGGER_ZONES: pb.WARNING_CODE_MANY_TRIGGER_ZONES,
    WarningCode.LOW_CONFIDENCE_PROPOSAL: pb.WARNING_CODE_LOW_CONFIDENCE_PROPOSAL,
    WarningCode.INSUFFICIENT_WINDOW_SAMPLES: pb.WARNING_CODE_INSUFFICIENT_WINDOW_SAMPLES,
    WarningCode.SURGE_PROXY_FALLBACK: pb.WARNING_CODE_SURGE_PROXY_FALLBACK,
    WarningCode.DEGRADED_COMBINED_TRIGGER: pb.WARNING_CODE_DEGRADED_COMBINED_TRIGGER,
}
_WARNING_CODE_FROM_WIRE = {v: k for k, v in _WARNING_CODE_TO_WIRE.items()}
_TRIGGER_EVIDENCE_SOURCE_TO_WIRE = {
    TriggerEvidenceSource.SURGE: pb.TRIGGER_EVIDENCE_SOURCE_SURGE,
    TriggerEvidenceSource.HIGH_STAGNATION: pb.TRIGGER_EVIDENCE_SOURCE_HIGH_STAGNATION,
    TriggerEvidenceSource.PUNCTURE: pb.TRIGGER_EVIDENCE_SOURCE_PUNCTURE,
    TriggerEvidenceSource.DANGER: pb.TRIGGER_EVIDENCE_SOURCE_DANGER,
    TriggerEvidenceSource.QUEUE_SCORE: pb.TRIGGER_EVIDENCE_SOURCE_QUEUE_SCORE,
    TriggerEvidenceSource.QUEUE_DIVERSITY: pb.TRIGGER_EVIDENCE_SOURCE_QUEUE_DIVERSITY,
}
_TRIGGER_EVIDENCE_SOURCE_FROM_WIRE = {v: k for k, v in _TRIGGER_EVIDENCE_SOURCE_TO_WIRE.items()}
_FALLBACK_KIND_TO_WIRE = {
    FallbackKind.REFERENCE_USED: pb.FALLBACK_KIND_REFERENCE_USED,
    FallbackKind.DEFAULT_ETA_USED: pb.FALLBACK_KIND_DEFAULT_ETA_USED,
    FallbackKind.PERCENTILE_DEGRADED: pb.FALLBACK_KIND_PERCENTILE_DEGRADED,
    FallbackKind.DIRECTION_PROPOSAL_HELD: pb.FALLBACK_KIND_DIRECTION_PROPOSAL_HELD,
    FallbackKind.PHASE2_SKIPPED: pb.FALLBACK_KIND_PHASE2_SKIPPED,
    FallbackKind.BUDGET_EXTENDED: pb.FALLBACK_KIND_BUDGET_EXTENDED,
    FallbackKind.FORECAST_PRIOR_DEGRADED: pb.FALLBACK_KIND_FORECAST_PRIOR_DEGRADED,
    FallbackKind.FORECAST_ARC_IMPUTED: pb.FALLBACK_KIND_FORECAST_ARC_IMPUTED,
    FallbackKind.INFEASIBLE_LP_RELAXED: pb.FALLBACK_KIND_INFEASIBLE_LP_RELAXED,
    FallbackKind.DETOUR_TRUNCATED: pb.FALLBACK_KIND_DETOUR_TRUNCATED,
    FallbackKind.LP_INFEASIBLE_HELD: pb.FALLBACK_KIND_LP_INFEASIBLE_HELD,
    FallbackKind.GREEDY_NO_IMPROVEMENT: pb.FALLBACK_KIND_GREEDY_NO_IMPROVEMENT,
    FallbackKind.LOCALIZATION_CAPPED: pb.FALLBACK_KIND_LOCALIZATION_CAPPED,
    FallbackKind.RESTRICTION_PROPOSED: pb.FALLBACK_KIND_RESTRICTION_PROPOSED,
}
_FALLBACK_KIND_FROM_WIRE = {v: k for k, v in _FALLBACK_KIND_TO_WIRE.items()}
_STEP_KIND_TO_WIRE = {
    StepKind.VALIDATION: pb.STEP_KIND_VALIDATION,
    StepKind.MODE_DECISION: pb.STEP_KIND_MODE_DECISION,
    StepKind.EVENTS_APPLY: pb.STEP_KIND_EVENTS_APPLY,
    StepKind.DETECTION: pb.STEP_KIND_DETECTION,
    StepKind.FORECASTING: pb.STEP_KIND_FORECASTING,
    StepKind.DETOUR: pb.STEP_KIND_DETOUR,
    StepKind.OPTIMIZATION: pb.STEP_KIND_OPTIMIZATION,
    StepKind.FEEDBACK: pb.STEP_KIND_FEEDBACK,
}
_STEP_KIND_FROM_WIRE = {v: k for k, v in _STEP_KIND_TO_WIRE.items()}
_STEP_STATUS_TO_WIRE = {
    StepStatus.OK: pb.STEP_STATUS_OK,
    StepStatus.SKIPPED: pb.STEP_STATUS_SKIPPED,
    StepStatus.FAILED: pb.STEP_STATUS_FAILED,
}
_STEP_STATUS_FROM_WIRE = {v: k for k, v in _STEP_STATUS_TO_WIRE.items()}
_OD_RESOLUTION_MODE_TO_WIRE = {
    ODResolutionMode.TURNING_EXACT: pb.OD_RESOLUTION_MODE_TURNING_EXACT,
    ODResolutionMode.DOUBLY_CONSTRAINED: pb.OD_RESOLUTION_MODE_DOUBLY_CONSTRAINED,
    ODResolutionMode.DISTANCE_PRIOR: pb.OD_RESOLUTION_MODE_DISTANCE_PRIOR,
}
_OD_RESOLUTION_MODE_FROM_WIRE = {v: k for k, v in _OD_RESOLUTION_MODE_TO_WIRE.items()}
_OD_RESOLUTION_REASON_TO_WIRE = {
    ODResolutionReason.DETERMINED: pb.OD_RESOLUTION_REASON_DETERMINED,
    ODResolutionReason.MERGE_SPLIT_AMBIGUOUS: pb.OD_RESOLUTION_REASON_MERGE_SPLIT_AMBIGUOUS,
    ODResolutionReason.SPARSE_OBSERVATION: pb.OD_RESOLUTION_REASON_SPARSE_OBSERVATION,
    ODResolutionReason.NODE_ONLY: pb.OD_RESOLUTION_REASON_NODE_ONLY,
}
_OD_RESOLUTION_REASON_FROM_WIRE = {v: k for k, v in _OD_RESOLUTION_REASON_TO_WIRE.items()}

_FEEDBACK_RESTRICTION_REASON_TO_WIRE = {
    FeedbackRestrictionReason.UNDRAINABLE_STAGNATION: pb.RESTRICTION_REASON_UNDRAINABLE_STAGNATION,
    FeedbackRestrictionReason.RESIDUAL_TAU: pb.RESTRICTION_REASON_RESIDUAL_TAU,
    FeedbackRestrictionReason.PUNCTURE: pb.RESTRICTION_REASON_PUNCTURE,
    FeedbackRestrictionReason.NODE_DANGER_UPSTREAM: pb.RESTRICTION_REASON_NODE_DANGER_UPSTREAM,
}
_FEEDBACK_RESTRICTION_REASON_FROM_WIRE = {
    value: key for key, value in _FEEDBACK_RESTRICTION_REASON_TO_WIRE.items()
}


def _required_float(message: Message, field: str) -> float:
    value = _required(message, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {field}")
    return _finite(float(value), field)


def _optional_float(message: Message, field: str) -> float | None:
    if not message.HasField(field):
        return None
    value = cast(object, getattr(message, field))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {field}")
    return _finite(float(value), field)


def _required_int(message: Message, field: str) -> int:
    value = _required(message, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {field}")
    return int(value)


def _required_bool(message: Message, field: str) -> bool:
    value = _required(message, field)
    if not isinstance(value, bool):
        raise ValueError(f"invalid {field}")
    return value


def _required_enum[K, E: Enum](
    message: Message, field: str, mapping: Mapping[K, E], name: str
) -> E:
    value = _required(message, field)
    if not isinstance(value, int):
        raise ValueError(f"invalid {field}")
    return _enum_from_wire(int(value), mapping, name)


def _required_id(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"empty {name}")
    return value


def _encode_timed_value(target: pb.TimedValue, value: tuple[datetime, float]) -> None:
    at, number = value
    _copy_timestamp(target, "at", at, "timed_value.at")
    target.value = _finite(number, "timed_value.value")


def _decode_timed_value(value: pb.TimedValue) -> tuple[datetime, float]:
    return _decode_required_datetime(value, "at"), _finite(value.value, "timed_value.value")


def _encode_edge_float(value: tuple[EdgeID, float]) -> pb.EdgeFloat:
    edge_id, number = value
    return pb.EdgeFloat(
        edge_id=_required_id(edge_id.value, "edge_id"),
        value=_finite(number, "edge_float.value"),
    )


def _decode_edge_float(value: pb.EdgeFloat) -> tuple[EdgeID, float]:
    return EdgeID(_required_id(value.edge_id, "edge_float.edge_id")), _finite(
        value.value, "edge_float.value"
    )


def _encode_node(value: Node) -> pb.Node:
    result = pb.Node(
        node_id=_required_id(value.node_id.value, "node_id"),
        kind=_enum_to_wire(value.kind, _NODE_KIND_TO_WIRE, "node kind"),
        is_boundary=value.is_boundary,
        enabled=value.enabled,
        attribute_tags=value.attribute_tags,
        time_resolution_s=value.time_resolution_s,
        danger_flag=value.danger_flag,
    )
    if value.danger_capacity is not None:
        result.danger_capacity = _finite(value.danger_capacity, "node.danger_capacity")
    return result


def _decode_node(value: pb.Node) -> Node:
    danger_capacity = _optional_float(value, "danger_capacity")
    return Node(
        node_id=NodeID(_required_string(value, "node_id")),
        kind=_required_enum(value, "kind", _NODE_KIND_FROM_WIRE, "node kind"),
        is_boundary=_required_bool(value, "is_boundary"),
        enabled=_required_bool(value, "enabled"),
        attribute_tags=tuple(value.attribute_tags),
        time_resolution_s=_required_int(value, "time_resolution_s"),
        danger_flag=_required_bool(value, "danger_flag"),
        danger_capacity=danger_capacity,
    )


def _encode_edge(value: Edge) -> pb.Edge:
    result = pb.Edge(
        edge_id=_required_id(value.edge_id.value, "edge_id"),
        endpoint_a=_required_id(value.endpoint_a.value, "endpoint_a"),
        endpoint_b=_required_id(value.endpoint_b.value, "endpoint_b"),
        direction_constraint=_enum_to_wire(
            value.direction_constraint, _DIRECTION_CONSTRAINT_TO_WIRE, "direction constraint"
        ),
        current_direction=_enum_to_wire(
            value.current_direction, _CURRENT_DIRECTION_TO_WIRE, "current direction"
        ),
        enabled=value.enabled,
        observation_type=_enum_to_wire(
            value.observation_type, _OBSERVATION_TYPE_TO_WIRE, "observation type"
        ),
        attribute_tags=value.attribute_tags,
        time_resolution_s=value.time_resolution_s,
        danger_flag=value.danger_flag,
    )
    if value.danger_capacity is not None:
        result.danger_capacity = _finite(value.danger_capacity, "edge.danger_capacity")
    if value.capacity_hint is not None:
        result.capacity_hint = _finite(value.capacity_hint, "edge.capacity_hint")
    return result


def _decode_edge(value: pb.Edge) -> Edge:
    return Edge(
        edge_id=EdgeID(_required_string(value, "edge_id")),
        endpoint_a=NodeID(_required_string(value, "endpoint_a")),
        endpoint_b=NodeID(_required_string(value, "endpoint_b")),
        direction_constraint=_required_enum(
            value, "direction_constraint", _DIRECTION_CONSTRAINT_FROM_WIRE, "direction constraint"
        ),
        current_direction=_required_enum(
            value, "current_direction", _CURRENT_DIRECTION_FROM_WIRE, "current direction"
        ),
        enabled=_required_bool(value, "enabled"),
        observation_type=_required_enum(
            value, "observation_type", _OBSERVATION_TYPE_FROM_WIRE, "observation type"
        ),
        attribute_tags=tuple(value.attribute_tags),
        time_resolution_s=_required_int(value, "time_resolution_s"),
        danger_flag=_required_bool(value, "danger_flag"),
        danger_capacity=_optional_float(value, "danger_capacity"),
        capacity_hint=_optional_float(value, "capacity_hint"),
    )


def _encode_graph(value: Graph) -> pb.Graph:
    return pb.Graph(
        nodes=(_encode_node(node) for node in value.nodes),
        edges=(_encode_edge(edge) for edge in value.edges),
    )


def _decode_graph(value: pb.Graph) -> Graph:
    return Graph(
        nodes=tuple(_decode_node(node) for node in value.nodes),
        edges=tuple(_decode_edge(edge) for edge in value.edges),
    )


def _encode_arc_flow(value: ArcFlow) -> pb.ArcFlow:
    return pb.ArcFlow(
        edge_id=_required_id(value.edge_id.value, "arc_flow.edge_id"),
        direction=_enum_to_wire(value.direction, _FLOW_DIRECTION_TO_WIRE, "flow direction"),
        flow_rate=_finite(value.flow_rate, "arc_flow.flow_rate"),
        confidence_flag=_enum_to_wire(
            value.confidence_flag, _CONFIDENCE_FLAG_TO_WIRE, "confidence flag"
        ),
    )


def _decode_arc_flow(value: pb.ArcFlow) -> ArcFlow:
    return ArcFlow(
        edge_id=EdgeID(_required_string(value, "edge_id")),
        direction=_required_enum(value, "direction", _FLOW_DIRECTION_FROM_WIRE, "flow direction"),
        flow_rate=_required_float(value, "flow_rate"),
        confidence_flag=_required_enum(
            value, "confidence_flag", _CONFIDENCE_FLAG_FROM_WIRE, "confidence flag"
        ),
    )


def _encode_arc_stagnation(value: ArcStagnation) -> pb.ArcStagnation:
    return pb.ArcStagnation(
        edge_id=_required_id(value.edge_id.value, "arc_stagnation.edge_id"),
        stagnation=_finite(value.stagnation, "arc_stagnation.stagnation"),
        derivation=_enum_to_wire(
            value.derivation, _STAGNATION_DERIVATION_TO_WIRE, "stagnation derivation"
        ),
        same_sensor_flow=value.same_sensor_flow,
        confidence_flag=_enum_to_wire(
            value.confidence_flag, _CONFIDENCE_FLAG_TO_WIRE, "confidence flag"
        ),
    )


def _decode_arc_stagnation(value: pb.ArcStagnation) -> ArcStagnation:
    return ArcStagnation(
        edge_id=EdgeID(_required_string(value, "edge_id")),
        stagnation=_required_float(value, "stagnation"),
        derivation=_required_enum(
            value, "derivation", _STAGNATION_DERIVATION_FROM_WIRE, "stagnation derivation"
        ),
        same_sensor_flow=_required_bool(value, "same_sensor_flow"),
        confidence_flag=_required_enum(
            value, "confidence_flag", _CONFIDENCE_FLAG_FROM_WIRE, "confidence flag"
        ),
    )


def _encode_arc_scalar_flow(value: ArcScalarFlow) -> pb.ArcScalarFlow:
    return pb.ArcScalarFlow(
        edge_id=_required_id(value.edge_id.value, "arc_scalar_flow.edge_id"),
        observed_count=_finite(value.observed_count, "arc_scalar_flow.observed_count"),
        confidence_flag=_enum_to_wire(
            value.confidence_flag, _CONFIDENCE_FLAG_TO_WIRE, "confidence flag"
        ),
    )


def _decode_arc_scalar_flow(value: pb.ArcScalarFlow) -> ArcScalarFlow:
    return ArcScalarFlow(
        edge_id=EdgeID(_required_string(value, "edge_id")),
        observed_count=_required_float(value, "observed_count"),
        confidence_flag=_required_enum(
            value, "confidence_flag", _CONFIDENCE_FLAG_FROM_WIRE, "confidence flag"
        ),
    )


def _encode_node_occupancy(value: NodeOccupancy) -> pb.NodeOccupancy:
    return pb.NodeOccupancy(
        node_id=_required_id(value.node_id.value, "node_occupancy.node_id"),
        occupancy=_finite(value.occupancy, "node_occupancy.occupancy"),
        occupancy_delta=_finite(value.occupancy_delta, "node_occupancy.occupancy_delta"),
        same_sensor_arrival=value.same_sensor_arrival,
        confidence_flag=_enum_to_wire(
            value.confidence_flag, _CONFIDENCE_FLAG_TO_WIRE, "confidence flag"
        ),
    )


def _decode_node_occupancy(value: pb.NodeOccupancy) -> NodeOccupancy:
    return NodeOccupancy(
        node_id=NodeID(_required_string(value, "node_id")),
        occupancy=_required_float(value, "occupancy"),
        occupancy_delta=_required_float(value, "occupancy_delta"),
        same_sensor_arrival=_required_bool(value, "same_sensor_arrival"),
        confidence_flag=_required_enum(
            value, "confidence_flag", _CONFIDENCE_FLAG_FROM_WIRE, "confidence flag"
        ),
    )


def _encode_turning(value: TurningObservation) -> pb.TurningObservation:
    result = pb.TurningObservation(
        node_id=_required_id(value.node_id.value, "turning.node_id"),
        from_edge_id=_required_id(value.from_edge_id.value, "turning.from_edge_id"),
        ratio=_finite(value.ratio, "turning.ratio"),
        confidence_flag=_enum_to_wire(
            value.confidence_flag, _CONFIDENCE_FLAG_TO_WIRE, "confidence flag"
        ),
    )
    if value.to_edge_id is not None:
        result.to_edge_id = _required_id(value.to_edge_id.value, "turning.to_edge_id")
    return result


def _decode_turning(value: pb.TurningObservation) -> TurningObservation:
    to_edge = _optional_string(value, "to_edge_id")
    return TurningObservation(
        node_id=NodeID(_required_string(value, "node_id")),
        from_edge_id=EdgeID(_required_string(value, "from_edge_id")),
        to_edge_id=None if to_edge is None else EdgeID(to_edge),
        ratio=_required_float(value, "ratio"),
        confidence_flag=_required_enum(
            value, "confidence_flag", _CONFIDENCE_FLAG_FROM_WIRE, "confidence flag"
        ),
    )


def _encode_observations(value: Observations) -> pb.Observations:
    result = pb.Observations()
    _copy_timestamp(result, "observed_at", value.observed_at, "observations.observed_at")
    if value.snapshot_ref is not None:
        result.snapshot_ref = value.snapshot_ref
    result.arc_flows.extend(_encode_arc_flow(item) for item in value.arc_flows)
    result.arc_stagnations.extend(_encode_arc_stagnation(item) for item in value.arc_stagnations)
    result.arc_scalar_flows.extend(_encode_arc_scalar_flow(item) for item in value.arc_scalar_flows)
    result.node_occupancies.extend(_encode_node_occupancy(item) for item in value.node_occupancies)
    result.node_turning.extend(_encode_turning(item) for item in value.node_turning)
    return result


def _decode_observations(value: pb.Observations) -> Observations:
    return Observations(
        observed_at=_decode_required_datetime(value, "observed_at"),
        snapshot_ref=_optional_string(value, "snapshot_ref"),
        arc_flows=tuple(_decode_arc_flow(item) for item in value.arc_flows),
        arc_stagnations=tuple(_decode_arc_stagnation(item) for item in value.arc_stagnations),
        arc_scalar_flows=tuple(_decode_arc_scalar_flow(item) for item in value.arc_scalar_flows),
        node_occupancies=tuple(_decode_node_occupancy(item) for item in value.node_occupancies),
        node_turning=tuple(_decode_turning(item) for item in value.node_turning),
    )


def _encode_history_stat(value: ArcHistoryStat) -> pb.ArcHistoryStat:
    result = pb.ArcHistoryStat(edge_id=_required_id(value.edge_id.value, "history.edge_id"))
    for field, number in (
        ("p90_stagnation", value.p90_stagnation),
        ("baseline_stagnation", value.baseline_stagnation),
        ("flow_sensitivity_eta", value.flow_sensitivity_eta),
        ("available_span_hours", value.available_span_hours),
    ):
        if number is not None:
            setattr(result, field, _finite(number, f"history.{field}"))
    return result


def _decode_history_stat(value: pb.ArcHistoryStat) -> ArcHistoryStat:
    return ArcHistoryStat(
        edge_id=EdgeID(_required_id(value.edge_id, "history.edge_id")),
        p90_stagnation=_optional_float(value, "p90_stagnation"),
        baseline_stagnation=_optional_float(value, "baseline_stagnation"),
        flow_sensitivity_eta=_optional_float(value, "flow_sensitivity_eta"),
        available_span_hours=_optional_float(value, "available_span_hours"),
    )


def _encode_window_series(value: ArcWindowSeries) -> pb.ArcWindowSeries:
    result = pb.ArcWindowSeries(edge_id=_required_id(value.edge_id.value, "window.edge_id"))
    for sample in value.flow_samples:
        _encode_timed_value(result.flow_samples.add(), sample)
    for sample in value.stagnation_samples:
        _encode_timed_value(result.stagnation_samples.add(), sample)
    if value.directional_flow_samples is not None:
        directional = result.directional_flow_samples
        directional.SetInParent()
        for direction, samples in value.directional_flow_samples:
            series = directional.series.add()
            series.direction = _enum_to_wire(direction, _FLOW_DIRECTION_TO_WIRE, "flow direction")
            for sample in samples:
                _encode_timed_value(series.samples.add(), sample)
    return result


def _decode_window_series(value: pb.ArcWindowSeries) -> ArcWindowSeries:
    directional: tuple[tuple[FlowDirection, tuple[tuple[datetime, float], ...]], ...] | None
    if value.HasField("directional_flow_samples"):
        directional = tuple(
            (
                _enum_from_wire(int(series.direction), _FLOW_DIRECTION_FROM_WIRE, "flow direction"),
                tuple(_decode_timed_value(sample) for sample in series.samples),
            )
            for series in value.directional_flow_samples.series
        )
    else:
        directional = None
    return ArcWindowSeries(
        edge_id=EdgeID(_required_id(value.edge_id, "window.edge_id")),
        flow_samples=tuple(_decode_timed_value(sample) for sample in value.flow_samples),
        stagnation_samples=tuple(
            _decode_timed_value(sample) for sample in value.stagnation_samples
        ),
        directional_flow_samples=directional,
    )


def _encode_history(value: HistoryDigest) -> pb.HistoryDigest:
    result = pb.HistoryDigest(completeness=_finite(value.completeness, "history.completeness"))
    result.arc_stats.extend(_encode_history_stat(item) for item in value.arc_stats)
    result.window_series.extend(_encode_window_series(item) for item in value.window_series)
    return result


def _decode_history(value: pb.HistoryDigest) -> HistoryDigest:
    return HistoryDigest(
        arc_stats=tuple(_decode_history_stat(item) for item in value.arc_stats),
        window_series=tuple(_decode_window_series(item) for item in value.window_series),
        completeness=_finite(value.completeness, "history.completeness"),
    )


def _encode_queued_trigger(value: QueuedTrigger) -> pb.QueuedTrigger:
    result = pb.QueuedTrigger(
        kind=_enum_to_wire(value.kind, _QUEUED_TRIGGER_KIND_TO_WIRE, "queued trigger kind"),
        accumulated_score=_finite(value.accumulated_score, "queued_trigger.accumulated_score"),
    )
    _copy_timestamp(result, "first_fired_at", value.first_fired_at, "queued_trigger.first_fired_at")
    _copy_timestamp(result, "last_fired_at", value.last_fired_at, "queued_trigger.last_fired_at")
    if value.origin_edge_id is not None:
        result.origin_edge_id = _required_id(value.origin_edge_id.value, "origin_edge_id")
    if value.origin_node_id is not None:
        result.origin_node_id = _required_id(value.origin_node_id.value, "origin_node_id")
    if value.snapshot_ref is not None:
        result.snapshot_ref = value.snapshot_ref
    return result


def _decode_queued_trigger(value: pb.QueuedTrigger) -> QueuedTrigger:
    origin_edge = _optional_string(value, "origin_edge_id")
    origin_node = _optional_string(value, "origin_node_id")
    return QueuedTrigger(
        kind=_required_enum(value, "kind", _QUEUED_TRIGGER_KIND_FROM_WIRE, "queued trigger kind"),
        first_fired_at=_decode_required_datetime(value, "first_fired_at"),
        last_fired_at=_decode_required_datetime(value, "last_fired_at"),
        accumulated_score=_finite(value.accumulated_score, "queued_trigger.accumulated_score"),
        origin_edge_id=None if origin_edge is None else EdgeID(origin_edge),
        origin_node_id=None if origin_node is None else NodeID(origin_node),
        snapshot_ref=_optional_string(value, "snapshot_ref"),
    )


def _encode_arc_watch(value: ArcWatchState) -> pb.ArcWatchState:
    result = pb.ArcWatchState(
        edge_id=_required_id(value.edge_id.value, "arc_watch.edge_id"),
        percentile_breached=value.percentile_breached,
        delta_breached=value.delta_breached,
        surge_breached=value.surge_breached,
        demand_excess_breached=value.demand_excess_breached,
    )
    if value.stagnation_watch_since is not None:
        _copy_timestamp(
            result, "stagnation_watch_since", value.stagnation_watch_since, "stagnation_watch_since"
        )
    if value.demand_watch_since is not None:
        _copy_timestamp(
            result, "demand_watch_since", value.demand_watch_since, "demand_watch_since"
        )
    return result


def _decode_arc_watch(value: pb.ArcWatchState) -> ArcWatchState:
    return ArcWatchState(
        edge_id=EdgeID(_required_id(value.edge_id, "arc_watch.edge_id")),
        percentile_breached=value.percentile_breached,
        delta_breached=value.delta_breached,
        stagnation_watch_since=_decode_optional_datetime(value, "stagnation_watch_since"),
        surge_breached=value.surge_breached,
        demand_excess_breached=value.demand_excess_breached,
        demand_watch_since=_decode_optional_datetime(value, "demand_watch_since"),
    )


def _encode_detection_state(value: DetectionState) -> pb.DetectionState:
    result = pb.DetectionState(consecutive_skip_count=value.consecutive_skip_count)
    if value.cooldown_until is not None:
        _copy_timestamp(result, "cooldown_until", value.cooldown_until, "cooldown_until")
    result.trigger_queue.extend(_encode_queued_trigger(item) for item in value.trigger_queue)
    result.arc_watch_states.extend(_encode_arc_watch(item) for item in value.arc_watch_states)
    if value.arc_demand_digest is not None:
        digest = result.arc_demand_digest
        digest.SetInParent()
        digest.entries.extend(
            pb.ArcDemandDigestEntry(
                edge_id=_required_id(item.edge_id.value, "demand_digest.edge_id"),
                demand=_finite(item.demand, "demand_digest.demand"),
            )
            for item in value.arc_demand_digest
        )
    result.warmup_states.extend(
        pb.WarmupState(
            target_key=item.target_key,
            until=_datetime(item.until, "warmup.until"),
        )
        for item in value.warmup_states
    )
    for item in value.arc_retrigger_counts:
        encoded = result.arc_retrigger_counts.add()
        encoded.edge_id = _required_id(item.edge_id.value, "retrigger.edge_id")
        encoded.count = item.count
        encoded.quiet_cycles = item.quiet_cycles
        if item.last_fired_at is not None:
            _copy_timestamp(encoded, "last_fired_at", item.last_fired_at, "retrigger.last_fired_at")
    return result


def _decode_detection_state(value: pb.DetectionState) -> DetectionState:
    digest: tuple[ArcDemandDigestEntry, ...] | None
    if value.HasField("arc_demand_digest"):
        digest = tuple(
            ArcDemandDigestEntry(
                edge_id=EdgeID(_required_id(item.edge_id, "demand_digest.edge_id")),
                demand=_finite(item.demand, "demand_digest.demand"),
            )
            for item in value.arc_demand_digest.entries
        )
    else:
        digest = None
    return DetectionState(
        cooldown_until=_decode_optional_datetime(value, "cooldown_until"),
        trigger_queue=tuple(_decode_queued_trigger(item) for item in value.trigger_queue),
        arc_watch_states=tuple(_decode_arc_watch(item) for item in value.arc_watch_states),
        arc_demand_digest=digest,
        warmup_states=tuple(
            WarmupState(
                target_key=item.target_key,
                until=_decode_required_datetime(item, "until"),
            )
            for item in value.warmup_states
        ),
        arc_retrigger_counts=tuple(
            RetriggerEntry(
                edge_id=EdgeID(_required_id(item.edge_id, "retrigger.edge_id")),
                count=item.count,
                quiet_cycles=item.quiet_cycles,
                last_fired_at=_decode_optional_datetime(item, "last_fired_at"),
            )
            for item in value.arc_retrigger_counts
        ),
        consecutive_skip_count=value.consecutive_skip_count,
    )


def _encode_scalar(value: object) -> pb.ScalarValue:
    result = pb.ScalarValue()
    if value is None:
        result.null_value.CopyFrom(empty_pb2.Empty())
    elif isinstance(value, bool):
        result.bool_value = value
    elif isinstance(value, str):
        result.string_value = value
    elif isinstance(value, int):
        result.int_value = value
    elif isinstance(value, float):
        result.double_value = _finite(value, "scalar.double_value")
    else:
        raise ValueError(f"unsupported scalar value: {type(value).__name__}")
    return result


def _decode_scalar(value: pb.ScalarValue) -> object:
    kind = cast(str | None, value.WhichOneof("kind"))
    if kind is None:
        raise ValueError("missing scalar value")
    if kind == "null_value":
        return None
    if kind == "double_value":
        return _finite(value.double_value, "scalar.double_value")
    return cast(object, getattr(value, kind))


def _encode_key_values(values: tuple[tuple[str, object], ...]) -> list[pb.KeyValue]:
    result: list[pb.KeyValue] = []
    for key, value in values:
        item = pb.KeyValue(key=_required_id(key, "key"))
        item.value.CopyFrom(_encode_scalar(value))
        result.append(item)
    return result


def _decode_key_values(values: Iterable[pb.KeyValue]) -> tuple[tuple[str, object], ...]:
    result: list[tuple[str, object]] = []
    for item in values:
        if not item.key:
            raise ValueError("empty key")
        if not item.HasField("value"):
            raise ValueError("missing key value")
        result.append((item.key, _decode_scalar(item.value)))
    return tuple(result)


def _encode_event(value: Event) -> pb.Event:
    result = pb.Event(
        kind=_enum_to_wire(value.kind, _EVENT_KIND_TO_WIRE, "event kind"),
        target_id=_required_id(value.target_id, "event.target_id"),
    )
    _copy_timestamp(result, "occurred_at", value.occurred_at, "event.occurred_at")
    if value.params is not None:
        result.params.SetInParent()
        result.params.values.extend(_encode_key_values(value.params))
    return result


def _decode_event(value: pb.Event) -> Event:
    params = _decode_key_values(value.params.values) if value.HasField("params") else None
    return Event(
        kind=_required_enum(value, "kind", _EVENT_KIND_FROM_WIRE, "event kind"),
        target_id=_required_id(value.target_id, "event.target_id"),
        occurred_at=_decode_required_datetime(value, "occurred_at"),
        params=params,
    )


def _encode_tag_reference(value: TagReference) -> pb.TagReference:
    result = pb.TagReference(
        attribute_tag=value.attribute_tag,
        sample_count=value.sample_count,
    )
    for field, number in (
        ("eta_typical", value.eta_typical),
        ("baseline_stagnation", value.baseline_stagnation),
        ("capacity_typical", value.capacity_typical),
    ):
        if number is not None:
            setattr(result, field, _finite(number, f"tag_reference.{field}"))
    return result


def _decode_tag_reference(value: pb.TagReference) -> TagReference:
    return TagReference(
        attribute_tag=value.attribute_tag,
        eta_typical=_optional_float(value, "eta_typical"),
        baseline_stagnation=_optional_float(value, "baseline_stagnation"),
        capacity_typical=_optional_float(value, "capacity_typical"),
        sample_count=value.sample_count,
    )


def _encode_threshold_set(value: ThresholdSet) -> pb.ThresholdSet:
    result = pb.ThresholdSet()
    for field, number in (
        ("surge_rate_threshold_percent_per_min", value.surge_rate_threshold_percent_per_min),
        ("high_stagnation_duration_min", value.high_stagnation_duration_min),
        ("beta", value.beta),
        ("theta_demand", value.theta_demand),
        ("warmup_duration_min", value.warmup_duration_min),
    ):
        if number is not None:
            setattr(result, field, _finite(number, f"threshold_set.{field}"))
    return result


def _decode_threshold_set(value: pb.ThresholdSet) -> ThresholdSet:
    return ThresholdSet(
        surge_rate_threshold_percent_per_min=_optional_float(
            value, "surge_rate_threshold_percent_per_min"
        ),
        high_stagnation_duration_min=_optional_float(value, "high_stagnation_duration_min"),
        beta=_optional_float(value, "beta"),
        theta_demand=_optional_float(value, "theta_demand"),
        warmup_duration_min=_optional_float(value, "warmup_duration_min"),
    )


def _encode_references(value: Reference) -> pb.Reference:
    result = pb.Reference(source_k_anonymity=value.source_k_anonymity)
    result.by_attribute_tag.extend(_encode_tag_reference(item) for item in value.by_attribute_tag)
    if value.default_thresholds is not None:
        result.default_thresholds.CopyFrom(
            pb.ThresholdDefaults(
                short_term=_encode_threshold_set(value.default_thresholds.short_term),
                long_term=_encode_threshold_set(value.default_thresholds.long_term),
            )
        )
    return result


def _decode_references(value: pb.Reference) -> Reference:
    defaults = None
    if value.HasField("default_thresholds"):
        defaults = ThresholdDefaults(
            short_term=_decode_threshold_set(value.default_thresholds.short_term),
            long_term=_decode_threshold_set(value.default_thresholds.long_term),
        )
    return Reference(
        by_attribute_tag=tuple(_decode_tag_reference(item) for item in value.by_attribute_tag),
        default_thresholds=defaults,
        source_k_anonymity=value.source_k_anonymity,
    )


def _encode_tenant_context(value: TenantContext) -> pb.TenantContext:
    return pb.TenantContext(
        tenant_id=_required_id(value.tenant_id, "tenant_id"),
        tenant_category=_enum_to_wire(
            value.tenant_category, _TENANT_CATEGORY_TO_WIRE, "tenant category"
        ),
        available_history_hours=_finite(value.available_history_hours, "available_history_hours"),
    )


def _decode_tenant_context(value: pb.TenantContext) -> TenantContext:
    return TenantContext(
        tenant_id=_required_string(value, "tenant_id"),
        tenant_category=_required_enum(
            value, "tenant_category", _TENANT_CATEGORY_FROM_WIRE, "tenant category"
        ),
        available_history_hours=_required_float(value, "available_history_hours"),
    )


def _set_optional(target: Message, field: str, value: object) -> None:
    if value is not None:
        setattr(target, field, value)


def _encode_config(value: ResolvedConfig) -> pb.ResolvedConfig:
    result = pb.ResolvedConfig()
    for field, raw_value in (
        ("surge_rate_threshold_percent_per_min", value.surge_rate_threshold_percent_per_min),
        ("high_stagnation_duration_min", value.high_stagnation_duration_min),
        ("beta", value.beta),
        ("theta_demand", value.theta_demand),
        ("min_window_samples", value.min_window_samples),
        ("cooldown_duration_min", value.cooldown_duration_min),
        ("warmup_duration_min", value.warmup_duration_min),
        ("retrigger_warning_threshold", value.retrigger_warning_threshold),
        ("retrigger_reset_quiet_cycles", value.retrigger_reset_quiet_cycles),
        ("queue_score_threshold", value.queue_score_threshold),
        ("queue_diversity_threshold", value.queue_diversity_threshold),
        ("queue_freshness_min", value.queue_freshness_min),
        (
            "optimization_mode",
            _enum_to_wire(value.optimization_mode, _OPTIMIZATION_MODE_TO_WIRE, "optimization mode"),
        ),
        ("local_radius_hops", value.local_radius_hops),
        ("max_trigger_zones", value.max_trigger_zones),
        ("greedy_improve_margin", value.greedy_improve_margin),
        ("restriction_proposal_enabled", value.restriction_proposal_enabled),
        ("tau_danger_threshold", value.tau_danger_threshold),
        ("puncture_trigger_enabled", value.puncture_trigger_enabled),
        ("puncture_ratio_threshold", value.puncture_ratio_threshold),
        ("forecasting_budget_sec", value.forecasting_budget_sec),
        ("detour_budget_sec", value.detour_budget_sec),
        ("lightweight_opt_budget_sec", value.lightweight_opt_budget_sec),
        ("milp_time_limit_sec", value.milp_time_limit_sec),
        ("max_consecutive_skips", value.max_consecutive_skips),
        ("solver_seed", value.solver_seed),
        ("epsilon", value.epsilon),
        ("epsilon_0", value.epsilon_0),
        ("big_m_factor", value.big_m_factor),
        ("delta_min", value.delta_min),
        ("confidence_weight_floor", value.confidence_weight_floor),
        ("mip_rel_gap", value.mip_rel_gap),
        ("gravity_alpha", value.gravity_alpha),
        ("ipf_max_iter", value.ipf_max_iter),
        ("ipf_tolerance", value.ipf_tolerance),
        ("transit_time_prior_sec", value.transit_time_prior_sec),
        ("dwell_time_prior_sec", value.dwell_time_prior_sec),
        ("min_reference_sample_count", value.min_reference_sample_count),
        ("k_shortest_paths", value.k_shortest_paths),
        ("fallback_eta", value.fallback_eta),
        ("fallback_baseline_stagnation", value.fallback_baseline_stagnation),
        ("scalar_direction_enabled", value.scalar_direction_enabled),
        ("k_shortest_paths_auto", value.k_shortest_paths_auto),
        ("k_shortest_paths_max", value.k_shortest_paths_max),
        ("phase_feedback_enabled", value.phase_feedback_enabled),
        ("phase_feedback_candidates", value.phase_feedback_candidates),
        ("full_weight_hours", value.full_weight_hours),
        ("eta_mixing_ratio", value.eta_mixing_ratio),
        ("two_stage_optimization", value.two_stage_optimization),
        ("backoff_enabled", value.backoff_enabled),
        ("improvement_threshold", value.improvement_threshold),
        ("backoff_max_factor", value.backoff_max_factor),
        ("delta_objective_enabled", value.delta_objective_enabled),
        ("node_detour_enabled", value.node_detour_enabled),
        ("milp_boundary_control_enabled", value.milp_boundary_control_enabled),
        ("scheduled_inflow_prior_enabled", value.scheduled_inflow_prior_enabled),
        ("log_tenant_id", value.log_tenant_id),
    ):
        field_value = (
            _finite(raw_value, f"config.{field}") if isinstance(raw_value, float) else raw_value
        )
        _set_optional(result, field, field_value)
    result.throughput_target_edges.extend(
        _required_id(edge.value, "throughput_target_edges")
        for edge in value.throughput_target_edges
    )
    result.attribute_tag_priority.extend(value.attribute_tag_priority)
    result.shadow_extensions.extend(value.shadow_extensions)
    result.throughput_weights.CopyFrom(
        pb.ThroughputWeights(
            trigger_origin=_finite(value.throughput_weights.trigger_origin, "trigger_origin"),
            detour_path=_finite(value.throughput_weights.detour_path, "detour_path"),
            operator_set=_finite(value.throughput_weights.operator_set, "operator_set"),
        )
    )
    result.throughput_max_per_edge.extend(
        _encode_edge_float(item) for item in value.throughput_max_per_edge
    )
    return result


def _decode_config(value: pb.ResolvedConfig) -> ResolvedConfig:
    if not value.HasField("throughput_weights"):
        raise ValueError("missing throughput_weights")
    throughput_weights = ThroughputWeights(
        trigger_origin=_finite(value.throughput_weights.trigger_origin, "trigger_origin"),
        detour_path=_finite(value.throughput_weights.detour_path, "detour_path"),
        operator_set=_finite(value.throughput_weights.operator_set, "operator_set"),
    )
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=_required_float(
            value, "surge_rate_threshold_percent_per_min"
        ),
        high_stagnation_duration_min=_required_float(value, "high_stagnation_duration_min"),
        beta=_required_float(value, "beta"),
        theta_demand=_optional_float(value, "theta_demand"),
        min_window_samples=_required_int(value, "min_window_samples"),
        cooldown_duration_min=_required_float(value, "cooldown_duration_min"),
        warmup_duration_min=_required_float(value, "warmup_duration_min"),
        retrigger_warning_threshold=_required_int(value, "retrigger_warning_threshold"),
        retrigger_reset_quiet_cycles=_required_int(value, "retrigger_reset_quiet_cycles"),
        queue_score_threshold=_required_float(value, "queue_score_threshold"),
        queue_diversity_threshold=_required_int(value, "queue_diversity_threshold"),
        queue_freshness_min=_optional_float(value, "queue_freshness_min"),
        throughput_target_edges=tuple(EdgeID(edge) for edge in value.throughput_target_edges),
        optimization_mode=_required_enum(
            value, "optimization_mode", _OPTIMIZATION_MODE_FROM_WIRE, "optimization mode"
        ),
        local_radius_hops=_required_int(value, "local_radius_hops"),
        max_trigger_zones=_required_int(value, "max_trigger_zones"),
        greedy_improve_margin=_required_float(value, "greedy_improve_margin"),
        restriction_proposal_enabled=_required_bool(value, "restriction_proposal_enabled"),
        tau_danger_threshold=_optional_float(value, "tau_danger_threshold"),
        puncture_trigger_enabled=_required_bool(value, "puncture_trigger_enabled"),
        puncture_ratio_threshold=_required_float(value, "puncture_ratio_threshold"),
        forecasting_budget_sec=_required_float(value, "forecasting_budget_sec"),
        detour_budget_sec=_required_float(value, "detour_budget_sec"),
        lightweight_opt_budget_sec=_required_float(value, "lightweight_opt_budget_sec"),
        milp_time_limit_sec=_required_float(value, "milp_time_limit_sec"),
        max_consecutive_skips=_required_int(value, "max_consecutive_skips"),
        solver_seed=_required_int(value, "solver_seed"),
        epsilon=_required_float(value, "epsilon"),
        epsilon_0=_required_float(value, "epsilon_0"),
        big_m_factor=_required_float(value, "big_m_factor"),
        delta_min=_required_float(value, "delta_min"),
        confidence_weight_floor=_required_float(value, "confidence_weight_floor"),
        mip_rel_gap=_required_float(value, "mip_rel_gap"),
        gravity_alpha=_required_float(value, "gravity_alpha"),
        ipf_max_iter=_required_int(value, "ipf_max_iter"),
        ipf_tolerance=_required_float(value, "ipf_tolerance"),
        transit_time_prior_sec=_optional_float(value, "transit_time_prior_sec"),
        dwell_time_prior_sec=_optional_float(value, "dwell_time_prior_sec"),
        min_reference_sample_count=_required_int(value, "min_reference_sample_count"),
        k_shortest_paths=_required_int(value, "k_shortest_paths"),
        fallback_eta=_required_float(value, "fallback_eta"),
        fallback_baseline_stagnation=_required_float(value, "fallback_baseline_stagnation"),
        scalar_direction_enabled=_required_bool(value, "scalar_direction_enabled"),
        k_shortest_paths_auto=_required_bool(value, "k_shortest_paths_auto"),
        k_shortest_paths_max=_required_int(value, "k_shortest_paths_max"),
        phase_feedback_enabled=_required_bool(value, "phase_feedback_enabled"),
        phase_feedback_candidates=_required_int(value, "phase_feedback_candidates"),
        attribute_tag_priority=tuple(value.attribute_tag_priority),
        full_weight_hours=_required_float(value, "full_weight_hours"),
        eta_mixing_ratio=_required_float(value, "eta_mixing_ratio"),
        throughput_weights=throughput_weights,
        throughput_max_per_edge=tuple(
            _decode_edge_float(item) for item in value.throughput_max_per_edge
        ),
        two_stage_optimization=_required_bool(value, "two_stage_optimization"),
        backoff_enabled=_required_bool(value, "backoff_enabled"),
        improvement_threshold=_required_float(value, "improvement_threshold"),
        backoff_max_factor=_required_int(value, "backoff_max_factor"),
        shadow_extensions=tuple(value.shadow_extensions),
        delta_objective_enabled=_required_bool(value, "delta_objective_enabled"),
        node_detour_enabled=_required_bool(value, "node_detour_enabled"),
        milp_boundary_control_enabled=_required_bool(value, "milp_boundary_control_enabled"),
        scheduled_inflow_prior_enabled=_required_bool(value, "scheduled_inflow_prior_enabled"),
        log_tenant_id=_required_bool(value, "log_tenant_id"),
    )


def _encode_optimization_result(value: OptimizationResult) -> pb.OptimizationResult:
    result = pb.OptimizationResult(
        solver_status=_enum_to_wire(value.solver_status, _SOLVER_STATUS_TO_WIRE, "solver status"),
        seed=value.seed,
    )
    for item in value.route_importance:
        result.route_importance.append(
            pb.RouteImportance(
                edge_id=_required_id(item.edge_id.value, "route_importance.edge_id"),
                direction=_enum_to_wire(
                    item.direction, _IMPORTANCE_DIRECTION_TO_WIRE, "importance direction"
                ),
                importance=_finite(item.importance, "route_importance.importance"),
                valid_until_next_trigger=item.valid_until_next_trigger,
            )
        )
    for item in value.direction_proposal:
        result.direction_proposal.append(
            pb.DirectionProposal(
                edge_id=_required_id(item.edge_id.value, "direction_proposal.edge_id"),
                proposed_direction=_enum_to_wire(
                    item.proposed_direction, _PROPOSED_DIRECTION_TO_WIRE, "proposed direction"
                ),
                confidence=_finite(item.confidence, "direction_proposal.confidence"),
                change_type=_enum_to_wire(
                    item.change_type, _DIRECTION_CHANGE_TYPE_TO_WIRE, "direction change type"
                ),
            )
        )
    for item in value.restriction_proposal:
        encoded = pb.RestrictionProposal(
            edge_id=_required_id(item.edge_id.value, "restriction_proposal.edge_id"),
            action=_enum_to_wire(item.action, _RESTRICTION_ACTION_TO_WIRE, "restriction action"),
            reason=_enum_to_wire(item.reason, _RESTRICTION_REASON_TO_WIRE, "restriction reason"),
            confidence=_finite(item.confidence, "restriction_proposal.confidence"),
            scope_note=item.scope_note,
        )
        if item.limit_value is not None:
            encoded.limit_value = _finite(item.limit_value, "restriction_proposal.limit_value")
        result.restriction_proposal.append(encoded)
    for item in value.detour_paths:
        result.detour_paths.append(
            pb.DetourPathProposal(
                origin_edge_id=_required_id(item.origin_edge_id.value, "detour.origin_edge_id"),
                edge_ids=tuple(
                    _required_id(edge.value, "detour.edge_id") for edge in item.edge_ids
                ),
                confidence=_finite(item.confidence, "detour.confidence"),
            )
        )
    for item in value.boundary_control:
        result.boundary_control.append(
            pb.BoundaryControl(
                node_id=_required_id(item.node_id.value, "boundary_control.node_id"),
                action=_enum_to_wire(item.action, _BOUNDARY_ACTION_TO_WIRE, "boundary action"),
                reason=item.reason,
            )
        )
    result.objective_values.CopyFrom(
        pb.OptimizationObjectiveValues(
            tau_star=_finite(value.objective_values.tau_star, "objective_values.tau_star")
        )
    )
    if value.objective_values.throughput is not None:
        result.objective_values.throughput = _finite(
            value.objective_values.throughput, "objective_values.throughput"
        )
    if value.solved_at is not None:
        _copy_timestamp(result, "solved_at", value.solved_at, "optimization.solved_at")
    return result


def _decode_optimization_result(value: pb.OptimizationResult) -> OptimizationResult:
    if not value.HasField("objective_values"):
        raise ValueError("missing objective_values")
    return OptimizationResult(
        route_importance=tuple(
            RouteImportance(
                edge_id=EdgeID(_required_id(item.edge_id, "route_importance.edge_id")),
                direction=_enum_from_wire(
                    int(item.direction), _IMPORTANCE_DIRECTION_FROM_WIRE, "importance direction"
                ),
                importance=_finite(item.importance, "route_importance.importance"),
                valid_until_next_trigger=item.valid_until_next_trigger,
            )
            for item in value.route_importance
        ),
        direction_proposal=tuple(
            DirectionProposal(
                edge_id=EdgeID(_required_id(item.edge_id, "direction_proposal.edge_id")),
                proposed_direction=_enum_from_wire(
                    int(item.proposed_direction),
                    _PROPOSED_DIRECTION_FROM_WIRE,
                    "proposed direction",
                ),
                confidence=_finite(item.confidence, "direction_proposal.confidence"),
                change_type=_enum_from_wire(
                    int(item.change_type), _DIRECTION_CHANGE_TYPE_FROM_WIRE, "direction change type"
                ),
            )
            for item in value.direction_proposal
        ),
        restriction_proposal=tuple(
            RestrictionProposal(
                edge_id=EdgeID(_required_id(item.edge_id, "restriction_proposal.edge_id")),
                action=_enum_from_wire(
                    int(item.action), _RESTRICTION_ACTION_FROM_WIRE, "restriction action"
                ),
                limit_value=_optional_float(item, "limit_value"),
                reason=_enum_from_wire(
                    int(item.reason), _RESTRICTION_REASON_FROM_WIRE, "restriction reason"
                ),
                confidence=_finite(item.confidence, "restriction_proposal.confidence"),
                scope_note=item.scope_note,
            )
            for item in value.restriction_proposal
        ),
        detour_paths=tuple(
            DetourPathProposal(
                origin_edge_id=EdgeID(_required_id(item.origin_edge_id, "detour.origin_edge_id")),
                edge_ids=tuple(
                    EdgeID(_required_id(edge, "detour.edge_id")) for edge in item.edge_ids
                ),
                confidence=_finite(item.confidence, "detour.confidence"),
            )
            for item in value.detour_paths
        ),
        boundary_control=tuple(
            BoundaryControl(
                node_id=NodeID(_required_id(item.node_id, "boundary_control.node_id")),
                action=_enum_from_wire(
                    int(item.action), _BOUNDARY_ACTION_FROM_WIRE, "boundary action"
                ),
                reason=item.reason,
            )
            for item in value.boundary_control
        ),
        objective_values=OptimizationObjectiveValues(
            tau_star=_finite(value.objective_values.tau_star, "objective_values.tau_star"),
            throughput=_optional_float(value.objective_values, "throughput"),
        ),
        solver_status=_enum_from_wire(
            int(value.solver_status), _SOLVER_STATUS_FROM_WIRE, "solver status"
        ),
        solved_at=_decode_optional_datetime(value, "solved_at"),
        seed=value.seed,
    )


def _encode_feedback_objective(value: FeedbackObjectiveValues) -> pb.FeedbackObjectiveValues:
    result = pb.FeedbackObjectiveValues(tau_star=_finite(value.tau_star, "feedback.tau_star"))
    if value.throughput is not None:
        result.throughput = _finite(value.throughput, "feedback.throughput")
    return result


def _decode_feedback_objective(value: pb.FeedbackObjectiveValues) -> FeedbackObjectiveValues:
    return FeedbackObjectiveValues(
        tau_star=_finite(value.tau_star, "feedback.tau_star"),
        throughput=_optional_float(value, "throughput"),
    )


def _encode_warning(value: Warning) -> pb.Warning:
    result = pb.Warning(
        code=_enum_to_wire(value.code, _WARNING_CODE_TO_WIRE, "warning code"),
    )
    result.context.extend(_encode_key_values(value.context))
    return result


def _decode_warning(value: pb.Warning) -> Warning:
    return Warning(
        code=_enum_from_wire(int(value.code), _WARNING_CODE_FROM_WIRE, "warning code"),
        context=_decode_key_values(value.context),
    )


def _encode_compute_meta(value: ComputeMeta) -> pb.ComputeMeta:
    return pb.ComputeMeta(
        mode=_enum_to_wire(value.mode, _MODE_TO_WIRE, "mode"),
        optimization_mode=_enum_to_wire(
            value.optimization_mode, _OPTIMIZATION_MODE_TO_WIRE, "optimization mode"
        ),
        solver_phase1_ms=value.solver_phase1_ms,
        solver_phase2_ms=value.solver_phase2_ms,
        solver_phase1_status=value.solver_phase1_status,
        solver_phase2_status=value.solver_phase2_status,
        reachability_constraints=pb.ReachabilityConstraints(
            local=value.reachability_constraints.local,
            boundary=value.reachability_constraints.boundary,
        ),
    )


def _decode_compute_meta(value: pb.ComputeMeta) -> ComputeMeta:
    if not value.HasField("reachability_constraints"):
        raise ValueError("missing reachability_constraints")
    return ComputeMeta(
        mode=_enum_from_wire(int(value.mode), _MODE_FROM_WIRE, "mode"),
        optimization_mode=_enum_from_wire(
            int(value.optimization_mode), _OPTIMIZATION_MODE_FROM_WIRE, "optimization mode"
        ),
        solver_phase1_ms=value.solver_phase1_ms,
        solver_phase2_ms=value.solver_phase2_ms,
        solver_phase1_status=value.solver_phase1_status,
        solver_phase2_status=value.solver_phase2_status,
        reachability_constraints=ReachabilityConstraints(
            local=value.reachability_constraints.local,
            boundary=value.reachability_constraints.boundary,
        ),
    )


def _encode_feedback(value: FeedbackValues) -> pb.FeedbackValues:
    result = pb.FeedbackValues(schema_version=value.schema_version)
    result.compute_meta.CopyFrom(_encode_compute_meta(value.compute_meta))
    result.objective_values.CopyFrom(_encode_feedback_objective(value.objective_values))
    result.per_tag_observations.extend(
        pb.TagObservation(
            attribute_tag=item.attribute_tag,
            eta_estimate=_finite(item.eta_estimate, "tag_observation.eta_estimate"),
            edge_count=item.edge_count,
            observation_span_min=_finite(
                item.observation_span_min, "tag_observation.observation_span_min"
            ),
        )
        for item in value.per_tag_observations
    )
    if value.prediction_actual_diff is not None:
        item = value.prediction_actual_diff
        result.prediction_actual_diff.CopyFrom(
            pb.PredictionActualDiff(
                expected_tau_star=_finite(item.expected_tau_star, "prediction.expected_tau_star"),
                actual_tau_star=_finite(item.actual_tau_star, "prediction.actual_tau_star"),
                delta=_finite(item.delta, "prediction.delta"),
            )
        )
    result.reference_usage.CopyFrom(
        pb.ReferenceUsageReport(
            used_tags=value.reference_usage.used_tags,
            used_default=value.reference_usage.used_default,
            used_edges_count=value.reference_usage.used_edges_count,
        )
    )
    result.quality_metrics.CopyFrom(
        pb.QualityMetrics(
            vector_coverage_ratio=_finite(
                value.quality_metrics.vector_coverage_ratio, "quality.vector_coverage_ratio"
            ),
            low_confidence_arc_ratio=_finite(
                value.quality_metrics.low_confidence_arc_ratio, "quality.low_confidence_arc_ratio"
            ),
            history_completeness=_finite(
                value.quality_metrics.history_completeness, "quality.history_completeness"
            ),
        )
    )
    if value.detour_metrics is not None:
        item = value.detour_metrics
        result.detour_metrics.CopyFrom(
            pb.DetourMetrics(
                k_requested=item.k_requested,
                k_effective=item.k_effective,
                paths_actually_used_ratio=_finite(
                    item.paths_actually_used_ratio, "detour_metrics.paths_actually_used_ratio"
                ),
            )
        )
    if value.restriction_metrics is not None:
        item = value.restriction_metrics
        encoded = pb.RestrictionMetrics(
            proposed_count=item.proposed_count,
            estimated_inflow_cut=_finite(
                item.estimated_inflow_cut, "restriction_metrics.estimated_inflow_cut"
            ),
            undrainable_origin_ratio=_finite(
                item.undrainable_origin_ratio, "restriction_metrics.undrainable_origin_ratio"
            ),
        )
        encoded.by_reason.extend(
            pb.RestrictionCount(
                reason=_enum_to_wire(
                    reason, _FEEDBACK_RESTRICTION_REASON_TO_WIRE, "feedback restriction reason"
                ),
                count=count,
            )
            for reason, count in item.by_reason
        )
        result.restriction_metrics.CopyFrom(encoded)
    result.direction_change_summary.CopyFrom(
        pb.DirectionChangeSummary(
            convert=value.direction_change_summary.convert,
            release=value.direction_change_summary.release,
            flip=value.direction_change_summary.flip,
        )
    )
    if value.ab_diff is not None:
        item = value.ab_diff
        result.ab_diff.CopyFrom(
            pb.AbDiff(
                enabled_extensions=item.enabled_extensions,
                shadow_tau_star=_finite(item.shadow_tau_star, "ab_diff.shadow_tau_star"),
                actual_tau_star=_finite(item.actual_tau_star, "ab_diff.actual_tau_star"),
                shadow_throughput=_finite(item.shadow_throughput, "ab_diff.shadow_throughput"),
                actual_throughput=_finite(item.actual_throughput, "ab_diff.actual_throughput"),
                diff_summary=item.diff_summary,
            )
        )
    if value.forecast_summary is not None:
        item = value.forecast_summary
        forecast = pb.ForecastSummary(
            reproduction_error=_finite(item.reproduction_error, "forecast.reproduction_error")
        )
        forecast.node_demand.extend(
            pb.NodeDemand(
                node_id=_required_id(demand.node_id.value, "node_demand.node_id"),
                gross_out=_finite(demand.gross_out, "node_demand.gross_out"),
                gross_in=_finite(demand.gross_in, "node_demand.gross_in"),
                production=_finite(demand.production, "node_demand.production"),
                absorption=_finite(demand.absorption, "node_demand.absorption"),
                transit=_finite(demand.transit, "node_demand.transit"),
                staying=_finite(demand.staying, "node_demand.staying"),
            )
            for demand in item.node_demand
        )
        forecast.estimation_resolution.extend(
            pb.NodeResolution(
                node_id=_required_id(resolution.node_id.value, "node_resolution.node_id"),
                mode=_enum_to_wire(
                    resolution.mode, _OD_RESOLUTION_MODE_TO_WIRE, "OD resolution mode"
                ),
                reason=_enum_to_wire(
                    resolution.reason, _OD_RESOLUTION_REASON_TO_WIRE, "OD resolution reason"
                ),
                imputed_arcs=tuple(
                    _required_id(edge.value, "node_resolution.imputed_arc")
                    for edge in resolution.imputed_arcs
                ),
            )
            for resolution in item.estimation_resolution
        )
        result.forecast_summary.CopyFrom(forecast)
    result.warnings.extend(_encode_warning(item) for item in value.warnings)
    return result


def _decode_feedback(value: pb.FeedbackValues) -> FeedbackValues:
    if not value.HasField("compute_meta"):
        raise ValueError("missing compute_meta")
    if not value.HasField("objective_values"):
        raise ValueError("missing feedback objective_values")
    if not value.HasField("reference_usage"):
        raise ValueError("missing reference_usage")
    if not value.HasField("quality_metrics"):
        raise ValueError("missing quality_metrics")
    if not value.HasField("direction_change_summary"):
        raise ValueError("missing direction_change_summary")
    prediction = None
    if value.HasField("prediction_actual_diff"):
        item = value.prediction_actual_diff
        prediction = PredictionActualDiff(
            expected_tau_star=_finite(item.expected_tau_star, "prediction.expected_tau_star"),
            actual_tau_star=_finite(item.actual_tau_star, "prediction.actual_tau_star"),
            delta=_finite(item.delta, "prediction.delta"),
        )
    detour = None
    if value.HasField("detour_metrics"):
        item = value.detour_metrics
        detour = DetourMetrics(
            k_requested=item.k_requested,
            k_effective=item.k_effective,
            paths_actually_used_ratio=_finite(
                item.paths_actually_used_ratio, "detour_metrics.paths_actually_used_ratio"
            ),
        )
    restriction = None
    if value.HasField("restriction_metrics"):
        item = value.restriction_metrics
        restriction = RestrictionMetrics(
            proposed_count=item.proposed_count,
            by_reason=tuple(
                (
                    _enum_from_wire(
                        int(reason.reason),
                        _FEEDBACK_RESTRICTION_REASON_FROM_WIRE,
                        "feedback restriction reason",
                    ),
                    reason.count,
                )
                for reason in item.by_reason
            ),
            estimated_inflow_cut=_finite(
                item.estimated_inflow_cut, "restriction_metrics.estimated_inflow_cut"
            ),
            undrainable_origin_ratio=_finite(
                item.undrainable_origin_ratio, "restriction_metrics.undrainable_origin_ratio"
            ),
        )
    ab_diff = None
    if value.HasField("ab_diff"):
        item = value.ab_diff
        ab_diff = AbDiff(
            enabled_extensions=tuple(item.enabled_extensions),
            shadow_tau_star=_finite(item.shadow_tau_star, "ab_diff.shadow_tau_star"),
            actual_tau_star=_finite(item.actual_tau_star, "ab_diff.actual_tau_star"),
            shadow_throughput=_finite(item.shadow_throughput, "ab_diff.shadow_throughput"),
            actual_throughput=_finite(item.actual_throughput, "ab_diff.actual_throughput"),
            diff_summary=item.diff_summary,
        )
    forecast = None
    if value.HasField("forecast_summary"):
        item = value.forecast_summary
        forecast = ForecastSummary(
            node_demand=tuple(
                NodeDemand(
                    node_id=NodeID(_required_id(demand.node_id, "node_demand.node_id")),
                    gross_out=_finite(demand.gross_out, "node_demand.gross_out"),
                    gross_in=_finite(demand.gross_in, "node_demand.gross_in"),
                    production=_finite(demand.production, "node_demand.production"),
                    absorption=_finite(demand.absorption, "node_demand.absorption"),
                    transit=_finite(demand.transit, "node_demand.transit"),
                    staying=_finite(demand.staying, "node_demand.staying"),
                )
                for demand in item.node_demand
            ),
            reproduction_error=_finite(item.reproduction_error, "forecast.reproduction_error"),
            estimation_resolution=tuple(
                NodeResolution(
                    node_id=NodeID(_required_id(resolution.node_id, "node_resolution.node_id")),
                    mode=_enum_from_wire(
                        int(resolution.mode), _OD_RESOLUTION_MODE_FROM_WIRE, "OD resolution mode"
                    ),
                    reason=_enum_from_wire(
                        int(resolution.reason),
                        _OD_RESOLUTION_REASON_FROM_WIRE,
                        "OD resolution reason",
                    ),
                    imputed_arcs=tuple(
                        EdgeID(_required_id(edge, "node_resolution.imputed_arc"))
                        for edge in resolution.imputed_arcs
                    ),
                )
                for resolution in item.estimation_resolution
            ),
        )
    return FeedbackValues(
        schema_version=_required_id(value.schema_version, "feedback.schema_version"),
        compute_meta=_decode_compute_meta(value.compute_meta),
        objective_values=_decode_feedback_objective(value.objective_values),
        per_tag_observations=tuple(
            TagObservation(
                attribute_tag=item.attribute_tag,
                eta_estimate=_finite(item.eta_estimate, "tag_observation.eta_estimate"),
                edge_count=item.edge_count,
                observation_span_min=_finite(
                    item.observation_span_min, "tag_observation.observation_span_min"
                ),
            )
            for item in value.per_tag_observations
        ),
        prediction_actual_diff=prediction,
        reference_usage=ReferenceUsageReport(
            used_tags=tuple(value.reference_usage.used_tags),
            used_default=value.reference_usage.used_default,
            used_edges_count=value.reference_usage.used_edges_count,
        ),
        quality_metrics=QualityMetrics(
            vector_coverage_ratio=_finite(
                value.quality_metrics.vector_coverage_ratio, "quality.vector_coverage_ratio"
            ),
            low_confidence_arc_ratio=_finite(
                value.quality_metrics.low_confidence_arc_ratio, "quality.low_confidence_arc_ratio"
            ),
            history_completeness=_finite(
                value.quality_metrics.history_completeness, "quality.history_completeness"
            ),
        ),
        detour_metrics=detour,
        restriction_metrics=restriction,
        direction_change_summary=DirectionChangeSummary(
            convert=value.direction_change_summary.convert,
            release=value.direction_change_summary.release,
            flip=value.direction_change_summary.flip,
        ),
        ab_diff=ab_diff,
        forecast_summary=forecast,
        warnings=tuple(_decode_warning(item) for item in value.warnings),
    )


def _encode_trigger_evidence(value: TriggerEvidence) -> pb.TriggerEvidence:
    result = pb.TriggerEvidence(
        source=_enum_to_wire(
            value.source, _TRIGGER_EVIDENCE_SOURCE_TO_WIRE, "trigger evidence source"
        ),
    )
    _copy_timestamp(result, "occurred_at", value.occurred_at, "trigger_evidence.occurred_at")
    if value.edge_id is not None:
        result.edge_id = _required_id(value.edge_id, "trigger_evidence.edge_id")
    if value.node_id is not None:
        result.node_id = _required_id(value.node_id, "trigger_evidence.node_id")
    for field, number in (
        ("metric_value", value.metric_value),
        ("threshold_value", value.threshold_value),
        ("duration_min", value.duration_min),
    ):
        if number is not None:
            setattr(result, field, _finite(number, f"trigger_evidence.{field}"))
    return result


def _decode_trigger_evidence(value: pb.TriggerEvidence) -> TriggerEvidence:
    return TriggerEvidence(
        source=_enum_from_wire(
            int(value.source), _TRIGGER_EVIDENCE_SOURCE_FROM_WIRE, "trigger evidence source"
        ),
        occurred_at=_decode_required_datetime(value, "occurred_at"),
        edge_id=_optional_string(value, "edge_id"),
        node_id=_optional_string(value, "node_id"),
        metric_value=_optional_float(value, "metric_value"),
        threshold_value=_optional_float(value, "threshold_value"),
        duration_min=_optional_float(value, "duration_min"),
    )


def _encode_fallback(value: FallbackRecord) -> pb.FallbackRecord:
    return pb.FallbackRecord(
        kind=_enum_to_wire(value.kind, _FALLBACK_KIND_TO_WIRE, "fallback kind"),
        reason=value.reason,
        affected_targets=value.affected_targets,
    )


def _decode_fallback(value: pb.FallbackRecord) -> FallbackRecord:
    return FallbackRecord(
        kind=_enum_from_wire(int(value.kind), _FALLBACK_KIND_FROM_WIRE, "fallback kind"),
        reason=value.reason,
        affected_targets=tuple(value.affected_targets),
    )


def _encode_step(value: StepRecord) -> pb.StepRecord:
    result = pb.StepRecord(
        step=_enum_to_wire(value.step, _STEP_KIND_TO_WIRE, "step kind"),
        elapsed_ms=value.elapsed_ms,
        status=_enum_to_wire(value.status, _STEP_STATUS_TO_WIRE, "step status"),
    )
    if value.note is not None:
        result.note = value.note
    return result


def _decode_step(value: pb.StepRecord) -> StepRecord:
    return StepRecord(
        step=_enum_from_wire(int(value.step), _STEP_KIND_FROM_WIRE, "step kind"),
        elapsed_ms=value.elapsed_ms,
        status=_enum_from_wire(int(value.status), _STEP_STATUS_FROM_WIRE, "step status"),
        note=_optional_string(value, "note"),
    )


def _encode_diagnostics(value: Diagnostics) -> pb.Diagnostics:
    result = pb.Diagnostics(
        mode=_enum_to_wire(value.mode, _MODE_TO_WIRE, "mode"),
        degraded_short_tenant=value.degraded_short_tenant,
        schema_version=value.schema_version,
    )
    result.warnings.extend(_encode_warning(item) for item in value.warnings)
    result.trigger_evidences.extend(
        _encode_trigger_evidence(item) for item in value.trigger_evidences
    )
    result.fallbacks_applied.extend(_encode_fallback(item) for item in value.fallbacks_applied)
    result.steps_executed.extend(_encode_step(item) for item in value.steps_executed)
    return result


def _decode_diagnostics(value: pb.Diagnostics) -> Diagnostics:
    return Diagnostics(
        mode=_enum_from_wire(int(value.mode), _MODE_FROM_WIRE, "mode"),
        warnings=tuple(_decode_warning(item) for item in value.warnings),
        trigger_evidences=tuple(_decode_trigger_evidence(item) for item in value.trigger_evidences),
        fallbacks_applied=tuple(_decode_fallback(item) for item in value.fallbacks_applied),
        steps_executed=tuple(_decode_step(item) for item in value.steps_executed),
        degraded_short_tenant=value.degraded_short_tenant,
        schema_version=_required_id(value.schema_version, "diagnostics.schema_version"),
    )


def _validate_request(value: Request) -> None:
    node_ids = [node.node_id.value for node in value.graph.nodes]
    edge_ids = [edge.edge_id.value for edge in value.graph.edges]
    node_set = set(node_ids)
    edge_set = set(edge_ids)
    for flow in value.observations.arc_flows:
        if flow.edge_id.value not in edge_set:
            raise ValueError("unknown observation edge")
    for stagnation in value.observations.arc_stagnations:
        if stagnation.edge_id.value not in edge_set:
            raise ValueError("unknown stagnation edge")
    for scalar in value.observations.arc_scalar_flows:
        if scalar.edge_id.value not in edge_set:
            raise ValueError("unknown scalar flow edge")
    for occupancy in value.observations.node_occupancies:
        if occupancy.node_id.value not in node_set:
            raise ValueError("unknown occupancy node")
    for turning in value.observations.node_turning:
        if turning.node_id.value not in node_set or turning.from_edge_id.value not in edge_set:
            raise ValueError("unknown turning reference")
        if turning.to_edge_id is not None and turning.to_edge_id.value not in edge_set:
            raise ValueError("unknown turning destination")
    for stat in value.history_digest.arc_stats:
        if stat.edge_id.value not in edge_set:
            raise ValueError("unknown history edge")
    for series in value.history_digest.window_series:
        if series.edge_id.value not in edge_set:
            raise ValueError("unknown history window edge")
        for samples in (series.flow_samples, series.stagnation_samples):
            if tuple(samples) != tuple(sorted(samples, key=lambda sample: sample[0])):
                raise ValueError("history samples are not ordered")
        if series.directional_flow_samples is not None:
            for _, samples in series.directional_flow_samples:
                if tuple(samples) != tuple(sorted(samples, key=lambda sample: sample[0])):
                    raise ValueError("directional samples are not ordered")
    for item in value.detection_state.warmup_states:
        if not item.target_key.startswith(("edge:", "node:")) or not item.target_key[5:]:
            raise ValueError("invalid warmup target")
    for edge in value.config.throughput_target_edges:
        if edge.value not in edge_set:
            raise ValueError("unknown throughput edge")
    for edge, _ in value.config.throughput_max_per_edge:
        if edge.value not in edge_set:
            raise ValueError("unknown throughput limit edge")
    for event in value.events:
        if not event.target_id:
            raise ValueError("empty event target")
        if event.target_id.startswith(("edge:", "node:")) and not event.target_id[5:]:
            raise ValueError("empty event target")
        if (
            event.target_id.startswith("edge:")
            and event.target_id[5:] not in edge_set
            and event.kind != EventKind.ADD_EDGE
        ):
            raise ValueError("unknown event edge")
        if (
            event.target_id.startswith("node:")
            and event.target_id[5:] not in node_set
            and event.kind != EventKind.ADD_NODE
        ):
            raise ValueError("unknown event node")
        if not event.target_id.startswith(("edge:", "node:")):
            raise ValueError("invalid event target")


def _decode_request_message(wire: pb.OptimizeRequest) -> Request:
    _ = _required_string(wire, "event_id")
    if not wire.HasField("tenant_context"):
        raise ValueError("missing tenant_context")
    if not wire.HasField("graph"):
        raise ValueError("missing graph")
    if not wire.HasField("observations"):
        raise ValueError("missing observations")
    if not wire.HasField("history_digest"):
        raise ValueError("missing history_digest")
    if not wire.HasField("detection_state"):
        raise ValueError("missing detection_state")
    if not wire.HasField("references"):
        raise ValueError("missing references")
    if not wire.HasField("config"):
        raise ValueError("missing config")
    request = Request(
        request_id=_required_string(wire, "request_id"),
        tenant_context=_decode_tenant_context(wire.tenant_context),
        graph=_decode_graph(wire.graph),
        observations=_decode_observations(wire.observations),
        history_digest=_decode_history(wire.history_digest),
        detection_state=_decode_detection_state(wire.detection_state),
        references=_decode_references(wire.references),
        config=_decode_config(wire.config),
        server_time=_decode_required_datetime(wire, "server_time"),
        schema_version=_required_string(wire, "schema_version"),
        previous_result=(
            _decode_optimization_result(wire.previous_result)
            if wire.HasField("previous_result")
            else None
        ),
        events=tuple(_decode_event(item) for item in wire.events),
    )
    _validate_request(request)
    return request


def encode_request(request: Request, *, event_id: str) -> pb.OptimizeRequest:
    if not event_id:
        raise ValueError("empty event_id")
    _validate_request(request)
    result = pb.OptimizeRequest(
        request_id=_required_id(request.request_id, "request_id"),
        schema_version=_required_id(request.schema_version, "schema_version"),
        event_id=event_id,
    )
    result.tenant_context.CopyFrom(_encode_tenant_context(request.tenant_context))
    result.graph.CopyFrom(_encode_graph(request.graph))
    result.observations.CopyFrom(_encode_observations(request.observations))
    result.history_digest.CopyFrom(_encode_history(request.history_digest))
    result.detection_state.CopyFrom(_encode_detection_state(request.detection_state))
    result.references.CopyFrom(_encode_references(request.references))
    result.config.CopyFrom(_encode_config(request.config))
    _copy_timestamp(result, "server_time", request.server_time, "server_time")
    if request.previous_result is not None:
        result.previous_result.CopyFrom(_encode_optimization_result(request.previous_result))
    result.events.extend(_encode_event(item) for item in request.events)
    return result


def decode_request(wire: pb.OptimizeRequest) -> Request:
    return _decode_request_message(wire)


def encode_response(response: Response) -> pb.OptimizeResponse:
    if not response.request_id:
        raise ValueError("empty response.request_id")
    result = pb.OptimizeResponse(
        request_id=response.request_id,
        verdict=_enum_to_wire(response.verdict, _VERDICT_TO_WIRE, "verdict"),
        elapsed_ms=response.elapsed_ms,
    )
    result.updated_detection_state.CopyFrom(
        _encode_detection_state(response.updated_detection_state)
    )
    result.feedback_values.CopyFrom(_encode_feedback(response.feedback_values))
    result.diagnostics.CopyFrom(_encode_diagnostics(response.diagnostics))
    if response.optimization_result is not None:
        result.optimization_result.CopyFrom(
            _encode_optimization_result(response.optimization_result)
        )
    return result


def decode_response(wire: pb.OptimizeResponse) -> Response:
    if not wire.HasField("request_id"):
        raise ValueError("missing response.request_id")
    if not wire.HasField("verdict"):
        raise ValueError("missing response.verdict")
    if not wire.HasField("updated_detection_state"):
        raise ValueError("missing updated_detection_state")
    if not wire.HasField("feedback_values"):
        raise ValueError("missing feedback_values")
    if not wire.HasField("diagnostics"):
        raise ValueError("missing diagnostics")
    if wire.elapsed_ms < 0:
        raise ValueError("negative elapsed_ms")
    return Response(
        request_id=_required_string(wire, "request_id"),
        verdict=_enum_from_wire(int(wire.verdict), _VERDICT_FROM_WIRE, "verdict"),
        updated_detection_state=_decode_detection_state(wire.updated_detection_state),
        feedback_values=_decode_feedback(wire.feedback_values),
        diagnostics=_decode_diagnostics(wire.diagnostics),
        optimization_result=(
            _decode_optimization_result(wire.optimization_result)
            if wire.HasField("optimization_result")
            else None
        ),
        elapsed_ms=wire.elapsed_ms,
    )


__all__ = ["decode_request", "decode_response", "encode_request", "encode_response"]
