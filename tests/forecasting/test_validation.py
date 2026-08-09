"""``validate_od``（Step C: 整合・検証）のテスト"""

from datetime import UTC, datetime

import pytest

from flow_control.domain import (
    ArcFlow,
    ConfidenceFlag,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    FlowDirection,
    Graph,
    HistoryDigest,
    Node,
    NodeID,
    NodeKind,
    NodeOccupancy,
    Observations,
    ObservationType,
    Reference,
)
from flow_control.forecasting import forecast
from flow_control.forecasting.config import ResolvedConfig
from flow_control.forecasting.od import ODDemand
from flow_control.forecasting.validation import validate_od

_OBSERVED_AT = datetime(2026, 6, 1, tzinfo=UTC)


def _node(node_id: str, kind: NodeKind = NodeKind.GOAL, *, boundary: bool = False) -> Node:
    return Node(node_id=NodeID(node_id), kind=kind, is_boundary=boundary, enabled=True)


def _edge(edge_id: str, a: str, b: str) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=ObservationType.VECTOR,
    )


def _flow(edge_id: str, rate: float, *, flag: ConfidenceFlag = ConfidenceFlag.OK) -> ArcFlow:
    return ArcFlow(
        edge_id=EdgeID(edge_id),
        direction=FlowDirection.A_TO_B,
        flow_rate=rate,
        confidence_flag=flag,
    )


def _od(origin: str, dest: str, demand: float) -> ODDemand:
    return ODDemand(origin=NodeID(origin), destination=NodeID(dest), demand=demand)


def _config() -> ResolvedConfig:
    return ResolvedConfig(min_reference_sample_count=5, fallback_eta=1.0)


def _confidence_of(result, node_id: str) -> float:
    for nc in result.node_confidence:
        if nc.node_id == NodeID(node_id):
            return nc.confidence
    raise AssertionError(f"node_confidence for {node_id} not found")


def test_perfect_reproduction_gives_zero_error_and_full_confidence() -> None:
    """OD が観測リンク流量を完全再現すれば残差 0・信頼度 1.0

    s -e1=10-> m -e2=10-> t に対し OD(s->t)=10 を実測配分で伝播 → 各アーク再現一致
    """
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t", NodeKind.GOAL),
        ),
        edges=(_edge("e1", "s", "m"), _edge("e2", "m", "t")),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0), _flow("e2", 10.0)),
    )

    result = validate_od(graph, observations, (_od("s", "t", 10.0),), (), _config())

    assert result.reproduction_error == pytest.approx(0.0)
    assert _confidence_of(result, "s") == pytest.approx(1.0)
    assert _confidence_of(result, "m") == pytest.approx(1.0)
    assert _confidence_of(result, "t") == pytest.approx(1.0)


def test_reproduction_mismatch_lowers_confidence() -> None:
    """OD が観測を過小再現すると相対残差が増え信頼度が下がる

    観測 e1(s->t)=10 に対し OD(s->t)=4 → 残差 ≈ 6/10 = 0.6, base ≈ 0.4
    """
    graph = Graph(
        nodes=(_node("s", NodeKind.TRANSIT_ONLY), _node("t", NodeKind.GOAL)),
        edges=(_edge("e1", "s", "t"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0),),
    )

    result = validate_od(graph, observations, (_od("s", "t", 4.0),), (), _config())

    assert result.reproduction_error == pytest.approx(0.6, abs=1e-3)
    assert _confidence_of(result, "s") == pytest.approx(0.4, abs=1e-3)


def test_hold_flag_attenuates_confidence() -> None:
    """HOLD アークの両端ノードは信頼度 0.7 倍"""
    graph = Graph(
        nodes=(_node("s", NodeKind.TRANSIT_ONLY), _node("t", NodeKind.GOAL)),
        edges=(_edge("e1", "s", "t"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0, flag=ConfidenceFlag.HOLD),),
    )

    result = validate_od(graph, observations, (_od("s", "t", 10.0),), (), _config())

    # HOLD でも再現は一致（残差 0, base=1.0）→ 0.7 倍が効く
    assert result.reproduction_error == pytest.approx(0.0)
    assert _confidence_of(result, "s") == pytest.approx(0.7)
    assert _confidence_of(result, "t") == pytest.approx(0.7)


