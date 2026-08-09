"""``forecast`` の統合テスト（観測 → Step A 点需要分解 → Step B OD 推定）"""

from datetime import UTC, datetime

import pytest

from flow_control.domain import (
    ArcFlow,
    ArcHistoryStat,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    FlowDirection,
    Graph,
    HistoryDigest,
    Mode,
    Node,
    NodeID,
    NodeKind,
    Observations,
    ObservationType,
    Reference,
)
from flow_control.forecasting import ODResolutionMode, forecast
from flow_control.forecasting.config import ResolvedConfig
from flow_control.forecasting.demand import NodeDemand


def _node(node_id: str, kind: NodeKind, *, boundary: bool = False) -> Node:
    return Node(node_id=NodeID(node_id), kind=kind, is_boundary=boundary, enabled=True)


def _vector_edge(edge_id: str, a: str, b: str) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _flow(edge_id: str, rate: float) -> ArcFlow:
    return ArcFlow(edge_id=EdgeID(edge_id), direction=FlowDirection.A_TO_B, flow_rate=rate)


def _config() -> ResolvedConfig:
    return ResolvedConfig(min_reference_sample_count=5, fallback_eta=1.0)


def _demand_of(demands: tuple[NodeDemand, ...], node_id: str) -> NodeDemand:
    for demand in demands:
        if demand.node_id == NodeID(node_id):
            return demand
    raise AssertionError(f"node {node_id} not found in node_demand")


def test_forecast_open_mode_decomposes_then_builds_od() -> None:
    """境界 entrance(生成) → 通過 mid → ゴール hall(吸収) のパイプライン

    e1: entrance->mid=10, e2: mid->hall=10
    Step A:
      entrance(境界/通過): P=10,A=0  → prod=10, absorb=0
      mid(通過):           P=10,A=10 → trans=10, prod=0, absorb=0
      hall(ゴール):         P=0, A=10 → stay=10, absorb=10, prod=0
    Step B: 生成源 entrance → 吸収 hall に全量 10 を配分（mid は通過のみで OD 非生成）
    """
    graph = Graph(
        nodes=(
            _node("entrance", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("mid", NodeKind.TRANSIT_ONLY),
            _node("hall", NodeKind.GOAL),
        ),
        edges=(
            _vector_edge("e1", "entrance", "mid"),
            _vector_edge("e2", "mid", "hall"),
        ),
    )
    observations = Observations(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        arc_flows=(_flow("e1", 10.0), _flow("e2", 10.0)),
    )

    result = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
    )

    entrance = _demand_of(result.node_demand, "entrance")
    mid = _demand_of(result.node_demand, "mid")
    hall = _demand_of(result.node_demand, "hall")
    assert (entrance.production, entrance.absorption) == (10.0, 0.0)
    assert (mid.transit, mid.production, mid.absorption) == (10.0, 0.0, 0.0)
    assert (hall.staying, hall.absorption, hall.production) == (10.0, 10.0, 0.0)

    assert len(result.od_matrix) == 1
    od = result.od_matrix[0]
    assert od.origin == NodeID("entrance")
    assert od.destination == NodeID("hall")
    assert od.demand == pytest.approx(10.0)


def test_forecast_closed_mode_decomposes_and_builds_od() -> None:
    """Closed モードでも Step A 点需要分解＋Step B OD 推定が行われる

    a(生成) -e1=5-> b(ゴール吸収)。境界が無く Closed モード，前方伝播で δ(a,b)=5
    """
    graph = Graph(
        nodes=(_node("a", NodeKind.GOAL), _node("b", NodeKind.GOAL)),
        edges=(_vector_edge("e1", "a", "b"),),
    )
    observations = Observations(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        arc_flows=(_flow("e1", 5.0),),
    )

    result = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
    )

    assert _demand_of(result.node_demand, "a").production == 5.0
    assert _demand_of(result.node_demand, "b").absorption == 5.0
    assert len(result.od_matrix) == 1
    od = result.od_matrix[0]
    assert (od.origin, od.destination) == (NodeID("a"), NodeID("b"))
    assert od.demand == pytest.approx(5.0)


