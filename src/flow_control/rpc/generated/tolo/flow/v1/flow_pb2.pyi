import datetime

from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NodeKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NODE_KIND_UNSPECIFIED: _ClassVar[NodeKind]
    NODE_KIND_GOAL: _ClassVar[NodeKind]
    NODE_KIND_GOAL_TRANSIT_MIXED: _ClassVar[NodeKind]
    NODE_KIND_TRANSIT_ONLY: _ClassVar[NodeKind]

class DirectionConstraint(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DIRECTION_CONSTRAINT_UNSPECIFIED: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_BIDIRECTIONAL_PRIOR: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_ONEWAY_A_TO_B_PRIOR: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_ONEWAY_B_TO_A_PRIOR: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_LEGAL_FIXED_A_TO_B: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_LEGAL_FIXED_B_TO_A: _ClassVar[DirectionConstraint]
    DIRECTION_CONSTRAINT_LEGAL_FIXED_BIDIRECTIONAL: _ClassVar[DirectionConstraint]

class CurrentDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CURRENT_DIRECTION_UNSPECIFIED: _ClassVar[CurrentDirection]
    CURRENT_DIRECTION_A_TO_B: _ClassVar[CurrentDirection]
    CURRENT_DIRECTION_B_TO_A: _ClassVar[CurrentDirection]
    CURRENT_DIRECTION_BIDIRECTIONAL: _ClassVar[CurrentDirection]

class ObservationType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OBSERVATION_TYPE_UNSPECIFIED: _ClassVar[ObservationType]
    OBSERVATION_TYPE_VECTOR: _ClassVar[ObservationType]
    OBSERVATION_TYPE_SCALAR: _ClassVar[ObservationType]

class FlowDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FLOW_DIRECTION_UNSPECIFIED: _ClassVar[FlowDirection]
    FLOW_DIRECTION_A_TO_B: _ClassVar[FlowDirection]
    FLOW_DIRECTION_B_TO_A: _ClassVar[FlowDirection]

class ConfidenceFlag(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONFIDENCE_FLAG_UNSPECIFIED: _ClassVar[ConfidenceFlag]
    CONFIDENCE_FLAG_OK: _ClassVar[ConfidenceFlag]
    CONFIDENCE_FLAG_HOLD: _ClassVar[ConfidenceFlag]
    CONFIDENCE_FLAG_INVALID: _ClassVar[ConfidenceFlag]

class StagnationDerivation(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STAGNATION_DERIVATION_UNSPECIFIED: _ClassVar[StagnationDerivation]
    STAGNATION_DERIVATION_BASIC: _ClassVar[StagnationDerivation]
    STAGNATION_DERIVATION_REFINED: _ClassVar[StagnationDerivation]

class TenantCategory(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TENANT_CATEGORY_UNSPECIFIED: _ClassVar[TenantCategory]
    TENANT_CATEGORY_SHORT_TERM: _ClassVar[TenantCategory]
    TENANT_CATEGORY_LONG_TERM: _ClassVar[TenantCategory]

class OptimizationMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OPTIMIZATION_MODE_UNSPECIFIED: _ClassVar[OptimizationMode]
    OPTIMIZATION_MODE_LIGHTWEIGHT: _ClassVar[OptimizationMode]
    OPTIMIZATION_MODE_STRICT: _ClassVar[OptimizationMode]

class Verdict(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    VERDICT_UNSPECIFIED: _ClassVar[Verdict]
    VERDICT_OPTIMIZED: _ClassVar[Verdict]
    VERDICT_QUEUED: _ClassVar[Verdict]
    VERDICT_SKIPPED_NO_TRIGGER: _ClassVar[Verdict]
    VERDICT_SKIPPED_COOLDOWN: _ClassVar[Verdict]
    VERDICT_SKIPPED_WARMUP: _ClassVar[Verdict]
    VERDICT_SKIPPED_TIME: _ClassVar[Verdict]
    VERDICT_ERROR_SIZE_EXCEEDED: _ClassVar[Verdict]
    VERDICT_ERROR_INVALID_INPUT: _ClassVar[Verdict]

class QueuedTriggerKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    QUEUED_TRIGGER_KIND_UNSPECIFIED: _ClassVar[QueuedTriggerKind]
    QUEUED_TRIGGER_KIND_SURGE: _ClassVar[QueuedTriggerKind]
    QUEUED_TRIGGER_KIND_HIGH_STAGNATION: _ClassVar[QueuedTriggerKind]
    QUEUED_TRIGGER_KIND_PUNCTURE: _ClassVar[QueuedTriggerKind]
    QUEUED_TRIGGER_KIND_DANGER: _ClassVar[QueuedTriggerKind]

class EventKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EVENT_KIND_UNSPECIFIED: _ClassVar[EventKind]
    EVENT_KIND_DANGER_FLAG_UP: _ClassVar[EventKind]
    EVENT_KIND_DANGER_FLAG_DOWN: _ClassVar[EventKind]
    EVENT_KIND_DIRECTION_SWITCH: _ClassVar[EventKind]
    EVENT_KIND_ADD_EDGE: _ClassVar[EventKind]
    EVENT_KIND_ADD_NODE: _ClassVar[EventKind]
    EVENT_KIND_DISABLE: _ClassVar[EventKind]
    EVENT_KIND_ENABLE: _ClassVar[EventKind]
    EVENT_KIND_SCHEDULED_INFLOW: _ClassVar[EventKind]
    EVENT_KIND_SCHEDULED_ATTR_CHANGE: _ClassVar[EventKind]
    EVENT_KIND_SENSOR_SET_CHANGED: _ClassVar[EventKind]

class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MODE_UNSPECIFIED: _ClassVar[Mode]
    MODE_OPEN: _ClassVar[Mode]
    MODE_CLOSED: _ClassVar[Mode]

class RestrictionReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RESTRICTION_REASON_UNSPECIFIED: _ClassVar[RestrictionReason]
    RESTRICTION_REASON_UNDRAINABLE_STAGNATION: _ClassVar[RestrictionReason]
    RESTRICTION_REASON_RESIDUAL_TAU: _ClassVar[RestrictionReason]
    RESTRICTION_REASON_PUNCTURE: _ClassVar[RestrictionReason]
    RESTRICTION_REASON_NODE_DANGER_UPSTREAM: _ClassVar[RestrictionReason]
    RESTRICTION_REASON_OVERLOAD: _ClassVar[RestrictionReason]

class SolverStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SOLVER_STATUS_UNSPECIFIED: _ClassVar[SolverStatus]
    SOLVER_STATUS_OPTIMAL: _ClassVar[SolverStatus]
    SOLVER_STATUS_FEASIBLE: _ClassVar[SolverStatus]
    SOLVER_STATUS_INFEASIBLE: _ClassVar[SolverStatus]
    SOLVER_STATUS_TIMEOUT: _ClassVar[SolverStatus]
    SOLVER_STATUS_LIGHTWEIGHT: _ClassVar[SolverStatus]

class ImportanceDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    IMPORTANCE_DIRECTION_UNSPECIFIED: _ClassVar[ImportanceDirection]
    IMPORTANCE_DIRECTION_A_TO_B: _ClassVar[ImportanceDirection]
    IMPORTANCE_DIRECTION_B_TO_A: _ClassVar[ImportanceDirection]
    IMPORTANCE_DIRECTION_NONE: _ClassVar[ImportanceDirection]

class ProposedDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROPOSED_DIRECTION_UNSPECIFIED: _ClassVar[ProposedDirection]
    PROPOSED_DIRECTION_A_TO_B: _ClassVar[ProposedDirection]
    PROPOSED_DIRECTION_B_TO_A: _ClassVar[ProposedDirection]
    PROPOSED_DIRECTION_BIDIRECTIONAL: _ClassVar[ProposedDirection]

class DirectionChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DIRECTION_CHANGE_TYPE_UNSPECIFIED: _ClassVar[DirectionChangeType]
    DIRECTION_CHANGE_TYPE_CONVERT_ONEWAY: _ClassVar[DirectionChangeType]
    DIRECTION_CHANGE_TYPE_RELEASE_ONEWAY: _ClassVar[DirectionChangeType]
    DIRECTION_CHANGE_TYPE_FLIP_ONEWAY: _ClassVar[DirectionChangeType]
    DIRECTION_CHANGE_TYPE_KEEP: _ClassVar[DirectionChangeType]

class RestrictionAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RESTRICTION_ACTION_UNSPECIFIED: _ClassVar[RestrictionAction]
    RESTRICTION_ACTION_CLOSE: _ClassVar[RestrictionAction]
    RESTRICTION_ACTION_LIMIT: _ClassVar[RestrictionAction]
    RESTRICTION_ACTION_RESUME: _ClassVar[RestrictionAction]

class BoundaryAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BOUNDARY_ACTION_UNSPECIFIED: _ClassVar[BoundaryAction]
    BOUNDARY_ACTION_PAUSE_INGRESS: _ClassVar[BoundaryAction]
    BOUNDARY_ACTION_PAUSE_EGRESS: _ClassVar[BoundaryAction]
    BOUNDARY_ACTION_RESUME: _ClassVar[BoundaryAction]

class WarningCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WARNING_CODE_UNSPECIFIED: _ClassVar[WarningCode]
    WARNING_CODE_RETRIGGER: _ClassVar[WarningCode]
    WARNING_CODE_SIZE_NEAR_LIMIT: _ClassVar[WarningCode]
    WARNING_CODE_CONSTRAINT_NEAR: _ClassVar[WarningCode]
    WARNING_CODE_LOW_COVERAGE: _ClassVar[WarningCode]
    WARNING_CODE_FALLBACK_APPLIED: _ClassVar[WarningCode]
    WARNING_CODE_QUEUE_EXPIRED: _ClassVar[WarningCode]
    WARNING_CODE_SOLVER_GIVEUP: _ClassVar[WarningCode]
    WARNING_CODE_UNDRAINABLE_EDGE: _ClassVar[WarningCode]
    WARNING_CODE_MANY_TRIGGER_ZONES: _ClassVar[WarningCode]
    WARNING_CODE_LOW_CONFIDENCE_PROPOSAL: _ClassVar[WarningCode]
    WARNING_CODE_INSUFFICIENT_WINDOW_SAMPLES: _ClassVar[WarningCode]
    WARNING_CODE_SURGE_PROXY_FALLBACK: _ClassVar[WarningCode]
    WARNING_CODE_DEGRADED_COMBINED_TRIGGER: _ClassVar[WarningCode]

class TriggerEvidenceSource(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRIGGER_EVIDENCE_SOURCE_UNSPECIFIED: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_SURGE: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_HIGH_STAGNATION: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_PUNCTURE: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_DANGER: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_QUEUE_SCORE: _ClassVar[TriggerEvidenceSource]
    TRIGGER_EVIDENCE_SOURCE_QUEUE_DIVERSITY: _ClassVar[TriggerEvidenceSource]

class FallbackKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FALLBACK_KIND_UNSPECIFIED: _ClassVar[FallbackKind]
    FALLBACK_KIND_REFERENCE_USED: _ClassVar[FallbackKind]
    FALLBACK_KIND_DEFAULT_ETA_USED: _ClassVar[FallbackKind]
    FALLBACK_KIND_PERCENTILE_DEGRADED: _ClassVar[FallbackKind]
    FALLBACK_KIND_DIRECTION_PROPOSAL_HELD: _ClassVar[FallbackKind]
    FALLBACK_KIND_PHASE2_SKIPPED: _ClassVar[FallbackKind]
    FALLBACK_KIND_BUDGET_EXTENDED: _ClassVar[FallbackKind]
    FALLBACK_KIND_FORECAST_PRIOR_DEGRADED: _ClassVar[FallbackKind]
    FALLBACK_KIND_FORECAST_ARC_IMPUTED: _ClassVar[FallbackKind]
    FALLBACK_KIND_INFEASIBLE_LP_RELAXED: _ClassVar[FallbackKind]
    FALLBACK_KIND_DETOUR_TRUNCATED: _ClassVar[FallbackKind]
    FALLBACK_KIND_LP_INFEASIBLE_HELD: _ClassVar[FallbackKind]
    FALLBACK_KIND_GREEDY_NO_IMPROVEMENT: _ClassVar[FallbackKind]
    FALLBACK_KIND_LOCALIZATION_CAPPED: _ClassVar[FallbackKind]
    FALLBACK_KIND_RESTRICTION_PROPOSED: _ClassVar[FallbackKind]

class StepKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STEP_KIND_UNSPECIFIED: _ClassVar[StepKind]
    STEP_KIND_VALIDATION: _ClassVar[StepKind]
    STEP_KIND_MODE_DECISION: _ClassVar[StepKind]
    STEP_KIND_EVENTS_APPLY: _ClassVar[StepKind]
    STEP_KIND_DETECTION: _ClassVar[StepKind]
    STEP_KIND_FORECASTING: _ClassVar[StepKind]
    STEP_KIND_DETOUR: _ClassVar[StepKind]
    STEP_KIND_OPTIMIZATION: _ClassVar[StepKind]
    STEP_KIND_FEEDBACK: _ClassVar[StepKind]

class StepStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STEP_STATUS_UNSPECIFIED: _ClassVar[StepStatus]
    STEP_STATUS_OK: _ClassVar[StepStatus]
    STEP_STATUS_SKIPPED: _ClassVar[StepStatus]
    STEP_STATUS_FAILED: _ClassVar[StepStatus]

class ODResolutionMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OD_RESOLUTION_MODE_UNSPECIFIED: _ClassVar[ODResolutionMode]
    OD_RESOLUTION_MODE_TURNING_EXACT: _ClassVar[ODResolutionMode]
    OD_RESOLUTION_MODE_DOUBLY_CONSTRAINED: _ClassVar[ODResolutionMode]
    OD_RESOLUTION_MODE_DISTANCE_PRIOR: _ClassVar[ODResolutionMode]

class ODResolutionReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OD_RESOLUTION_REASON_UNSPECIFIED: _ClassVar[ODResolutionReason]
    OD_RESOLUTION_REASON_DETERMINED: _ClassVar[ODResolutionReason]
    OD_RESOLUTION_REASON_MERGE_SPLIT_AMBIGUOUS: _ClassVar[ODResolutionReason]
    OD_RESOLUTION_REASON_SPARSE_OBSERVATION: _ClassVar[ODResolutionReason]
    OD_RESOLUTION_REASON_NODE_ONLY: _ClassVar[ODResolutionReason]
NODE_KIND_UNSPECIFIED: NodeKind
NODE_KIND_GOAL: NodeKind
NODE_KIND_GOAL_TRANSIT_MIXED: NodeKind
NODE_KIND_TRANSIT_ONLY: NodeKind
DIRECTION_CONSTRAINT_UNSPECIFIED: DirectionConstraint
DIRECTION_CONSTRAINT_BIDIRECTIONAL_PRIOR: DirectionConstraint
DIRECTION_CONSTRAINT_ONEWAY_A_TO_B_PRIOR: DirectionConstraint
DIRECTION_CONSTRAINT_ONEWAY_B_TO_A_PRIOR: DirectionConstraint
DIRECTION_CONSTRAINT_LEGAL_FIXED_A_TO_B: DirectionConstraint
DIRECTION_CONSTRAINT_LEGAL_FIXED_B_TO_A: DirectionConstraint
DIRECTION_CONSTRAINT_LEGAL_FIXED_BIDIRECTIONAL: DirectionConstraint
CURRENT_DIRECTION_UNSPECIFIED: CurrentDirection
CURRENT_DIRECTION_A_TO_B: CurrentDirection
CURRENT_DIRECTION_B_TO_A: CurrentDirection
CURRENT_DIRECTION_BIDIRECTIONAL: CurrentDirection
OBSERVATION_TYPE_UNSPECIFIED: ObservationType
OBSERVATION_TYPE_VECTOR: ObservationType
OBSERVATION_TYPE_SCALAR: ObservationType
FLOW_DIRECTION_UNSPECIFIED: FlowDirection
FLOW_DIRECTION_A_TO_B: FlowDirection
FLOW_DIRECTION_B_TO_A: FlowDirection
CONFIDENCE_FLAG_UNSPECIFIED: ConfidenceFlag
CONFIDENCE_FLAG_OK: ConfidenceFlag
CONFIDENCE_FLAG_HOLD: ConfidenceFlag
CONFIDENCE_FLAG_INVALID: ConfidenceFlag
STAGNATION_DERIVATION_UNSPECIFIED: StagnationDerivation
STAGNATION_DERIVATION_BASIC: StagnationDerivation
STAGNATION_DERIVATION_REFINED: StagnationDerivation
TENANT_CATEGORY_UNSPECIFIED: TenantCategory
TENANT_CATEGORY_SHORT_TERM: TenantCategory
TENANT_CATEGORY_LONG_TERM: TenantCategory
OPTIMIZATION_MODE_UNSPECIFIED: OptimizationMode
OPTIMIZATION_MODE_LIGHTWEIGHT: OptimizationMode
OPTIMIZATION_MODE_STRICT: OptimizationMode
VERDICT_UNSPECIFIED: Verdict
VERDICT_OPTIMIZED: Verdict
VERDICT_QUEUED: Verdict
VERDICT_SKIPPED_NO_TRIGGER: Verdict
VERDICT_SKIPPED_COOLDOWN: Verdict
VERDICT_SKIPPED_WARMUP: Verdict
VERDICT_SKIPPED_TIME: Verdict
VERDICT_ERROR_SIZE_EXCEEDED: Verdict
VERDICT_ERROR_INVALID_INPUT: Verdict
QUEUED_TRIGGER_KIND_UNSPECIFIED: QueuedTriggerKind
QUEUED_TRIGGER_KIND_SURGE: QueuedTriggerKind
QUEUED_TRIGGER_KIND_HIGH_STAGNATION: QueuedTriggerKind
QUEUED_TRIGGER_KIND_PUNCTURE: QueuedTriggerKind
QUEUED_TRIGGER_KIND_DANGER: QueuedTriggerKind
EVENT_KIND_UNSPECIFIED: EventKind
EVENT_KIND_DANGER_FLAG_UP: EventKind
EVENT_KIND_DANGER_FLAG_DOWN: EventKind
EVENT_KIND_DIRECTION_SWITCH: EventKind
EVENT_KIND_ADD_EDGE: EventKind
EVENT_KIND_ADD_NODE: EventKind
EVENT_KIND_DISABLE: EventKind
EVENT_KIND_ENABLE: EventKind
EVENT_KIND_SCHEDULED_INFLOW: EventKind
EVENT_KIND_SCHEDULED_ATTR_CHANGE: EventKind
EVENT_KIND_SENSOR_SET_CHANGED: EventKind
MODE_UNSPECIFIED: Mode
MODE_OPEN: Mode
MODE_CLOSED: Mode
RESTRICTION_REASON_UNSPECIFIED: RestrictionReason
RESTRICTION_REASON_UNDRAINABLE_STAGNATION: RestrictionReason
RESTRICTION_REASON_RESIDUAL_TAU: RestrictionReason
RESTRICTION_REASON_PUNCTURE: RestrictionReason
RESTRICTION_REASON_NODE_DANGER_UPSTREAM: RestrictionReason
RESTRICTION_REASON_OVERLOAD: RestrictionReason
SOLVER_STATUS_UNSPECIFIED: SolverStatus
SOLVER_STATUS_OPTIMAL: SolverStatus
SOLVER_STATUS_FEASIBLE: SolverStatus
SOLVER_STATUS_INFEASIBLE: SolverStatus
SOLVER_STATUS_TIMEOUT: SolverStatus
SOLVER_STATUS_LIGHTWEIGHT: SolverStatus
IMPORTANCE_DIRECTION_UNSPECIFIED: ImportanceDirection
IMPORTANCE_DIRECTION_A_TO_B: ImportanceDirection
IMPORTANCE_DIRECTION_B_TO_A: ImportanceDirection
IMPORTANCE_DIRECTION_NONE: ImportanceDirection
PROPOSED_DIRECTION_UNSPECIFIED: ProposedDirection
PROPOSED_DIRECTION_A_TO_B: ProposedDirection
PROPOSED_DIRECTION_B_TO_A: ProposedDirection
PROPOSED_DIRECTION_BIDIRECTIONAL: ProposedDirection
DIRECTION_CHANGE_TYPE_UNSPECIFIED: DirectionChangeType
DIRECTION_CHANGE_TYPE_CONVERT_ONEWAY: DirectionChangeType
DIRECTION_CHANGE_TYPE_RELEASE_ONEWAY: DirectionChangeType
DIRECTION_CHANGE_TYPE_FLIP_ONEWAY: DirectionChangeType
DIRECTION_CHANGE_TYPE_KEEP: DirectionChangeType
RESTRICTION_ACTION_UNSPECIFIED: RestrictionAction
RESTRICTION_ACTION_CLOSE: RestrictionAction
RESTRICTION_ACTION_LIMIT: RestrictionAction
RESTRICTION_ACTION_RESUME: RestrictionAction
BOUNDARY_ACTION_UNSPECIFIED: BoundaryAction
BOUNDARY_ACTION_PAUSE_INGRESS: BoundaryAction
BOUNDARY_ACTION_PAUSE_EGRESS: BoundaryAction
BOUNDARY_ACTION_RESUME: BoundaryAction
WARNING_CODE_UNSPECIFIED: WarningCode
WARNING_CODE_RETRIGGER: WarningCode
WARNING_CODE_SIZE_NEAR_LIMIT: WarningCode
WARNING_CODE_CONSTRAINT_NEAR: WarningCode
WARNING_CODE_LOW_COVERAGE: WarningCode
WARNING_CODE_FALLBACK_APPLIED: WarningCode
WARNING_CODE_QUEUE_EXPIRED: WarningCode
WARNING_CODE_SOLVER_GIVEUP: WarningCode
WARNING_CODE_UNDRAINABLE_EDGE: WarningCode
WARNING_CODE_MANY_TRIGGER_ZONES: WarningCode
WARNING_CODE_LOW_CONFIDENCE_PROPOSAL: WarningCode
WARNING_CODE_INSUFFICIENT_WINDOW_SAMPLES: WarningCode
WARNING_CODE_SURGE_PROXY_FALLBACK: WarningCode
WARNING_CODE_DEGRADED_COMBINED_TRIGGER: WarningCode
TRIGGER_EVIDENCE_SOURCE_UNSPECIFIED: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_SURGE: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_HIGH_STAGNATION: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_PUNCTURE: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_DANGER: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_QUEUE_SCORE: TriggerEvidenceSource
TRIGGER_EVIDENCE_SOURCE_QUEUE_DIVERSITY: TriggerEvidenceSource
FALLBACK_KIND_UNSPECIFIED: FallbackKind
FALLBACK_KIND_REFERENCE_USED: FallbackKind
FALLBACK_KIND_DEFAULT_ETA_USED: FallbackKind
FALLBACK_KIND_PERCENTILE_DEGRADED: FallbackKind
FALLBACK_KIND_DIRECTION_PROPOSAL_HELD: FallbackKind
FALLBACK_KIND_PHASE2_SKIPPED: FallbackKind
FALLBACK_KIND_BUDGET_EXTENDED: FallbackKind
FALLBACK_KIND_FORECAST_PRIOR_DEGRADED: FallbackKind
FALLBACK_KIND_FORECAST_ARC_IMPUTED: FallbackKind
FALLBACK_KIND_INFEASIBLE_LP_RELAXED: FallbackKind
FALLBACK_KIND_DETOUR_TRUNCATED: FallbackKind
FALLBACK_KIND_LP_INFEASIBLE_HELD: FallbackKind
FALLBACK_KIND_GREEDY_NO_IMPROVEMENT: FallbackKind
FALLBACK_KIND_LOCALIZATION_CAPPED: FallbackKind
FALLBACK_KIND_RESTRICTION_PROPOSED: FallbackKind
STEP_KIND_UNSPECIFIED: StepKind
STEP_KIND_VALIDATION: StepKind
STEP_KIND_MODE_DECISION: StepKind
STEP_KIND_EVENTS_APPLY: StepKind
STEP_KIND_DETECTION: StepKind
STEP_KIND_FORECASTING: StepKind
STEP_KIND_DETOUR: StepKind
STEP_KIND_OPTIMIZATION: StepKind
STEP_KIND_FEEDBACK: StepKind
STEP_STATUS_UNSPECIFIED: StepStatus
STEP_STATUS_OK: StepStatus
STEP_STATUS_SKIPPED: StepStatus
STEP_STATUS_FAILED: StepStatus
OD_RESOLUTION_MODE_UNSPECIFIED: ODResolutionMode
OD_RESOLUTION_MODE_TURNING_EXACT: ODResolutionMode
OD_RESOLUTION_MODE_DOUBLY_CONSTRAINED: ODResolutionMode
OD_RESOLUTION_MODE_DISTANCE_PRIOR: ODResolutionMode
OD_RESOLUTION_REASON_UNSPECIFIED: ODResolutionReason
OD_RESOLUTION_REASON_DETERMINED: ODResolutionReason
OD_RESOLUTION_REASON_MERGE_SPLIT_AMBIGUOUS: ODResolutionReason
OD_RESOLUTION_REASON_SPARSE_OBSERVATION: ODResolutionReason
OD_RESOLUTION_REASON_NODE_ONLY: ODResolutionReason

class OptimizeRequest(_message.Message):
    __slots__ = ("request_id", "schema_version", "event_id", "tenant_context", "graph", "observations", "history_digest", "detection_state", "references", "previous_result", "events", "config", "server_time")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    TENANT_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    GRAPH_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    HISTORY_DIGEST_FIELD_NUMBER: _ClassVar[int]
    DETECTION_STATE_FIELD_NUMBER: _ClassVar[int]
    REFERENCES_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_RESULT_FIELD_NUMBER: _ClassVar[int]
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SERVER_TIME_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    schema_version: str
    event_id: str
    tenant_context: TenantContext
    graph: Graph
    observations: Observations
    history_digest: HistoryDigest
    detection_state: DetectionState
    references: Reference
    previous_result: OptimizationResult
    events: _containers.RepeatedCompositeFieldContainer[Event]
    config: ResolvedConfig
    server_time: _timestamp_pb2.Timestamp
    def __init__(self, request_id: _Optional[str] = ..., schema_version: _Optional[str] = ..., event_id: _Optional[str] = ..., tenant_context: _Optional[_Union[TenantContext, _Mapping]] = ..., graph: _Optional[_Union[Graph, _Mapping]] = ..., observations: _Optional[_Union[Observations, _Mapping]] = ..., history_digest: _Optional[_Union[HistoryDigest, _Mapping]] = ..., detection_state: _Optional[_Union[DetectionState, _Mapping]] = ..., references: _Optional[_Union[Reference, _Mapping]] = ..., previous_result: _Optional[_Union[OptimizationResult, _Mapping]] = ..., events: _Optional[_Iterable[_Union[Event, _Mapping]]] = ..., config: _Optional[_Union[ResolvedConfig, _Mapping]] = ..., server_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class OptimizeResponse(_message.Message):
    __slots__ = ("request_id", "verdict", "updated_detection_state", "feedback_values", "diagnostics", "optimization_result", "elapsed_ms")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    VERDICT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_DETECTION_STATE_FIELD_NUMBER: _ClassVar[int]
    FEEDBACK_VALUES_FIELD_NUMBER: _ClassVar[int]
    DIAGNOSTICS_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZATION_RESULT_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    verdict: Verdict
    updated_detection_state: DetectionState
    feedback_values: FeedbackValues
    diagnostics: Diagnostics
    optimization_result: OptimizationResult
    elapsed_ms: int
    def __init__(self, request_id: _Optional[str] = ..., verdict: _Optional[_Union[Verdict, str]] = ..., updated_detection_state: _Optional[_Union[DetectionState, _Mapping]] = ..., feedback_values: _Optional[_Union[FeedbackValues, _Mapping]] = ..., diagnostics: _Optional[_Union[Diagnostics, _Mapping]] = ..., optimization_result: _Optional[_Union[OptimizationResult, _Mapping]] = ..., elapsed_ms: _Optional[int] = ...) -> None: ...

class TenantContext(_message.Message):
    __slots__ = ("tenant_id", "tenant_category", "available_history_hours")
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    TENANT_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_HISTORY_HOURS_FIELD_NUMBER: _ClassVar[int]
    tenant_id: str
    tenant_category: TenantCategory
    available_history_hours: float
    def __init__(self, tenant_id: _Optional[str] = ..., tenant_category: _Optional[_Union[TenantCategory, str]] = ..., available_history_hours: _Optional[float] = ...) -> None: ...

class Graph(_message.Message):
    __slots__ = ("nodes", "edges")
    NODES_FIELD_NUMBER: _ClassVar[int]
    EDGES_FIELD_NUMBER: _ClassVar[int]
    nodes: _containers.RepeatedCompositeFieldContainer[Node]
    edges: _containers.RepeatedCompositeFieldContainer[Edge]
    def __init__(self, nodes: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., edges: _Optional[_Iterable[_Union[Edge, _Mapping]]] = ...) -> None: ...

class Node(_message.Message):
    __slots__ = ("node_id", "kind", "is_boundary", "enabled", "attribute_tags", "time_resolution_s", "danger_flag", "danger_capacity")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    IS_BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTE_TAGS_FIELD_NUMBER: _ClassVar[int]
    TIME_RESOLUTION_S_FIELD_NUMBER: _ClassVar[int]
    DANGER_FLAG_FIELD_NUMBER: _ClassVar[int]
    DANGER_CAPACITY_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    kind: NodeKind
    is_boundary: bool
    enabled: bool
    attribute_tags: _containers.RepeatedScalarFieldContainer[str]
    time_resolution_s: int
    danger_flag: bool
    danger_capacity: float
    def __init__(self, node_id: _Optional[str] = ..., kind: _Optional[_Union[NodeKind, str]] = ..., is_boundary: bool = ..., enabled: bool = ..., attribute_tags: _Optional[_Iterable[str]] = ..., time_resolution_s: _Optional[int] = ..., danger_flag: bool = ..., danger_capacity: _Optional[float] = ...) -> None: ...

class Edge(_message.Message):
    __slots__ = ("edge_id", "endpoint_a", "endpoint_b", "direction_constraint", "current_direction", "enabled", "observation_type", "attribute_tags", "time_resolution_s", "danger_flag", "danger_capacity", "capacity_hint")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_A_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_B_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_CONSTRAINT_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DIRECTION_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_TYPE_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTE_TAGS_FIELD_NUMBER: _ClassVar[int]
    TIME_RESOLUTION_S_FIELD_NUMBER: _ClassVar[int]
    DANGER_FLAG_FIELD_NUMBER: _ClassVar[int]
    DANGER_CAPACITY_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_HINT_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    endpoint_a: str
    endpoint_b: str
    direction_constraint: DirectionConstraint
    current_direction: CurrentDirection
    enabled: bool
    observation_type: ObservationType
    attribute_tags: _containers.RepeatedScalarFieldContainer[str]
    time_resolution_s: int
    danger_flag: bool
    danger_capacity: float
    capacity_hint: float
    def __init__(self, edge_id: _Optional[str] = ..., endpoint_a: _Optional[str] = ..., endpoint_b: _Optional[str] = ..., direction_constraint: _Optional[_Union[DirectionConstraint, str]] = ..., current_direction: _Optional[_Union[CurrentDirection, str]] = ..., enabled: bool = ..., observation_type: _Optional[_Union[ObservationType, str]] = ..., attribute_tags: _Optional[_Iterable[str]] = ..., time_resolution_s: _Optional[int] = ..., danger_flag: bool = ..., danger_capacity: _Optional[float] = ..., capacity_hint: _Optional[float] = ...) -> None: ...

class Observations(_message.Message):
    __slots__ = ("observed_at", "snapshot_ref", "arc_flows", "arc_stagnations", "arc_scalar_flows", "node_occupancies", "node_turning")
    OBSERVED_AT_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_REF_FIELD_NUMBER: _ClassVar[int]
    ARC_FLOWS_FIELD_NUMBER: _ClassVar[int]
    ARC_STAGNATIONS_FIELD_NUMBER: _ClassVar[int]
    ARC_SCALAR_FLOWS_FIELD_NUMBER: _ClassVar[int]
    NODE_OCCUPANCIES_FIELD_NUMBER: _ClassVar[int]
    NODE_TURNING_FIELD_NUMBER: _ClassVar[int]
    observed_at: _timestamp_pb2.Timestamp
    snapshot_ref: str
    arc_flows: _containers.RepeatedCompositeFieldContainer[ArcFlow]
    arc_stagnations: _containers.RepeatedCompositeFieldContainer[ArcStagnation]
    arc_scalar_flows: _containers.RepeatedCompositeFieldContainer[ArcScalarFlow]
    node_occupancies: _containers.RepeatedCompositeFieldContainer[NodeOccupancy]
    node_turning: _containers.RepeatedCompositeFieldContainer[TurningObservation]
    def __init__(self, observed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., snapshot_ref: _Optional[str] = ..., arc_flows: _Optional[_Iterable[_Union[ArcFlow, _Mapping]]] = ..., arc_stagnations: _Optional[_Iterable[_Union[ArcStagnation, _Mapping]]] = ..., arc_scalar_flows: _Optional[_Iterable[_Union[ArcScalarFlow, _Mapping]]] = ..., node_occupancies: _Optional[_Iterable[_Union[NodeOccupancy, _Mapping]]] = ..., node_turning: _Optional[_Iterable[_Union[TurningObservation, _Mapping]]] = ...) -> None: ...

class ArcFlow(_message.Message):
    __slots__ = ("edge_id", "direction", "flow_rate", "confidence_flag")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    FLOW_RATE_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FLAG_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    direction: FlowDirection
    flow_rate: float
    confidence_flag: ConfidenceFlag
    def __init__(self, edge_id: _Optional[str] = ..., direction: _Optional[_Union[FlowDirection, str]] = ..., flow_rate: _Optional[float] = ..., confidence_flag: _Optional[_Union[ConfidenceFlag, str]] = ...) -> None: ...

class ArcStagnation(_message.Message):
    __slots__ = ("edge_id", "stagnation", "derivation", "same_sensor_flow", "confidence_flag")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    STAGNATION_FIELD_NUMBER: _ClassVar[int]
    DERIVATION_FIELD_NUMBER: _ClassVar[int]
    SAME_SENSOR_FLOW_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FLAG_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    stagnation: float
    derivation: StagnationDerivation
    same_sensor_flow: bool
    confidence_flag: ConfidenceFlag
    def __init__(self, edge_id: _Optional[str] = ..., stagnation: _Optional[float] = ..., derivation: _Optional[_Union[StagnationDerivation, str]] = ..., same_sensor_flow: bool = ..., confidence_flag: _Optional[_Union[ConfidenceFlag, str]] = ...) -> None: ...

class ArcScalarFlow(_message.Message):
    __slots__ = ("edge_id", "observed_count", "confidence_flag")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_COUNT_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FLAG_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    observed_count: float
    confidence_flag: ConfidenceFlag
    def __init__(self, edge_id: _Optional[str] = ..., observed_count: _Optional[float] = ..., confidence_flag: _Optional[_Union[ConfidenceFlag, str]] = ...) -> None: ...

class NodeOccupancy(_message.Message):
    __slots__ = ("node_id", "occupancy", "occupancy_delta", "same_sensor_arrival", "confidence_flag")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    OCCUPANCY_FIELD_NUMBER: _ClassVar[int]
    OCCUPANCY_DELTA_FIELD_NUMBER: _ClassVar[int]
    SAME_SENSOR_ARRIVAL_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FLAG_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    occupancy: float
    occupancy_delta: float
    same_sensor_arrival: bool
    confidence_flag: ConfidenceFlag
    def __init__(self, node_id: _Optional[str] = ..., occupancy: _Optional[float] = ..., occupancy_delta: _Optional[float] = ..., same_sensor_arrival: bool = ..., confidence_flag: _Optional[_Union[ConfidenceFlag, str]] = ...) -> None: ...

class TurningObservation(_message.Message):
    __slots__ = ("node_id", "from_edge_id", "to_edge_id", "ratio", "confidence_flag")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    TO_EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    RATIO_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FLAG_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    from_edge_id: str
    to_edge_id: str
    ratio: float
    confidence_flag: ConfidenceFlag
    def __init__(self, node_id: _Optional[str] = ..., from_edge_id: _Optional[str] = ..., to_edge_id: _Optional[str] = ..., ratio: _Optional[float] = ..., confidence_flag: _Optional[_Union[ConfidenceFlag, str]] = ...) -> None: ...

class HistoryDigest(_message.Message):
    __slots__ = ("arc_stats", "window_series", "completeness")
    ARC_STATS_FIELD_NUMBER: _ClassVar[int]
    WINDOW_SERIES_FIELD_NUMBER: _ClassVar[int]
    COMPLETENESS_FIELD_NUMBER: _ClassVar[int]
    arc_stats: _containers.RepeatedCompositeFieldContainer[ArcHistoryStat]
    window_series: _containers.RepeatedCompositeFieldContainer[ArcWindowSeries]
    completeness: float
    def __init__(self, arc_stats: _Optional[_Iterable[_Union[ArcHistoryStat, _Mapping]]] = ..., window_series: _Optional[_Iterable[_Union[ArcWindowSeries, _Mapping]]] = ..., completeness: _Optional[float] = ...) -> None: ...

class ArcHistoryStat(_message.Message):
    __slots__ = ("edge_id", "p90_stagnation", "baseline_stagnation", "flow_sensitivity_eta", "available_span_hours")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    P90_STAGNATION_FIELD_NUMBER: _ClassVar[int]
    BASELINE_STAGNATION_FIELD_NUMBER: _ClassVar[int]
    FLOW_SENSITIVITY_ETA_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_SPAN_HOURS_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    p90_stagnation: float
    baseline_stagnation: float
    flow_sensitivity_eta: float
    available_span_hours: float
    def __init__(self, edge_id: _Optional[str] = ..., p90_stagnation: _Optional[float] = ..., baseline_stagnation: _Optional[float] = ..., flow_sensitivity_eta: _Optional[float] = ..., available_span_hours: _Optional[float] = ...) -> None: ...

class ArcWindowSeries(_message.Message):
    __slots__ = ("edge_id", "flow_samples", "stagnation_samples", "directional_flow_samples")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    FLOW_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    STAGNATION_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    DIRECTIONAL_FLOW_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    flow_samples: _containers.RepeatedCompositeFieldContainer[TimedValue]
    stagnation_samples: _containers.RepeatedCompositeFieldContainer[TimedValue]
    directional_flow_samples: DirectionalFlowSamples
    def __init__(self, edge_id: _Optional[str] = ..., flow_samples: _Optional[_Iterable[_Union[TimedValue, _Mapping]]] = ..., stagnation_samples: _Optional[_Iterable[_Union[TimedValue, _Mapping]]] = ..., directional_flow_samples: _Optional[_Union[DirectionalFlowSamples, _Mapping]] = ...) -> None: ...

class DirectionalFlowSamples(_message.Message):
    __slots__ = ("series",)
    SERIES_FIELD_NUMBER: _ClassVar[int]
    series: _containers.RepeatedCompositeFieldContainer[DirectionalSeries]
    def __init__(self, series: _Optional[_Iterable[_Union[DirectionalSeries, _Mapping]]] = ...) -> None: ...

class DirectionalSeries(_message.Message):
    __slots__ = ("direction", "samples")
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    SAMPLES_FIELD_NUMBER: _ClassVar[int]
    direction: FlowDirection
    samples: _containers.RepeatedCompositeFieldContainer[TimedValue]
    def __init__(self, direction: _Optional[_Union[FlowDirection, str]] = ..., samples: _Optional[_Iterable[_Union[TimedValue, _Mapping]]] = ...) -> None: ...

class TimedValue(_message.Message):
    __slots__ = ("at", "value")
    AT_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    at: _timestamp_pb2.Timestamp
    value: float
    def __init__(self, at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., value: _Optional[float] = ...) -> None: ...

class DetectionState(_message.Message):
    __slots__ = ("cooldown_until", "trigger_queue", "arc_watch_states", "arc_demand_digest", "warmup_states", "arc_retrigger_counts", "consecutive_skip_count")
    COOLDOWN_UNTIL_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_QUEUE_FIELD_NUMBER: _ClassVar[int]
    ARC_WATCH_STATES_FIELD_NUMBER: _ClassVar[int]
    ARC_DEMAND_DIGEST_FIELD_NUMBER: _ClassVar[int]
    WARMUP_STATES_FIELD_NUMBER: _ClassVar[int]
    ARC_RETRIGGER_COUNTS_FIELD_NUMBER: _ClassVar[int]
    CONSECUTIVE_SKIP_COUNT_FIELD_NUMBER: _ClassVar[int]
    cooldown_until: _timestamp_pb2.Timestamp
    trigger_queue: _containers.RepeatedCompositeFieldContainer[QueuedTrigger]
    arc_watch_states: _containers.RepeatedCompositeFieldContainer[ArcWatchState]
    arc_demand_digest: ArcDemandDigest
    warmup_states: _containers.RepeatedCompositeFieldContainer[WarmupState]
    arc_retrigger_counts: _containers.RepeatedCompositeFieldContainer[RetriggerEntry]
    consecutive_skip_count: int
    def __init__(self, cooldown_until: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., trigger_queue: _Optional[_Iterable[_Union[QueuedTrigger, _Mapping]]] = ..., arc_watch_states: _Optional[_Iterable[_Union[ArcWatchState, _Mapping]]] = ..., arc_demand_digest: _Optional[_Union[ArcDemandDigest, _Mapping]] = ..., warmup_states: _Optional[_Iterable[_Union[WarmupState, _Mapping]]] = ..., arc_retrigger_counts: _Optional[_Iterable[_Union[RetriggerEntry, _Mapping]]] = ..., consecutive_skip_count: _Optional[int] = ...) -> None: ...

class ArcDemandDigest(_message.Message):
    __slots__ = ("entries",)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[ArcDemandDigestEntry]
    def __init__(self, entries: _Optional[_Iterable[_Union[ArcDemandDigestEntry, _Mapping]]] = ...) -> None: ...

class ArcDemandDigestEntry(_message.Message):
    __slots__ = ("edge_id", "demand")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    DEMAND_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    demand: float
    def __init__(self, edge_id: _Optional[str] = ..., demand: _Optional[float] = ...) -> None: ...

class QueuedTrigger(_message.Message):
    __slots__ = ("kind", "first_fired_at", "last_fired_at", "accumulated_score", "origin_edge_id", "origin_node_id", "snapshot_ref")
    KIND_FIELD_NUMBER: _ClassVar[int]
    FIRST_FIRED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_FIRED_AT_FIELD_NUMBER: _ClassVar[int]
    ACCUMULATED_SCORE_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_REF_FIELD_NUMBER: _ClassVar[int]
    kind: QueuedTriggerKind
    first_fired_at: _timestamp_pb2.Timestamp
    last_fired_at: _timestamp_pb2.Timestamp
    accumulated_score: float
    origin_edge_id: str
    origin_node_id: str
    snapshot_ref: str
    def __init__(self, kind: _Optional[_Union[QueuedTriggerKind, str]] = ..., first_fired_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_fired_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., accumulated_score: _Optional[float] = ..., origin_edge_id: _Optional[str] = ..., origin_node_id: _Optional[str] = ..., snapshot_ref: _Optional[str] = ...) -> None: ...

class ArcWatchState(_message.Message):
    __slots__ = ("edge_id", "percentile_breached", "delta_breached", "stagnation_watch_since", "surge_breached", "demand_excess_breached", "demand_watch_since")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    PERCENTILE_BREACHED_FIELD_NUMBER: _ClassVar[int]
    DELTA_BREACHED_FIELD_NUMBER: _ClassVar[int]
    STAGNATION_WATCH_SINCE_FIELD_NUMBER: _ClassVar[int]
    SURGE_BREACHED_FIELD_NUMBER: _ClassVar[int]
    DEMAND_EXCESS_BREACHED_FIELD_NUMBER: _ClassVar[int]
    DEMAND_WATCH_SINCE_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    percentile_breached: bool
    delta_breached: bool
    stagnation_watch_since: _timestamp_pb2.Timestamp
    surge_breached: bool
    demand_excess_breached: bool
    demand_watch_since: _timestamp_pb2.Timestamp
    def __init__(self, edge_id: _Optional[str] = ..., percentile_breached: bool = ..., delta_breached: bool = ..., stagnation_watch_since: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., surge_breached: bool = ..., demand_excess_breached: bool = ..., demand_watch_since: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class WarmupState(_message.Message):
    __slots__ = ("target_key", "until")
    TARGET_KEY_FIELD_NUMBER: _ClassVar[int]
    UNTIL_FIELD_NUMBER: _ClassVar[int]
    target_key: str
    until: _timestamp_pb2.Timestamp
    def __init__(self, target_key: _Optional[str] = ..., until: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RetriggerEntry(_message.Message):
    __slots__ = ("edge_id", "count", "quiet_cycles", "last_fired_at")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    QUIET_CYCLES_FIELD_NUMBER: _ClassVar[int]
    LAST_FIRED_AT_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    count: int
    quiet_cycles: int
    last_fired_at: _timestamp_pb2.Timestamp
    def __init__(self, edge_id: _Optional[str] = ..., count: _Optional[int] = ..., quiet_cycles: _Optional[int] = ..., last_fired_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Event(_message.Message):
    __slots__ = ("kind", "target_id", "occurred_at", "params")
    KIND_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    kind: EventKind
    target_id: str
    occurred_at: _timestamp_pb2.Timestamp
    params: ParamList
    def __init__(self, kind: _Optional[_Union[EventKind, str]] = ..., target_id: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., params: _Optional[_Union[ParamList, _Mapping]] = ...) -> None: ...

class ParamList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedCompositeFieldContainer[KeyValue]
    def __init__(self, values: _Optional[_Iterable[_Union[KeyValue, _Mapping]]] = ...) -> None: ...

class KeyValue(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: ScalarValue
    def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[ScalarValue, _Mapping]] = ...) -> None: ...

class ScalarValue(_message.Message):
    __slots__ = ("string_value", "double_value", "int_value", "bool_value", "null_value")
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    DOUBLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    INT_VALUE_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    NULL_VALUE_FIELD_NUMBER: _ClassVar[int]
    string_value: str
    double_value: float
    int_value: int
    bool_value: bool
    null_value: _empty_pb2.Empty
    def __init__(self, string_value: _Optional[str] = ..., double_value: _Optional[float] = ..., int_value: _Optional[int] = ..., bool_value: bool = ..., null_value: _Optional[_Union[_empty_pb2.Empty, _Mapping]] = ...) -> None: ...

class Reference(_message.Message):
    __slots__ = ("by_attribute_tag", "default_thresholds", "source_k_anonymity")
    BY_ATTRIBUTE_TAG_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_THRESHOLDS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_K_ANONYMITY_FIELD_NUMBER: _ClassVar[int]
    by_attribute_tag: _containers.RepeatedCompositeFieldContainer[TagReference]
    default_thresholds: ThresholdDefaults
    source_k_anonymity: int
    def __init__(self, by_attribute_tag: _Optional[_Iterable[_Union[TagReference, _Mapping]]] = ..., default_thresholds: _Optional[_Union[ThresholdDefaults, _Mapping]] = ..., source_k_anonymity: _Optional[int] = ...) -> None: ...

class TagReference(_message.Message):
    __slots__ = ("attribute_tag", "eta_typical", "baseline_stagnation", "capacity_typical", "sample_count")
    ATTRIBUTE_TAG_FIELD_NUMBER: _ClassVar[int]
    ETA_TYPICAL_FIELD_NUMBER: _ClassVar[int]
    BASELINE_STAGNATION_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_TYPICAL_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    attribute_tag: str
    eta_typical: float
    baseline_stagnation: float
    capacity_typical: float
    sample_count: int
    def __init__(self, attribute_tag: _Optional[str] = ..., eta_typical: _Optional[float] = ..., baseline_stagnation: _Optional[float] = ..., capacity_typical: _Optional[float] = ..., sample_count: _Optional[int] = ...) -> None: ...

class ThresholdDefaults(_message.Message):
    __slots__ = ("short_term", "long_term")
    SHORT_TERM_FIELD_NUMBER: _ClassVar[int]
    LONG_TERM_FIELD_NUMBER: _ClassVar[int]
    short_term: ThresholdSet
    long_term: ThresholdSet
    def __init__(self, short_term: _Optional[_Union[ThresholdSet, _Mapping]] = ..., long_term: _Optional[_Union[ThresholdSet, _Mapping]] = ...) -> None: ...

class ThresholdSet(_message.Message):
    __slots__ = ("surge_rate_threshold_percent_per_min", "high_stagnation_duration_min", "beta", "theta_demand", "warmup_duration_min")
    SURGE_RATE_THRESHOLD_PERCENT_PER_MIN_FIELD_NUMBER: _ClassVar[int]
    HIGH_STAGNATION_DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    BETA_FIELD_NUMBER: _ClassVar[int]
    THETA_DEMAND_FIELD_NUMBER: _ClassVar[int]
    WARMUP_DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    surge_rate_threshold_percent_per_min: float
    high_stagnation_duration_min: float
    beta: float
    theta_demand: float
    warmup_duration_min: float
    def __init__(self, surge_rate_threshold_percent_per_min: _Optional[float] = ..., high_stagnation_duration_min: _Optional[float] = ..., beta: _Optional[float] = ..., theta_demand: _Optional[float] = ..., warmup_duration_min: _Optional[float] = ...) -> None: ...

class ResolvedConfig(_message.Message):
    __slots__ = ("surge_rate_threshold_percent_per_min", "high_stagnation_duration_min", "beta", "theta_demand", "min_window_samples", "cooldown_duration_min", "warmup_duration_min", "retrigger_warning_threshold", "retrigger_reset_quiet_cycles", "queue_score_threshold", "queue_diversity_threshold", "queue_freshness_min", "throughput_target_edges", "optimization_mode", "local_radius_hops", "max_trigger_zones", "greedy_improve_margin", "restriction_proposal_enabled", "tau_danger_threshold", "puncture_trigger_enabled", "puncture_ratio_threshold", "forecasting_budget_sec", "detour_budget_sec", "lightweight_opt_budget_sec", "milp_time_limit_sec", "max_consecutive_skips", "solver_seed", "epsilon", "epsilon_0", "big_m_factor", "delta_min", "confidence_weight_floor", "mip_rel_gap", "gravity_alpha", "ipf_max_iter", "ipf_tolerance", "transit_time_prior_sec", "dwell_time_prior_sec", "min_reference_sample_count", "k_shortest_paths", "fallback_eta", "fallback_baseline_stagnation", "scalar_direction_enabled", "k_shortest_paths_auto", "k_shortest_paths_max", "phase_feedback_enabled", "phase_feedback_candidates", "attribute_tag_priority", "full_weight_hours", "eta_mixing_ratio", "throughput_weights", "throughput_max_per_edge", "two_stage_optimization", "backoff_enabled", "improvement_threshold", "backoff_max_factor", "shadow_extensions", "delta_objective_enabled", "node_detour_enabled", "milp_boundary_control_enabled", "scheduled_inflow_prior_enabled", "log_tenant_id")
    SURGE_RATE_THRESHOLD_PERCENT_PER_MIN_FIELD_NUMBER: _ClassVar[int]
    HIGH_STAGNATION_DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    BETA_FIELD_NUMBER: _ClassVar[int]
    THETA_DEMAND_FIELD_NUMBER: _ClassVar[int]
    MIN_WINDOW_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    COOLDOWN_DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    WARMUP_DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    RETRIGGER_WARNING_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    RETRIGGER_RESET_QUIET_CYCLES_FIELD_NUMBER: _ClassVar[int]
    QUEUE_SCORE_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    QUEUE_DIVERSITY_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    QUEUE_FRESHNESS_MIN_FIELD_NUMBER: _ClassVar[int]
    THROUGHPUT_TARGET_EDGES_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZATION_MODE_FIELD_NUMBER: _ClassVar[int]
    LOCAL_RADIUS_HOPS_FIELD_NUMBER: _ClassVar[int]
    MAX_TRIGGER_ZONES_FIELD_NUMBER: _ClassVar[int]
    GREEDY_IMPROVE_MARGIN_FIELD_NUMBER: _ClassVar[int]
    RESTRICTION_PROPOSAL_ENABLED_FIELD_NUMBER: _ClassVar[int]
    TAU_DANGER_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    PUNCTURE_TRIGGER_ENABLED_FIELD_NUMBER: _ClassVar[int]
    PUNCTURE_RATIO_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    FORECASTING_BUDGET_SEC_FIELD_NUMBER: _ClassVar[int]
    DETOUR_BUDGET_SEC_FIELD_NUMBER: _ClassVar[int]
    LIGHTWEIGHT_OPT_BUDGET_SEC_FIELD_NUMBER: _ClassVar[int]
    MILP_TIME_LIMIT_SEC_FIELD_NUMBER: _ClassVar[int]
    MAX_CONSECUTIVE_SKIPS_FIELD_NUMBER: _ClassVar[int]
    SOLVER_SEED_FIELD_NUMBER: _ClassVar[int]
    EPSILON_FIELD_NUMBER: _ClassVar[int]
    EPSILON_0_FIELD_NUMBER: _ClassVar[int]
    BIG_M_FACTOR_FIELD_NUMBER: _ClassVar[int]
    DELTA_MIN_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_WEIGHT_FLOOR_FIELD_NUMBER: _ClassVar[int]
    MIP_REL_GAP_FIELD_NUMBER: _ClassVar[int]
    GRAVITY_ALPHA_FIELD_NUMBER: _ClassVar[int]
    IPF_MAX_ITER_FIELD_NUMBER: _ClassVar[int]
    IPF_TOLERANCE_FIELD_NUMBER: _ClassVar[int]
    TRANSIT_TIME_PRIOR_SEC_FIELD_NUMBER: _ClassVar[int]
    DWELL_TIME_PRIOR_SEC_FIELD_NUMBER: _ClassVar[int]
    MIN_REFERENCE_SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    K_SHORTEST_PATHS_FIELD_NUMBER: _ClassVar[int]
    FALLBACK_ETA_FIELD_NUMBER: _ClassVar[int]
    FALLBACK_BASELINE_STAGNATION_FIELD_NUMBER: _ClassVar[int]
    SCALAR_DIRECTION_ENABLED_FIELD_NUMBER: _ClassVar[int]
    K_SHORTEST_PATHS_AUTO_FIELD_NUMBER: _ClassVar[int]
    K_SHORTEST_PATHS_MAX_FIELD_NUMBER: _ClassVar[int]
    PHASE_FEEDBACK_ENABLED_FIELD_NUMBER: _ClassVar[int]
    PHASE_FEEDBACK_CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTE_TAG_PRIORITY_FIELD_NUMBER: _ClassVar[int]
    FULL_WEIGHT_HOURS_FIELD_NUMBER: _ClassVar[int]
    ETA_MIXING_RATIO_FIELD_NUMBER: _ClassVar[int]
    THROUGHPUT_WEIGHTS_FIELD_NUMBER: _ClassVar[int]
    THROUGHPUT_MAX_PER_EDGE_FIELD_NUMBER: _ClassVar[int]
    TWO_STAGE_OPTIMIZATION_FIELD_NUMBER: _ClassVar[int]
    BACKOFF_ENABLED_FIELD_NUMBER: _ClassVar[int]
    IMPROVEMENT_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    BACKOFF_MAX_FACTOR_FIELD_NUMBER: _ClassVar[int]
    SHADOW_EXTENSIONS_FIELD_NUMBER: _ClassVar[int]
    DELTA_OBJECTIVE_ENABLED_FIELD_NUMBER: _ClassVar[int]
    NODE_DETOUR_ENABLED_FIELD_NUMBER: _ClassVar[int]
    MILP_BOUNDARY_CONTROL_ENABLED_FIELD_NUMBER: _ClassVar[int]
    SCHEDULED_INFLOW_PRIOR_ENABLED_FIELD_NUMBER: _ClassVar[int]
    LOG_TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    surge_rate_threshold_percent_per_min: float
    high_stagnation_duration_min: float
    beta: float
    theta_demand: float
    min_window_samples: int
    cooldown_duration_min: float
    warmup_duration_min: float
    retrigger_warning_threshold: int
    retrigger_reset_quiet_cycles: int
    queue_score_threshold: float
    queue_diversity_threshold: int
    queue_freshness_min: float
    throughput_target_edges: _containers.RepeatedScalarFieldContainer[str]
    optimization_mode: OptimizationMode
    local_radius_hops: int
    max_trigger_zones: int
    greedy_improve_margin: float
    restriction_proposal_enabled: bool
    tau_danger_threshold: float
    puncture_trigger_enabled: bool
    puncture_ratio_threshold: float
    forecasting_budget_sec: float
    detour_budget_sec: float
    lightweight_opt_budget_sec: float
    milp_time_limit_sec: float
    max_consecutive_skips: int
    solver_seed: int
    epsilon: float
    epsilon_0: float
    big_m_factor: float
    delta_min: float
    confidence_weight_floor: float
    mip_rel_gap: float
    gravity_alpha: float
    ipf_max_iter: int
    ipf_tolerance: float
    transit_time_prior_sec: float
    dwell_time_prior_sec: float
    min_reference_sample_count: int
    k_shortest_paths: int
    fallback_eta: float
    fallback_baseline_stagnation: float
    scalar_direction_enabled: bool
    k_shortest_paths_auto: bool
    k_shortest_paths_max: int
    phase_feedback_enabled: bool
    phase_feedback_candidates: int
    attribute_tag_priority: _containers.RepeatedScalarFieldContainer[str]
    full_weight_hours: float
    eta_mixing_ratio: float
    throughput_weights: ThroughputWeights
    throughput_max_per_edge: _containers.RepeatedCompositeFieldContainer[EdgeFloat]
    two_stage_optimization: bool
    backoff_enabled: bool
    improvement_threshold: float
    backoff_max_factor: int
    shadow_extensions: _containers.RepeatedScalarFieldContainer[str]
    delta_objective_enabled: bool
    node_detour_enabled: bool
    milp_boundary_control_enabled: bool
    scheduled_inflow_prior_enabled: bool
    log_tenant_id: bool
    def __init__(self, surge_rate_threshold_percent_per_min: _Optional[float] = ..., high_stagnation_duration_min: _Optional[float] = ..., beta: _Optional[float] = ..., theta_demand: _Optional[float] = ..., min_window_samples: _Optional[int] = ..., cooldown_duration_min: _Optional[float] = ..., warmup_duration_min: _Optional[float] = ..., retrigger_warning_threshold: _Optional[int] = ..., retrigger_reset_quiet_cycles: _Optional[int] = ..., queue_score_threshold: _Optional[float] = ..., queue_diversity_threshold: _Optional[int] = ..., queue_freshness_min: _Optional[float] = ..., throughput_target_edges: _Optional[_Iterable[str]] = ..., optimization_mode: _Optional[_Union[OptimizationMode, str]] = ..., local_radius_hops: _Optional[int] = ..., max_trigger_zones: _Optional[int] = ..., greedy_improve_margin: _Optional[float] = ..., restriction_proposal_enabled: bool = ..., tau_danger_threshold: _Optional[float] = ..., puncture_trigger_enabled: bool = ..., puncture_ratio_threshold: _Optional[float] = ..., forecasting_budget_sec: _Optional[float] = ..., detour_budget_sec: _Optional[float] = ..., lightweight_opt_budget_sec: _Optional[float] = ..., milp_time_limit_sec: _Optional[float] = ..., max_consecutive_skips: _Optional[int] = ..., solver_seed: _Optional[int] = ..., epsilon: _Optional[float] = ..., epsilon_0: _Optional[float] = ..., big_m_factor: _Optional[float] = ..., delta_min: _Optional[float] = ..., confidence_weight_floor: _Optional[float] = ..., mip_rel_gap: _Optional[float] = ..., gravity_alpha: _Optional[float] = ..., ipf_max_iter: _Optional[int] = ..., ipf_tolerance: _Optional[float] = ..., transit_time_prior_sec: _Optional[float] = ..., dwell_time_prior_sec: _Optional[float] = ..., min_reference_sample_count: _Optional[int] = ..., k_shortest_paths: _Optional[int] = ..., fallback_eta: _Optional[float] = ..., fallback_baseline_stagnation: _Optional[float] = ..., scalar_direction_enabled: bool = ..., k_shortest_paths_auto: bool = ..., k_shortest_paths_max: _Optional[int] = ..., phase_feedback_enabled: bool = ..., phase_feedback_candidates: _Optional[int] = ..., attribute_tag_priority: _Optional[_Iterable[str]] = ..., full_weight_hours: _Optional[float] = ..., eta_mixing_ratio: _Optional[float] = ..., throughput_weights: _Optional[_Union[ThroughputWeights, _Mapping]] = ..., throughput_max_per_edge: _Optional[_Iterable[_Union[EdgeFloat, _Mapping]]] = ..., two_stage_optimization: bool = ..., backoff_enabled: bool = ..., improvement_threshold: _Optional[float] = ..., backoff_max_factor: _Optional[int] = ..., shadow_extensions: _Optional[_Iterable[str]] = ..., delta_objective_enabled: bool = ..., node_detour_enabled: bool = ..., milp_boundary_control_enabled: bool = ..., scheduled_inflow_prior_enabled: bool = ..., log_tenant_id: bool = ...) -> None: ...

class ThroughputWeights(_message.Message):
    __slots__ = ("trigger_origin", "detour_path", "operator_set")
    TRIGGER_ORIGIN_FIELD_NUMBER: _ClassVar[int]
    DETOUR_PATH_FIELD_NUMBER: _ClassVar[int]
    OPERATOR_SET_FIELD_NUMBER: _ClassVar[int]
    trigger_origin: float
    detour_path: float
    operator_set: float
    def __init__(self, trigger_origin: _Optional[float] = ..., detour_path: _Optional[float] = ..., operator_set: _Optional[float] = ...) -> None: ...

class EdgeFloat(_message.Message):
    __slots__ = ("edge_id", "value")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    value: float
    def __init__(self, edge_id: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...

class OptimizationResult(_message.Message):
    __slots__ = ("route_importance", "direction_proposal", "restriction_proposal", "detour_paths", "boundary_control", "objective_values", "solver_status", "solved_at", "seed")
    ROUTE_IMPORTANCE_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_PROPOSAL_FIELD_NUMBER: _ClassVar[int]
    RESTRICTION_PROPOSAL_FIELD_NUMBER: _ClassVar[int]
    DETOUR_PATHS_FIELD_NUMBER: _ClassVar[int]
    BOUNDARY_CONTROL_FIELD_NUMBER: _ClassVar[int]
    OBJECTIVE_VALUES_FIELD_NUMBER: _ClassVar[int]
    SOLVER_STATUS_FIELD_NUMBER: _ClassVar[int]
    SOLVED_AT_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    route_importance: _containers.RepeatedCompositeFieldContainer[RouteImportance]
    direction_proposal: _containers.RepeatedCompositeFieldContainer[DirectionProposal]
    restriction_proposal: _containers.RepeatedCompositeFieldContainer[RestrictionProposal]
    detour_paths: _containers.RepeatedCompositeFieldContainer[DetourPathProposal]
    boundary_control: _containers.RepeatedCompositeFieldContainer[BoundaryControl]
    objective_values: OptimizationObjectiveValues
    solver_status: SolverStatus
    solved_at: _timestamp_pb2.Timestamp
    seed: int
    def __init__(self, route_importance: _Optional[_Iterable[_Union[RouteImportance, _Mapping]]] = ..., direction_proposal: _Optional[_Iterable[_Union[DirectionProposal, _Mapping]]] = ..., restriction_proposal: _Optional[_Iterable[_Union[RestrictionProposal, _Mapping]]] = ..., detour_paths: _Optional[_Iterable[_Union[DetourPathProposal, _Mapping]]] = ..., boundary_control: _Optional[_Iterable[_Union[BoundaryControl, _Mapping]]] = ..., objective_values: _Optional[_Union[OptimizationObjectiveValues, _Mapping]] = ..., solver_status: _Optional[_Union[SolverStatus, str]] = ..., solved_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., seed: _Optional[int] = ...) -> None: ...

class RouteImportance(_message.Message):
    __slots__ = ("edge_id", "direction", "importance", "valid_until_next_trigger")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    IMPORTANCE_FIELD_NUMBER: _ClassVar[int]
    VALID_UNTIL_NEXT_TRIGGER_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    direction: ImportanceDirection
    importance: float
    valid_until_next_trigger: bool
    def __init__(self, edge_id: _Optional[str] = ..., direction: _Optional[_Union[ImportanceDirection, str]] = ..., importance: _Optional[float] = ..., valid_until_next_trigger: bool = ...) -> None: ...

class DirectionProposal(_message.Message):
    __slots__ = ("edge_id", "proposed_direction", "confidence", "change_type")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    PROPOSED_DIRECTION_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    proposed_direction: ProposedDirection
    confidence: float
    change_type: DirectionChangeType
    def __init__(self, edge_id: _Optional[str] = ..., proposed_direction: _Optional[_Union[ProposedDirection, str]] = ..., confidence: _Optional[float] = ..., change_type: _Optional[_Union[DirectionChangeType, str]] = ...) -> None: ...

class RestrictionProposal(_message.Message):
    __slots__ = ("edge_id", "action", "limit_value", "reason", "confidence", "scope_note")
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    LIMIT_VALUE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    SCOPE_NOTE_FIELD_NUMBER: _ClassVar[int]
    edge_id: str
    action: RestrictionAction
    limit_value: float
    reason: RestrictionReason
    confidence: float
    scope_note: str
    def __init__(self, edge_id: _Optional[str] = ..., action: _Optional[_Union[RestrictionAction, str]] = ..., limit_value: _Optional[float] = ..., reason: _Optional[_Union[RestrictionReason, str]] = ..., confidence: _Optional[float] = ..., scope_note: _Optional[str] = ...) -> None: ...

class DetourPathProposal(_message.Message):
    __slots__ = ("origin_edge_id", "edge_ids", "confidence")
    ORIGIN_EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    EDGE_IDS_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    origin_edge_id: str
    edge_ids: _containers.RepeatedScalarFieldContainer[str]
    confidence: float
    def __init__(self, origin_edge_id: _Optional[str] = ..., edge_ids: _Optional[_Iterable[str]] = ..., confidence: _Optional[float] = ...) -> None: ...

class BoundaryControl(_message.Message):
    __slots__ = ("node_id", "action", "reason")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    action: BoundaryAction
    reason: str
    def __init__(self, node_id: _Optional[str] = ..., action: _Optional[_Union[BoundaryAction, str]] = ..., reason: _Optional[str] = ...) -> None: ...

class OptimizationObjectiveValues(_message.Message):
    __slots__ = ("tau_star", "throughput")
    TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    THROUGHPUT_FIELD_NUMBER: _ClassVar[int]
    tau_star: float
    throughput: float
    def __init__(self, tau_star: _Optional[float] = ..., throughput: _Optional[float] = ...) -> None: ...

class FeedbackValues(_message.Message):
    __slots__ = ("schema_version", "compute_meta", "objective_values", "per_tag_observations", "prediction_actual_diff", "reference_usage", "quality_metrics", "detour_metrics", "restriction_metrics", "direction_change_summary", "ab_diff", "forecast_summary", "warnings")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_META_FIELD_NUMBER: _ClassVar[int]
    OBJECTIVE_VALUES_FIELD_NUMBER: _ClassVar[int]
    PER_TAG_OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    PREDICTION_ACTUAL_DIFF_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_USAGE_FIELD_NUMBER: _ClassVar[int]
    QUALITY_METRICS_FIELD_NUMBER: _ClassVar[int]
    DETOUR_METRICS_FIELD_NUMBER: _ClassVar[int]
    RESTRICTION_METRICS_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_CHANGE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    AB_DIFF_FIELD_NUMBER: _ClassVar[int]
    FORECAST_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    compute_meta: ComputeMeta
    objective_values: FeedbackObjectiveValues
    per_tag_observations: _containers.RepeatedCompositeFieldContainer[TagObservation]
    prediction_actual_diff: PredictionActualDiff
    reference_usage: ReferenceUsageReport
    quality_metrics: QualityMetrics
    detour_metrics: DetourMetrics
    restriction_metrics: RestrictionMetrics
    direction_change_summary: DirectionChangeSummary
    ab_diff: AbDiff
    forecast_summary: ForecastSummary
    warnings: _containers.RepeatedCompositeFieldContainer[Warning]
    def __init__(self, schema_version: _Optional[str] = ..., compute_meta: _Optional[_Union[ComputeMeta, _Mapping]] = ..., objective_values: _Optional[_Union[FeedbackObjectiveValues, _Mapping]] = ..., per_tag_observations: _Optional[_Iterable[_Union[TagObservation, _Mapping]]] = ..., prediction_actual_diff: _Optional[_Union[PredictionActualDiff, _Mapping]] = ..., reference_usage: _Optional[_Union[ReferenceUsageReport, _Mapping]] = ..., quality_metrics: _Optional[_Union[QualityMetrics, _Mapping]] = ..., detour_metrics: _Optional[_Union[DetourMetrics, _Mapping]] = ..., restriction_metrics: _Optional[_Union[RestrictionMetrics, _Mapping]] = ..., direction_change_summary: _Optional[_Union[DirectionChangeSummary, _Mapping]] = ..., ab_diff: _Optional[_Union[AbDiff, _Mapping]] = ..., forecast_summary: _Optional[_Union[ForecastSummary, _Mapping]] = ..., warnings: _Optional[_Iterable[_Union[Warning, _Mapping]]] = ...) -> None: ...

class ComputeMeta(_message.Message):
    __slots__ = ("mode", "optimization_mode", "solver_phase1_ms", "solver_phase2_ms", "solver_phase1_status", "solver_phase2_status", "reachability_constraints")
    MODE_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZATION_MODE_FIELD_NUMBER: _ClassVar[int]
    SOLVER_PHASE1_MS_FIELD_NUMBER: _ClassVar[int]
    SOLVER_PHASE2_MS_FIELD_NUMBER: _ClassVar[int]
    SOLVER_PHASE1_STATUS_FIELD_NUMBER: _ClassVar[int]
    SOLVER_PHASE2_STATUS_FIELD_NUMBER: _ClassVar[int]
    REACHABILITY_CONSTRAINTS_FIELD_NUMBER: _ClassVar[int]
    mode: Mode
    optimization_mode: OptimizationMode
    solver_phase1_ms: int
    solver_phase2_ms: int
    solver_phase1_status: str
    solver_phase2_status: str
    reachability_constraints: ReachabilityConstraints
    def __init__(self, mode: _Optional[_Union[Mode, str]] = ..., optimization_mode: _Optional[_Union[OptimizationMode, str]] = ..., solver_phase1_ms: _Optional[int] = ..., solver_phase2_ms: _Optional[int] = ..., solver_phase1_status: _Optional[str] = ..., solver_phase2_status: _Optional[str] = ..., reachability_constraints: _Optional[_Union[ReachabilityConstraints, _Mapping]] = ...) -> None: ...

class ReachabilityConstraints(_message.Message):
    __slots__ = ("local", "boundary")
    LOCAL_FIELD_NUMBER: _ClassVar[int]
    BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    local: bool
    boundary: bool
    def __init__(self, local: bool = ..., boundary: bool = ...) -> None: ...

class FeedbackObjectiveValues(_message.Message):
    __slots__ = ("tau_star", "throughput")
    TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    THROUGHPUT_FIELD_NUMBER: _ClassVar[int]
    tau_star: float
    throughput: float
    def __init__(self, tau_star: _Optional[float] = ..., throughput: _Optional[float] = ...) -> None: ...

class TagObservation(_message.Message):
    __slots__ = ("attribute_tag", "eta_estimate", "edge_count", "observation_span_min")
    ATTRIBUTE_TAG_FIELD_NUMBER: _ClassVar[int]
    ETA_ESTIMATE_FIELD_NUMBER: _ClassVar[int]
    EDGE_COUNT_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_SPAN_MIN_FIELD_NUMBER: _ClassVar[int]
    attribute_tag: str
    eta_estimate: float
    edge_count: int
    observation_span_min: float
    def __init__(self, attribute_tag: _Optional[str] = ..., eta_estimate: _Optional[float] = ..., edge_count: _Optional[int] = ..., observation_span_min: _Optional[float] = ...) -> None: ...

class PredictionActualDiff(_message.Message):
    __slots__ = ("expected_tau_star", "actual_tau_star", "delta")
    EXPECTED_TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    DELTA_FIELD_NUMBER: _ClassVar[int]
    expected_tau_star: float
    actual_tau_star: float
    delta: float
    def __init__(self, expected_tau_star: _Optional[float] = ..., actual_tau_star: _Optional[float] = ..., delta: _Optional[float] = ...) -> None: ...

class ReferenceUsageReport(_message.Message):
    __slots__ = ("used_tags", "used_default", "used_edges_count")
    USED_TAGS_FIELD_NUMBER: _ClassVar[int]
    USED_DEFAULT_FIELD_NUMBER: _ClassVar[int]
    USED_EDGES_COUNT_FIELD_NUMBER: _ClassVar[int]
    used_tags: _containers.RepeatedScalarFieldContainer[str]
    used_default: bool
    used_edges_count: int
    def __init__(self, used_tags: _Optional[_Iterable[str]] = ..., used_default: bool = ..., used_edges_count: _Optional[int] = ...) -> None: ...

class QualityMetrics(_message.Message):
    __slots__ = ("vector_coverage_ratio", "low_confidence_arc_ratio", "history_completeness")
    VECTOR_COVERAGE_RATIO_FIELD_NUMBER: _ClassVar[int]
    LOW_CONFIDENCE_ARC_RATIO_FIELD_NUMBER: _ClassVar[int]
    HISTORY_COMPLETENESS_FIELD_NUMBER: _ClassVar[int]
    vector_coverage_ratio: float
    low_confidence_arc_ratio: float
    history_completeness: float
    def __init__(self, vector_coverage_ratio: _Optional[float] = ..., low_confidence_arc_ratio: _Optional[float] = ..., history_completeness: _Optional[float] = ...) -> None: ...

class DetourMetrics(_message.Message):
    __slots__ = ("k_requested", "k_effective", "paths_actually_used_ratio")
    K_REQUESTED_FIELD_NUMBER: _ClassVar[int]
    K_EFFECTIVE_FIELD_NUMBER: _ClassVar[int]
    PATHS_ACTUALLY_USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    k_requested: int
    k_effective: int
    paths_actually_used_ratio: float
    def __init__(self, k_requested: _Optional[int] = ..., k_effective: _Optional[int] = ..., paths_actually_used_ratio: _Optional[float] = ...) -> None: ...

class RestrictionMetrics(_message.Message):
    __slots__ = ("proposed_count", "by_reason", "estimated_inflow_cut", "undrainable_origin_ratio")
    PROPOSED_COUNT_FIELD_NUMBER: _ClassVar[int]
    BY_REASON_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_INFLOW_CUT_FIELD_NUMBER: _ClassVar[int]
    UNDRAINABLE_ORIGIN_RATIO_FIELD_NUMBER: _ClassVar[int]
    proposed_count: int
    by_reason: _containers.RepeatedCompositeFieldContainer[RestrictionCount]
    estimated_inflow_cut: float
    undrainable_origin_ratio: float
    def __init__(self, proposed_count: _Optional[int] = ..., by_reason: _Optional[_Iterable[_Union[RestrictionCount, _Mapping]]] = ..., estimated_inflow_cut: _Optional[float] = ..., undrainable_origin_ratio: _Optional[float] = ...) -> None: ...

class RestrictionCount(_message.Message):
    __slots__ = ("reason", "count")
    REASON_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    reason: RestrictionReason
    count: int
    def __init__(self, reason: _Optional[_Union[RestrictionReason, str]] = ..., count: _Optional[int] = ...) -> None: ...

class DirectionChangeSummary(_message.Message):
    __slots__ = ("convert", "release", "flip")
    CONVERT_FIELD_NUMBER: _ClassVar[int]
    RELEASE_FIELD_NUMBER: _ClassVar[int]
    FLIP_FIELD_NUMBER: _ClassVar[int]
    convert: int
    release: int
    flip: int
    def __init__(self, convert: _Optional[int] = ..., release: _Optional[int] = ..., flip: _Optional[int] = ...) -> None: ...

class AbDiff(_message.Message):
    __slots__ = ("enabled_extensions", "shadow_tau_star", "actual_tau_star", "shadow_throughput", "actual_throughput", "diff_summary")
    ENABLED_EXTENSIONS_FIELD_NUMBER: _ClassVar[int]
    SHADOW_TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_TAU_STAR_FIELD_NUMBER: _ClassVar[int]
    SHADOW_THROUGHPUT_FIELD_NUMBER: _ClassVar[int]
    ACTUAL_THROUGHPUT_FIELD_NUMBER: _ClassVar[int]
    DIFF_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    enabled_extensions: _containers.RepeatedScalarFieldContainer[str]
    shadow_tau_star: float
    actual_tau_star: float
    shadow_throughput: float
    actual_throughput: float
    diff_summary: str
    def __init__(self, enabled_extensions: _Optional[_Iterable[str]] = ..., shadow_tau_star: _Optional[float] = ..., actual_tau_star: _Optional[float] = ..., shadow_throughput: _Optional[float] = ..., actual_throughput: _Optional[float] = ..., diff_summary: _Optional[str] = ...) -> None: ...

class ForecastSummary(_message.Message):
    __slots__ = ("node_demand", "reproduction_error", "estimation_resolution")
    NODE_DEMAND_FIELD_NUMBER: _ClassVar[int]
    REPRODUCTION_ERROR_FIELD_NUMBER: _ClassVar[int]
    ESTIMATION_RESOLUTION_FIELD_NUMBER: _ClassVar[int]
    node_demand: _containers.RepeatedCompositeFieldContainer[NodeDemand]
    reproduction_error: float
    estimation_resolution: _containers.RepeatedCompositeFieldContainer[NodeResolution]
    def __init__(self, node_demand: _Optional[_Iterable[_Union[NodeDemand, _Mapping]]] = ..., reproduction_error: _Optional[float] = ..., estimation_resolution: _Optional[_Iterable[_Union[NodeResolution, _Mapping]]] = ...) -> None: ...

class NodeDemand(_message.Message):
    __slots__ = ("node_id", "gross_out", "gross_in", "production", "absorption", "transit", "staying")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    GROSS_OUT_FIELD_NUMBER: _ClassVar[int]
    GROSS_IN_FIELD_NUMBER: _ClassVar[int]
    PRODUCTION_FIELD_NUMBER: _ClassVar[int]
    ABSORPTION_FIELD_NUMBER: _ClassVar[int]
    TRANSIT_FIELD_NUMBER: _ClassVar[int]
    STAYING_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    gross_out: float
    gross_in: float
    production: float
    absorption: float
    transit: float
    staying: float
    def __init__(self, node_id: _Optional[str] = ..., gross_out: _Optional[float] = ..., gross_in: _Optional[float] = ..., production: _Optional[float] = ..., absorption: _Optional[float] = ..., transit: _Optional[float] = ..., staying: _Optional[float] = ...) -> None: ...

class NodeResolution(_message.Message):
    __slots__ = ("node_id", "mode", "reason", "imputed_arcs")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    IMPUTED_ARCS_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    mode: ODResolutionMode
    reason: ODResolutionReason
    imputed_arcs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, node_id: _Optional[str] = ..., mode: _Optional[_Union[ODResolutionMode, str]] = ..., reason: _Optional[_Union[ODResolutionReason, str]] = ..., imputed_arcs: _Optional[_Iterable[str]] = ...) -> None: ...

class Warning(_message.Message):
    __slots__ = ("code", "context")
    CODE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    code: WarningCode
    context: _containers.RepeatedCompositeFieldContainer[KeyValue]
    def __init__(self, code: _Optional[_Union[WarningCode, str]] = ..., context: _Optional[_Iterable[_Union[KeyValue, _Mapping]]] = ...) -> None: ...

class Diagnostics(_message.Message):
    __slots__ = ("mode", "warnings", "trigger_evidences", "fallbacks_applied", "steps_executed", "degraded_short_tenant", "schema_version")
    MODE_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_EVIDENCES_FIELD_NUMBER: _ClassVar[int]
    FALLBACKS_APPLIED_FIELD_NUMBER: _ClassVar[int]
    STEPS_EXECUTED_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_SHORT_TENANT_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    mode: Mode
    warnings: _containers.RepeatedCompositeFieldContainer[Warning]
    trigger_evidences: _containers.RepeatedCompositeFieldContainer[TriggerEvidence]
    fallbacks_applied: _containers.RepeatedCompositeFieldContainer[FallbackRecord]
    steps_executed: _containers.RepeatedCompositeFieldContainer[StepRecord]
    degraded_short_tenant: bool
    schema_version: str
    def __init__(self, mode: _Optional[_Union[Mode, str]] = ..., warnings: _Optional[_Iterable[_Union[Warning, _Mapping]]] = ..., trigger_evidences: _Optional[_Iterable[_Union[TriggerEvidence, _Mapping]]] = ..., fallbacks_applied: _Optional[_Iterable[_Union[FallbackRecord, _Mapping]]] = ..., steps_executed: _Optional[_Iterable[_Union[StepRecord, _Mapping]]] = ..., degraded_short_tenant: bool = ..., schema_version: _Optional[str] = ...) -> None: ...

class TriggerEvidence(_message.Message):
    __slots__ = ("source", "occurred_at", "edge_id", "node_id", "metric_value", "threshold_value", "duration_min")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    EDGE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    METRIC_VALUE_FIELD_NUMBER: _ClassVar[int]
    THRESHOLD_VALUE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MIN_FIELD_NUMBER: _ClassVar[int]
    source: TriggerEvidenceSource
    occurred_at: _timestamp_pb2.Timestamp
    edge_id: str
    node_id: str
    metric_value: float
    threshold_value: float
    duration_min: float
    def __init__(self, source: _Optional[_Union[TriggerEvidenceSource, str]] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., edge_id: _Optional[str] = ..., node_id: _Optional[str] = ..., metric_value: _Optional[float] = ..., threshold_value: _Optional[float] = ..., duration_min: _Optional[float] = ...) -> None: ...

class FallbackRecord(_message.Message):
    __slots__ = ("kind", "reason", "affected_targets")
    KIND_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_TARGETS_FIELD_NUMBER: _ClassVar[int]
    kind: FallbackKind
    reason: str
    affected_targets: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, kind: _Optional[_Union[FallbackKind, str]] = ..., reason: _Optional[str] = ..., affected_targets: _Optional[_Iterable[str]] = ...) -> None: ...

class StepRecord(_message.Message):
    __slots__ = ("step", "elapsed_ms", "status", "note")
    STEP_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    step: StepKind
    elapsed_ms: int
    status: StepStatus
    note: str
    def __init__(self, step: _Optional[_Union[StepKind, str]] = ..., elapsed_ms: _Optional[int] = ..., status: _Optional[_Union[StepStatus, str]] = ..., note: _Optional[str] = ...) -> None: ...
