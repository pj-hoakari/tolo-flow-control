from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from google.protobuf.timestamp_pb2 import Timestamp

from flow_control.domain import Boundary, BoundaryDirection, Graph, NodeKind
from flow_control.rpc.codec import decode_request, encode_response
from flow_control.rpc.generated.tolo.flow.v1 import flow_pb2 as pb
from flow_control.service.handler import (
    _detection_config,
    _detour_config,
    _forecast_config,
    _optimization_config,
    handle_request,
)

from .. import graph_builder
from ..scenario_base import DEFAULT_TIME, PipelineConfigs, Scenario, make_scenario

WINDOW = timedelta(minutes=1)
HISTORY_CYCLES = 30
HOT_EDGE = "e_j1_hallA"
SURGE_CYCLES = 17
SURGE_START = 10
THROUGH_FLOW = 5.0

_NODE_KINDS = {
    NodeKind.GOAL: pb.NODE_KIND_GOAL,
    NodeKind.GOAL_TRANSIT_MIXED: pb.NODE_KIND_GOAL_TRANSIT_MIXED,
    NodeKind.TRANSIT_ONLY: pb.NODE_KIND_TRANSIT_ONLY,
}
_BOUNDARY_DIRECTIONS = {
    BoundaryDirection.ENTRY: pb.BOUNDARY_DIRECTION_ENTRY,
    BoundaryDirection.EXIT: pb.BOUNDARY_DIRECTION_EXIT,
    BoundaryDirection.ENTRY_AND_EXIT: pb.BOUNDARY_DIRECTION_ENTRY_AND_EXIT,
}


def _boundary(boundary: Boundary | None) -> pb.Boundary | None:
    if boundary is None:
        return None
    return pb.Boundary(direction=_BOUNDARY_DIRECTIONS[boundary.direction], active=boundary.active)


@dataclass(frozen=True)
class RouteMeasurement:
    forward: float
    backward: float
    stagnation: float | None = None


@dataclass(frozen=True)
class Cycle:
    server_time: datetime
    routes: Mapping[str, RouteMeasurement]
    occupancy_delta: Mapping[str, float] = field(default_factory=dict)


def _timestamp(value: datetime) -> Timestamp:
    stamp = Timestamp()
    stamp.FromDatetime(value)
    return stamp


def _graph(graph: Graph) -> pb.Graph:
    resolution = int(WINDOW.total_seconds())
    return pb.Graph(
        nodes=[
            pb.Node(
                node_id=node.node_id.value,
                kind=_NODE_KINDS[node.kind],
                enabled=True,
                boundary=_boundary(node.boundary),
                time_resolution_s=resolution,
                danger_flag=False,
            )
            for node in graph.nodes
        ],
        edges=[
            pb.Edge(
                edge_id=edge.edge_id.value,
                endpoint_a=edge.endpoint_a.value,
                endpoint_b=edge.endpoint_b.value,
                direction_constraint=pb.DIRECTION_CONSTRAINT_BIDIRECTIONAL_PRIOR,
                current_direction=pb.CURRENT_DIRECTION_BIDIRECTIONAL,
                enabled=True,
                observation_type=pb.OBSERVATION_TYPE_VECTOR,
                time_resolution_s=resolution,
                danger_flag=False,
                capacity_hint=edge.capacity_hint,
            )
            for edge in graph.edges
        ],
    )


def _observations(cycle: Cycle, *, omit_zero_flows: bool) -> pb.Observations:
    ok = pb.CONFIDENCE_FLAG_OK
    observations = pb.Observations(
        observed_at=_timestamp(cycle.server_time), snapshot_ref=f"snap-{cycle.server_time:%H%M}"
    )
    for edge_id, measurement in sorted(cycle.routes.items()):
        observations.arc_flows.extend(
            pb.ArcFlow(edge_id=edge_id, direction=direction, flow_rate=rate, confidence_flag=ok)
            for direction, rate in (
                (pb.FLOW_DIRECTION_A_TO_B, measurement.forward),
                (pb.FLOW_DIRECTION_B_TO_A, measurement.backward),
            )
            if rate > 0 or not omit_zero_flows
        )
        if measurement.stagnation is not None:
            observations.arc_stagnations.append(
                pb.ArcStagnation(
                    edge_id=edge_id,
                    stagnation=measurement.stagnation,
                    derivation=pb.STAGNATION_DERIVATION_BASIC,
                    same_sensor_flow=False,
                    confidence_flag=ok,
                )
            )
    for node_id, delta in sorted(cycle.occupancy_delta.items()):
        observations.node_occupancies.append(
            pb.NodeOccupancy(
                node_id=node_id,
                occupancy=0.0,
                occupancy_delta=delta,
                same_sensor_arrival=False,
                confidence_flag=ok,
            )
        )
    return observations


