"""Phase1 スキーマ基盤層の存在・整合を検証するスモークテスト。

サービス境界の I/O 契約・統一 ResolvedConfig と、設計改稿で追加したドメイン
フィールドが実装に反映されていることを確認する。
抽出・オーケストレーションのロジックは後続 Phase の対象で、ここでは扱わない。
"""

from datetime import datetime, timezone

from flow_control.detection.state import (
    ArcDemandDigestEntry,
    ArcWatchState,
    DetectionState,
    QueuedTriggerKind,
)
from flow_control.detection.triggers import Event, EventKind
from flow_control.domain.enums import FlowDirection
from flow_control.domain.graph import EdgeID, Graph, NodeID
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest
from flow_control.domain.observations import (
    ArcStagnation,
    NodeOccupancy,
    Observations,
    StagnationDerivation,
    TurningObservation,
)
from flow_control.domain.references import Reference, TagReference, ThresholdDefaults
from flow_control.service import (
    Diagnostics,
    FeedbackValues,
    OptimizationMode,
    Request,
    ResolvedConfig,
    Response,
    TenantCategory,
    TenantContext,
    Verdict,
)

_NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_verdict_has_eight_values() -> None:
    assert {v.value for v in Verdict} == {
        "optimized",
        "queued",
        "skipped_no_trigger",
        "skipped_cooldown",
        "skipped_warmup",
        "skipped_time",
        "error_size_exceeded",
        "error_invalid_input",
    }


def test_unified_config_defaults_are_noharm() -> None:
    cfg = ResolvedConfig()
    # 基本モード（軽量分解）が既定
    assert cfg.optimization_mode is OptimizationMode.LIGHTWEIGHT
    # 拡張ロードマップ連動フラグは既定で無効（現状動作と同一）
    assert cfg.restriction_proposal_enabled is False
    assert cfg.puncture_trigger_enabled is False
    assert cfg.two_stage_optimization is False
    # 需要超過判定は既定で無効（急増のみ）
    assert cfg.theta_demand is None
    # 主要フィールドが揃っている
    for name in (
        "beta",
        "theta_demand",
        "min_window_samples",
        "local_radius_hops",
        "tau_danger_threshold",
        "lightweight_opt_budget_sec",
        "k_shortest_paths",
        "gravity_alpha",
    ):
        assert name in ResolvedConfig.__dataclass_fields__


def test_request_response_construct() -> None:
    req = Request(
        request_id="r1",
        tenant_context=TenantContext(
            tenant_id="t1", tenant_category=TenantCategory.SHORT_TERM
        ),
        graph=Graph(),
        observations=Observations(observed_at=_NOW),
        history_digest=HistoryDigest(),
        detection_state=DetectionState(),
        references=Reference(),
        config=ResolvedConfig(),
        server_time=_NOW,
    )
    assert req.schema_version == "request/1"
    assert req.previous_result is None

    resp = Response(
        request_id="r1",
        verdict=Verdict.SKIPPED_NO_TRIGGER,
        updated_detection_state=DetectionState(),
    )
    assert resp.feedback_values.schema_version == "feedback/3"
    assert resp.diagnostics.schema_version == "diagnostics/2"
    assert isinstance(resp.feedback_values, FeedbackValues)
    assert isinstance(resp.diagnostics, Diagnostics)


def test_observations_new_fields() -> None:
    stag = ArcStagnation(
        EdgeID("e1"),
        10.0,
        derivation=StagnationDerivation.REFINED,
        same_sensor_flow=True,
    )
    assert stag.derivation is StagnationDerivation.REFINED
    assert stag.same_sensor_flow is True

    occ = NodeOccupancy(node_id=NodeID("v"), occupancy=5.0, same_sensor_arrival=True)
    assert occ.same_sensor_arrival is True

    turning = TurningObservation(
        node_id=NodeID("v"), from_edge_id=EdgeID("e1"), to_edge_id=EdgeID("e2"), ratio=0.6
    )
    obs = Observations(observed_at=_NOW, node_turning=(turning,))
    assert obs.node_turning[0].ratio == 0.6
    # 位置引数 2 個での旧来構築が壊れていないこと
    assert ArcStagnation(EdgeID("e2"), 3.0).derivation is StagnationDerivation.BASIC


def test_history_new_fields() -> None:
    stat = ArcHistoryStat(edge_id=EdgeID("e1"), available_span_hours=2.5)
    assert stat.available_span_hours == 2.5
    series = ArcWindowSeries(
        edge_id=EdgeID("e1"),
        directional_flow_samples=((FlowDirection.A_TO_B, ((_NOW, 1.0),)),),
    )
    assert series.directional_flow_samples is not None


def test_reference_new_fields() -> None:
    tag = TagReference(attribute_tag="wide", capacity_typical=120.0)
    assert tag.capacity_typical == 120.0
    ref = Reference(default_thresholds=ThresholdDefaults())
    assert ref.default_thresholds is not None


def test_detection_state_new_fields() -> None:
    assert QueuedTriggerKind.PUNCTURE.value == "PUNCTURE"
    watch = ArcWatchState(
        edge_id=EdgeID("e1"),
        stagnation_watch_since=_NOW,
        surge_breached=True,
        demand_excess_breached=True,
        demand_watch_since=_NOW,
    )
    assert watch.surge_breached is True
    assert watch.demand_watch_since == _NOW

    state = DetectionState(
        arc_demand_digest=(ArcDemandDigestEntry(edge_id=EdgeID("e1"), demand=4.2),)
    )
    assert state.demand_digest_of(EdgeID("e1")) == 4.2
    assert state.demand_digest_of(EdgeID("missing")) is None
    assert DetectionState().demand_digest_of(EdgeID("e1")) is None


def test_event_new_fields() -> None:
    assert EventKind.SENSOR_SET_CHANGED.value == "SENSOR_SET_CHANGED"
    ev = Event(
        kind=EventKind.SCHEDULED_INFLOW,
        target_id="edge:e1",
        occurred_at=_NOW,
        params=(("expected_count", 50),),
    )
    assert ev.params == (("expected_count", 50),)
    # params 省略時は None
    assert Event(kind=EventKind.ADD_EDGE, target_id="edge:e2", occurred_at=_NOW).params is None