def test_forecast_populates_full_schema() -> None:
    """4 段階（A 点需要・B OD・C 検証）＋ η_e が ForecastResult に揃う

    entrance -e1=10-> mid -e2=10-> hall（GOAL）の完全観測・決定可能チェーン
    e1 は履歴 η=0.4，e2 は履歴/参照なしで fallback
    """
    graph = Graph(
        nodes=(
            _node("entrance", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("mid", NodeKind.TRANSIT_ONLY),
            _node("hall", NodeKind.GOAL),
        ),
        edges=(
            _vector_edge("e1", "entrance", "mid"),
            _vector_edge("e2", "mid", "hall"),
        ),
    )
    observations = Observations(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        arc_flows=(_flow("e1", 10.0), _flow("e2", 10.0)),
    )
    history = HistoryDigest(
        arc_stats=(ArcHistoryStat(edge_id=EdgeID("e1"), flow_sensitivity_eta=0.4),)
    )

    result = forecast(
        graph=graph,
        observations=observations,
        history_digest=history,
        references=Reference(),
        triggered_edges=(EdgeID("e1"),),
        config=_config(),  # fallback_eta=1.0
    )

    # Step A: 点需要（全有効ノード）
    assert len(result.node_demand) == 3
    # Step B: OD（entrance→hall）と全ノードの解像度
    assert len(result.od_matrix) == 1
    assert result.od_matrix[0].origin == NodeID("entrance")
    assert result.od_matrix[0].destination == NodeID("hall")
    assert len(result.estimation_resolution) == 3
    assert all(r.mode == ODResolutionMode.TURNING_EXACT for r in result.estimation_resolution)
    # Step C: 再現残差 0・全ノード信頼度 1.0
    assert result.reproduction_error == pytest.approx(0.0)
    assert len(result.node_confidence) == 3
    assert all(nc.confidence == pytest.approx(1.0) for nc in result.node_confidence)
    # η_e: 履歴採用の e1 と fallback の e2
    etas = {s.edge_id: s.eta for s in result.arc_flow_sensitivity}
    assert etas[EdgeID("e1")] == pytest.approx(0.4)
    assert etas[EdgeID("e2")] == pytest.approx(1.0)
    assert EdgeID("e2") in result.fallback_usage.used_default_edges
    assert EdgeID("e1") not in result.fallback_usage.used_default_edges


def test_forecast_mode_none_matches_graph_derivation() -> None:
    # mode 未指定（None）とグラフ由来の OPEN が等価であることを確認
    graph = Graph(
        nodes=(
            _node("entrance", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("mid", NodeKind.TRANSIT_ONLY),
            _node("hall", NodeKind.GOAL),
        ),
        edges=(
            _vector_edge("e1", "entrance", "mid"),
            _vector_edge("e2", "mid", "hall"),
        ),
    )
    observations = Observations(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        arc_flows=(_flow("e1", 10.0), _flow("e2", 10.0)),
    )

    default = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
    )
    explicit_open = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
        mode=Mode.OPEN,
    )

    assert explicit_open.od_matrix == default.od_matrix


def test_forecast_mode_overrides_graph_derivation() -> None:
    # 境界→境界のみのグラフは graph 由来では OPEN（ext→ext 除外で OD 空）だが、
    # mode=CLOSED を渡すと除外されず OD が生成される（mode が導出を上書きする）
    graph = Graph(
        nodes=(
            _node("ent", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("ex", NodeKind.GOAL, boundary=True),
        ),
        edges=(_vector_edge("e1", "ent", "ex"),),
    )
    observations = Observations(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        arc_flows=(_flow("e1", 10.0),),
    )

    # OPEN（graph 由来の既定と一致）: ext→ext は除外され OD は空
    open_result = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
        mode=Mode.OPEN,
    )
    assert open_result.od_matrix == ()

    # CLOSED: ext→ext 除外なし → OD が生成される
    closed = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
        mode=Mode.CLOSED,
    )
    assert len(closed.od_matrix) >= 1