def test_invalid_flag_zeroes_confidence() -> None:
    """INVALID アークの両端ノードは信頼度 0.0"""
    graph = Graph(
        nodes=(_node("s", NodeKind.TRANSIT_ONLY), _node("t", NodeKind.GOAL)),
        edges=(_edge("e1", "s", "t"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0, flag=ConfidenceFlag.INVALID),),
    )

    result = validate_od(graph, observations, (), (), _config())

    assert _confidence_of(result, "s") == pytest.approx(0.0)
    assert _confidence_of(result, "t") == pytest.approx(0.0)


def test_missing_observation_halves_confidence() -> None:
    """観測欠損の有効ベクトルアークはカバレッジ減衰（0.5）にとどめる

    欠損は保存補完・prior の間接推定が受け皿となるため INVALID（0.0）と同一視しない
    """
    graph = Graph(
        nodes=(_node("s", NodeKind.TRANSIT_ONLY), _node("t", NodeKind.GOAL)),
        edges=(_edge("e1", "s", "t"),),
    )
    observations = Observations(observed_at=_OBSERVED_AT)

    result = validate_od(graph, observations, (), (), _config())

    assert _confidence_of(result, "s") == pytest.approx(0.5)
    assert _confidence_of(result, "t") == pytest.approx(0.5)


def test_partial_coverage_grades_confidence() -> None:
    """観測済み・欠損が混在するノードはカバレッジ比で段階的に減衰する

    m は e1（観測あり・再現一致）と e2（欠損）に接続 → coverage = (1 + 0.5)/2
    """
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t", NodeKind.GOAL),
        ),
        edges=(_edge("e1", "s", "m"), _edge("e2", "m", "t")),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0),),
    )

    result = validate_od(graph, observations, (_od("s", "m", 10.0),), (), _config())

    assert _confidence_of(result, "s") == pytest.approx(1.0)
    assert _confidence_of(result, "m") == pytest.approx(0.75)


def test_unreachable_od_row_shows_up_as_residual() -> None:
    """観測で運びきれない OD 行和は残差として現れる（計算は破綻しない）

    OD 行和 15 が観測 10 の e1 に流し込まれ |15-10|/10 = 0.5
    """
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY),
            _node("t", NodeKind.GOAL),
            _node("u", NodeKind.GOAL),  # 孤立（s,t と非連結）
        ),
        edges=(_edge("e1", "s", "t"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0),),
    )

    result = validate_od(
        graph, observations, (_od("s", "t", 10.0), _od("s", "u", 5.0)), (), _config()
    )

    assert result.reproduction_error == pytest.approx(0.5, abs=1e-3)


def test_forecast_populates_validation_outputs() -> None:
    """forecast 経由で reproduction_error と node_confidence が出力される

    s(境界生成) -e1=10-> B(MIXED, ΔOcc=6) -e2=4-> C(GOAL)（前方伝播で完全再現）
    """
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("B", NodeKind.GOAL_TRANSIT_MIXED),
            _node("C", NodeKind.GOAL),
        ),
        edges=(_edge("e1", "s", "B"), _edge("e2", "B", "C")),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0), _flow("e2", 4.0)),
        node_occupancies=(NodeOccupancy(node_id=NodeID("B"), occupancy=20.0, occupancy_delta=6.0),),
    )

    result = forecast(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        references=Reference(),
        triggered_edges=(),
        config=_config(),
    )

    assert result.reproduction_error == pytest.approx(0.0)
    assert _confidence_of(result, "s") == pytest.approx(1.0)
    assert _confidence_of(result, "C") == pytest.approx(1.0)
