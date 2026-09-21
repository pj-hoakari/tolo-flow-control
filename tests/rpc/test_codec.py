import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from google.protobuf import json_format

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
    NodeKind,
    ObservationType,
)
from flow_control.domain.graph import Edge, EdgeID, Graph, Node, NodeID
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import ArcFlow, Observations
from flow_control.domain.references import Reference
from flow_control.optimization.results import (
    BoundaryAction,
    BoundaryControl,
    DetourPathProposal,
    DirectionChangeType,
    DirectionProposal,
    ImportanceDirection,
    ObjectiveValues,
    OptimizationResult,
    ProposedDirection,
    RestrictionAction,
    RestrictionProposal,
    RestrictionReason,
    RouteImportance,
    SolverStatus,
)
from flow_control.rpc import codec
from flow_control.rpc.generated.tolo.flow.v1 import flow_pb2 as pb
from flow_control.service import (
    Diagnostics,
    FeedbackValues,
    QualityMetrics,
    Request,
    ResolvedConfig,
    Response,
    TenantContext,
    Verdict,
    handle_request,
)
from flow_control.service import ObjectiveValues as FeedbackObjectiveValues


def test_graph_round_trip_preserves_optional_values() -> None:
    graph = Graph(
        nodes=(
            Node(
                node_id=NodeID("n1"),
                kind=NodeKind.GOAL,
                is_boundary=True,
                enabled=True,
                attribute_tags=("main",),
                danger_capacity=12.5,
            ),
        ),
        edges=(
            Edge(
                edge_id=EdgeID("e1"),
                endpoint_a=NodeID("n1"),
                endpoint_b=NodeID("n2"),
                direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
                current_direction=CurrentDirection.A_TO_B,
                enabled=True,
                observation_type=ObservationType.VECTOR,
                capacity_hint=40.0,
            ),
        ),
    )

    encoded = codec._encode_graph(graph)

    assert encoded.nodes[0].HasField("danger_capacity")
    assert encoded.edges[0].HasField("capacity_hint")
    assert codec._decode_graph(encoded) == graph


def test_event_round_trip_preserves_scalar_kinds() -> None:
    event = Event(
        kind=EventKind.SCHEDULED_INFLOW,
        target_id="edge:e1",
        occurred_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        params=(("count", 3), ("enabled", True), ("ratio", 1.5), ("label", "x"), ("none", None)),
    )

    encoded = codec._encode_event(event)

    assert codec._decode_event(encoded) == event


def test_detection_state_round_trip_preserves_missing_vs_empty_digest() -> None:
    missing = codec._decode_detection_state(codec._encode_detection_state(DetectionState()))
    empty = codec._decode_detection_state(
        codec._encode_detection_state(DetectionState(arc_demand_digest=()))
    )

    assert missing.arc_demand_digest is None
    assert empty.arc_demand_digest == ()


def test_codec_rejects_missing_and_nonfinite_values() -> None:
    with pytest.raises(ValueError, match="missing node_id"):
        _ = codec._decode_node(pb.Node())
    with pytest.raises(ValueError, match=r"non-finite scalar\.double_value"):
        _ = codec._encode_scalar(math.nan)


def test_request_round_trip_uses_explicit_event_id() -> None:
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    graph = Graph(
        nodes=(
            Node(NodeID("n1"), NodeKind.GOAL, True, True),
            Node(NodeID("n2"), NodeKind.TRANSIT_ONLY, False, True),
        ),
        edges=(
            Edge(
                EdgeID("e1"),
                NodeID("n1"),
                NodeID("n2"),
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                CurrentDirection.A_TO_B,
                True,
                ObservationType.VECTOR,
            ),
        ),
    )
    previous_result = OptimizationResult(
        route_importance=(
            RouteImportance(EdgeID("e1"), ImportanceDirection.A_TO_B, importance=0.0),
        ),
        objective_values=ObjectiveValues(tau_star=0.0, throughput=None),
        solver_status=SolverStatus.TIMEOUT,
    )
    base = Request(
        request_id="r1",
        tenant_context=TenantContext(tenant_id="t1"),
        graph=graph,
        observations=Observations(observed_at=now),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=now,
        previous_result=previous_result,
        events=(
            Event(
                kind=EventKind.SCHEDULED_INFLOW,
                target_id="edge:e1",
                occurred_at=now,
                params=(("expected_count", 0),),
            ),
        ),
    )

    for state in (DetectionState(), DetectionState(arc_demand_digest=())):
        request = replace(base, detection_state=state)
        encoded = codec.encode_request(request, event_id="event-1")
        binary = pb.OptimizeRequest()
        _ = binary.ParseFromString(encoded.SerializeToString())
        json_wire = pb.OptimizeRequest()
        _ = json_format.Parse(json_format.MessageToJson(encoded), json_wire)

        assert encoded.event_id == "event-1"
        assert encoded.detection_state.HasField("arc_demand_digest") is (
            state.arc_demand_digest is not None
        )
        assert codec.decode_request(binary) == request
        assert codec.decode_request(json_wire) == request