def observation_config() -> pb.ResolvedConfig:
    return pb.ResolvedConfig(
        surge_rate_threshold_percent_per_min=50,
        high_stagnation_duration_min=5,
        beta=1,
        min_window_samples=5,
        cooldown_duration_min=60,
        warmup_duration_min=60,
        retrigger_warning_threshold=3,
        retrigger_reset_quiet_cycles=3,
        queue_score_threshold=5,
        queue_diversity_threshold=3,
        optimization_mode=pb.OPTIMIZATION_MODE_LIGHTWEIGHT,
        local_radius_hops=2,
        max_trigger_zones=4,
        greedy_improve_margin=0.05,
        restriction_proposal_enabled=False,
        puncture_trigger_enabled=False,
        puncture_ratio_threshold=1,
        forecasting_budget_sec=30,
        detour_budget_sec=30,
        lightweight_opt_budget_sec=120,
        milp_time_limit_sec=600,
        max_consecutive_skips=3,
        solver_seed=0,
        epsilon=1e-3,
        epsilon_0=1e-6,
        big_m_factor=1,
        delta_min=0.5,
        confidence_weight_floor=0.5,
        mip_rel_gap=0,
        gravity_alpha=1,
        ipf_max_iter=50,
        ipf_tolerance=1e-6,
        min_reference_sample_count=5,
        k_shortest_paths=3,
        fallback_eta=1,
        fallback_baseline_stagnation=1,
        scalar_direction_enabled=False,
        k_shortest_paths_auto=False,
        k_shortest_paths_max=3,
        phase_feedback_enabled=False,
        phase_feedback_candidates=0,
        full_weight_hours=0,
        eta_mixing_ratio=0,
        throughput_weights=pb.ThroughputWeights(trigger_origin=1, detour_path=1, operator_set=1),
        two_stage_optimization=False,
        backoff_enabled=False,
        improvement_threshold=0,
        backoff_max_factor=1,
        delta_objective_enabled=False,
        node_detour_enabled=False,
        milp_boundary_control_enabled=False,
        scheduled_inflow_prior_enabled=False,
        log_tenant_id=False,
    )


def _history(graph: Graph, past: Sequence[Cycle]) -> pb.HistoryDigest:
    digest = pb.HistoryDigest(completeness=1.0)
    for edge in graph.edges:
        edge_id = edge.edge_id.value
        series = pb.ArcWindowSeries(edge_id=edge_id)
        for cycle in past[-HISTORY_CYCLES:]:
            measurement = cycle.routes[edge_id]
            at = _timestamp(cycle.server_time)
            series.flow_samples.append(
                pb.TimedValue(at=at, value=measurement.forward + measurement.backward)
            )
            if measurement.stagnation is not None:
                series.stagnation_samples.append(pb.TimedValue(at=at, value=measurement.stagnation))
        digest.window_series.append(series)
    return digest


def observation_request(
    graph: Graph,
    cycle: Cycle,
    history: pb.HistoryDigest,
    config: pb.ResolvedConfig,
    detection_state: pb.DetectionState,
    previous_result: pb.OptimizationResult | None,
    *,
    omit_zero_flows: bool,
) -> pb.OptimizeRequest:
    request = pb.OptimizeRequest(
        request_id=f"req-{cycle.server_time:%H%M}",
        schema_version="request/1",
        event_id="evt-observation",
        tenant_context=pb.TenantContext(
            tenant_id="tenant-observation",
            tenant_category=pb.TENANT_CATEGORY_SHORT_TERM,
            available_history_hours=0,
        ),
        graph=_graph(graph),
        observations=_observations(cycle, omit_zero_flows=omit_zero_flows),
        history_digest=history,
        detection_state=detection_state,
        references=pb.Reference(),
        config=config,
        server_time=_timestamp(cycle.server_time),
    )
    if previous_result is not None:
        request.previous_result.CopyFrom(previous_result)
    return request