@pytest.mark.parametrize("verdict", tuple(Verdict))
def test_response_round_trip_preserves_all_verdicts(verdict: Verdict) -> None:
    response = Response(
        request_id="r1",
        verdict=verdict,
        updated_detection_state=DetectionState(),
        optimization_result=OptimizationResult(solver_status=SolverStatus.TIMEOUT),
    )

    encoded = codec.encode_response(response)

    assert codec.decode_response(encoded) == response


def test_response_round_trip_preserves_nondefault_feedback_and_diagnostics() -> None:
    response = Response(
        request_id="r1",
        verdict=Verdict.OPTIMIZED,
        updated_detection_state=DetectionState(arc_demand_digest=()),
        feedback_values=replace(
            FeedbackValues(),
            objective_values=FeedbackObjectiveValues(tau_star=0.0, throughput=None),
            quality_metrics=QualityMetrics(
                vector_coverage_ratio=1.0,
                low_confidence_arc_ratio=0.25,
                history_completeness=0.5,
            ),
        ),
        diagnostics=replace(Diagnostics(), degraded_short_tenant=True),
    )

    assert codec.decode_response(codec.encode_response(response)) == response


def test_public_codec_rejects_missing_unknown_nan_and_bad_reference() -> None:
    with pytest.raises(ValueError, match="missing event_id"):
        _ = codec.decode_request(pb.OptimizeRequest())

    response = Response(
        request_id="r1",
        verdict=Verdict.SKIPPED_NO_TRIGGER,
        updated_detection_state=DetectionState(),
    )
    unknown = codec.encode_response(response)
    _ = unknown.ParseFromString(unknown.SerializeToString() + b"\x10\x63")
    with pytest.raises(ValueError, match="unknown verdict"):
        _ = codec.decode_response(unknown)

    nonfinite = codec.encode_response(response)
    nonfinite.feedback_values.quality_metrics.vector_coverage_ratio = math.nan
    with pytest.raises(ValueError, match=r"non-finite quality\.vector_coverage_ratio"):
        _ = codec.decode_response(nonfinite)

    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    invalid = Request(
        request_id="r1",
        tenant_context=TenantContext(tenant_id="t1"),
        graph=Graph(),
        observations=Observations(
            observed_at=now,
            arc_flows=(ArcFlow(EdgeID("missing"), FlowDirection.A_TO_B, 0.0),),
        ),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=now,
    )
    with pytest.raises(ValueError, match="unknown observation edge"):
        _ = codec.encode_request(invalid, event_id="event-1")


def _stale_detection_state(now: datetime) -> DetectionState:
    return DetectionState(
        cooldown_until=now + timedelta(minutes=10),
        trigger_queue=(
            QueuedTrigger(
                kind=QueuedTriggerKind.SURGE,
                first_fired_at=now - timedelta(minutes=5),
                last_fired_at=now,
                accumulated_score=2.5,
                origin_edge_id=EdgeID("gone"),
                origin_node_id=NodeID("n2"),
                snapshot_ref="snap-1",
            ),
            QueuedTrigger(
                kind=QueuedTriggerKind.DANGER,
                first_fired_at=now,
                last_fired_at=now,
                origin_node_id=NodeID("vanished"),
            ),
        ),
        arc_watch_states=(
            ArcWatchState(
                edge_id=EdgeID("gone"),
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=now - timedelta(minutes=3),
                surge_breached=True,
                demand_excess_breached=True,
                demand_watch_since=now - timedelta(minutes=2),
            ),
            ArcWatchState(edge_id=EdgeID("e1")),
        ),
        arc_demand_digest=(
            ArcDemandDigestEntry(edge_id=EdgeID("gone"), demand=4.0),
            ArcDemandDigestEntry(edge_id=EdgeID("e1"), demand=1.0),
        ),
        warmup_states=(
            WarmupState(target_key="edge:gone", until=now + timedelta(minutes=4)),
            WarmupState(target_key="node:vanished", until=now + timedelta(minutes=4)),
        ),
        arc_retrigger_counts=(
            RetriggerEntry(edge_id=EdgeID("gone"), count=3, quiet_cycles=1, last_fired_at=now),
            RetriggerEntry(edge_id=EdgeID("e1")),
        ),
        consecutive_skip_count=2,
    )