@dataclass(frozen=True)
class ObservationRun:
    cycles: Sequence[Cycle]
    send_history: bool
    config: pb.ResolvedConfig
    omit_zero_flows: bool

    def responses(self, graph: Graph) -> list[pb.OptimizeResponse]:
        state = pb.DetectionState()
        previous: pb.OptimizationResult | None = None
        responses: list[pb.OptimizeResponse] = []
        for index in range(len(self.cycles)):
            response = encode_response(
                handle_request(decode_request(self.request(graph, index, state, previous)))
            )
            responses.append(response)
            state = response.updated_detection_state
            previous = (
                response.optimization_result if response.HasField("optimization_result") else None
            )
        return responses

    def request(
        self,
        graph: Graph,
        index: int,
        state: pb.DetectionState,
        previous: pb.OptimizationResult | None,
    ) -> pb.OptimizeRequest:
        history = _history(graph, self.cycles[:index]) if self.send_history else pb.HistoryDigest()
        return observation_request(
            graph,
            self.cycles[index],
            history,
            self.config,
            state,
            previous,
            omit_zero_flows=self.omit_zero_flows,
        )


def surge_cycles(graph: Graph, *, with_stagnation: bool) -> list[Cycle]:
    cycles: list[Cycle] = []
    for index in range(SURGE_CYCLES):
        ramp = max(0, index - SURGE_START)
        hall_a = 10.0 * 1.4**ramp
        forward = {
            "e_in_j1": THROUGH_FLOW + hall_a,
            HOT_EDGE: hall_a,
            "e_j1_hallB": THROUGH_FLOW,
            "e_hallB_j2": THROUGH_FLOW,
            "e_j2_out": THROUGH_FLOW,
        }
        routes = {
            edge.edge_id.value: RouteMeasurement(
                forward=forward.get(edge.edge_id.value, 0.0),
                backward=0.0,
                stagnation=(
                    (1.0 + 2.0 * ramp if edge.edge_id.value == HOT_EDGE else 1.0)
                    if with_stagnation
                    else None
                ),
            )
            for edge in graph.edges
        }
        cycles.append(
            Cycle(
                server_time=DEFAULT_TIME - WINDOW * (SURGE_CYCLES - 1 - index),
                routes=routes,
                occupancy_delta={"hallA": hall_a, "hallB": 0.0},
            )
        )
    return cycles


def as_sent_run(graph: Graph) -> ObservationRun:
    return ObservationRun(
        cycles=surge_cycles(graph, with_stagnation=False),
        send_history=False,
        config=observation_config(),
        omit_zero_flows=False,
    )


def with_history_run(
    graph: Graph, *, surge_threshold: float = 10.0, omit_zero_flows: bool = True
) -> ObservationRun:
    config = observation_config()
    config.surge_rate_threshold_percent_per_min = surge_threshold
    return ObservationRun(
        cycles=surge_cycles(graph, with_stagnation=True),
        send_history=True,
        config=config,
        omit_zero_flows=omit_zero_flows,
    )


def to_scenario(
    name: str,
    description: str,
    built: graph_builder.BuiltGraph,
    run: ObservationRun,
    *,
    expect_trigger: bool,
) -> Scenario:
    graph = built.graph
    last = len(run.cycles) - 1
    earlier = replace(run, cycles=run.cycles[:last]).responses(graph)
    state = earlier[-1].updated_detection_state if earlier else pb.DetectionState()
    request = decode_request(run.request(graph, last, state, None))
    config = request.config
    return make_scenario(
        name,
        description,
        graph_builder.BuiltGraph(graph=request.graph, positions=built.positions),
        request.observations,
        request.history_digest,
        previous_state=request.detection_state,
        configs=PipelineConfigs(
            detection=_detection_config(config),
            forecasting=_forecast_config(config),
            detour=_detour_config(config),
            optimization=_optimization_config(config),
        ),
        references=request.references,
        server_time=request.server_time,
        expect_trigger=expect_trigger,
    )