def _stale_previous_result(now: datetime) -> OptimizationResult:
    return OptimizationResult(
        route_importance=(
            RouteImportance(EdgeID("gone"), ImportanceDirection.B_TO_A, importance=0.5),
        ),
        direction_proposal=(
            DirectionProposal(
                EdgeID("gone"),
                ProposedDirection.A_TO_B,
                confidence=0.75,
                change_type=DirectionChangeType.FLIP_ONEWAY,
            ),
        ),
        restriction_proposal=(
            RestrictionProposal(
                EdgeID("gone"),
                RestrictionAction.LIMIT,
                limit_value=3.0,
                reason=RestrictionReason.PUNCTURE,
            ),
        ),
        detour_paths=(
            DetourPathProposal(EdgeID("gone"), (EdgeID("gone"), EdgeID("e1")), confidence=0.25),
        ),
        boundary_control=(
            BoundaryControl(NodeID("vanished"), BoundaryAction.PAUSE_INGRESS, reason="danger"),
        ),
        objective_values=ObjectiveValues(tau_star=1.25, throughput=2.0),
        solver_status=SolverStatus.FEASIBLE,
        solved_at=now,
        seed=7,
    )


def test_detection_state_and_previous_result_round_trip_all_collections() -> None:
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    state = _stale_detection_state(now)
    result = _stale_previous_result(now)

    assert codec._decode_detection_state(codec._encode_detection_state(state)) == state
    assert codec._decode_optimization_result(codec._encode_optimization_result(result)) == result


def test_request_round_trip_keeps_detection_state_of_removed_edges() -> None:
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    graph = Graph(
        nodes=(
            Node(NodeID("n1"), NodeKind.GOAL, True, True),
            Node(NodeID("n2"), NodeKind.TRANSIT_ONLY, False, True),
        ),
        edges=(
            Edge(
                EdgeID("e1"),
                NodeID("n1"),
                NodeID("n2"),
                DirectionConstraint.BIDIRECTIONAL_PRIOR,
                CurrentDirection.A_TO_B,
                True,
                ObservationType.VECTOR,
            ),
        ),
    )
    request = Request(
        request_id="r1",
        tenant_context=TenantContext(tenant_id="t1"),
        graph=graph,
        observations=Observations(
            observed_at=now,
            arc_flows=(ArcFlow(EdgeID("e1"), FlowDirection.A_TO_B, 1.0),),
        ),
        history_digest=HistoryDigest(),
        detection_state=_stale_detection_state(now),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=now,
        previous_result=_stale_previous_result(now),
    )

    decoded = codec.decode_request(codec.encode_request(request, event_id="event-1"))

    assert decoded == request
    assert handle_request(decoded).verdict is not Verdict.ERROR_INVALID_INPUT


def test_timestamps_normalize_to_utc_and_reject_naive() -> None:
    aware = Event(
        kind=EventKind.SCHEDULED_INFLOW,
        target_id="edge:e1",
        occurred_at=datetime(2026, 9, 21, 21, tzinfo=timezone(timedelta(hours=9))),
    )

    decoded = codec._decode_event(codec._encode_event(aware))

    assert decoded.occurred_at == datetime(2026, 9, 21, 12, tzinfo=UTC)
    assert decoded.occurred_at.utcoffset() == timedelta(0)
    naive = replace(aware, occurred_at=datetime(2026, 9, 21, 12))  # noqa: DTZ001
    with pytest.raises(ValueError, match=r"naive event\.occurred_at"):
        _ = codec._encode_event(naive)


def test_decode_rejects_unspecified_enum_values() -> None:
    with pytest.raises(ValueError, match="unknown node kind"):
        _ = codec._decode_node(pb.Node(node_id="n1", kind=pb.NODE_KIND_UNSPECIFIED))
    with pytest.raises(ValueError, match="unknown direction constraint"):
        _ = codec._decode_edge(
            pb.Edge(
                edge_id="e1",
                endpoint_a="n1",
                endpoint_b="n2",
                direction_constraint=pb.DIRECTION_CONSTRAINT_UNSPECIFIED,
            )
        )


def test_unknown_binary_field_survives_decode_but_protojson_rejects_it() -> None:
    response = Response(
        request_id="r1",
        verdict=Verdict.SKIPPED_NO_TRIGGER,
        updated_detection_state=DetectionState(),
    )
    encoded = codec.encode_response(response)
    wire = pb.OptimizeResponse()
    _ = wire.ParseFromString(encoded.SerializeToString() + b"\xc0\x3e\x01")

    assert codec.decode_response(wire) == response
    assert json_format.MessageToJson(wire) == json_format.MessageToJson(encoded)

    payload = '{"requestId": "r1", "mystery": 1}'
    with pytest.raises(json_format.ParseError):
        _ = json_format.Parse(payload, pb.OptimizeResponse())
    lenient = pb.OptimizeResponse()
    _ = json_format.Parse(payload, lenient, ignore_unknown_fields=True)
    assert lenient.request_id == "r1"
