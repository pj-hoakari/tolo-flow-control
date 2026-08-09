"""Tests for the puncture trigger (前処理 P)

パンクトリガーテスト

パンクはスカラー型エッジの前処理として独立に発火する（組合せ発火とは別系統）。

条件:
  - ``config.puncture_trigger_enabled`` が True
  - エッジが SCALAR 型かつ ``capacity_hint`` 設定あり
  - ``σ_e（観測カウント）>= puncture_ratio_threshold * capacity_hint``

capacity_hint 未設定・enabled=False では発火しない（ノーハーム）。
"""

from datetime import datetime

import pytest

from flow_control.detection.config import ResolvedConfig
from flow_control.detection.diagnostics import PunctureEvidence
from flow_control.detection.state import DetectionState, QueuedTriggerKind
from flow_control.detection.triggers import detect_metric_triggers
from flow_control.domain import (
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
)
from flow_control.domain.history import HistoryDigest
from flow_control.domain.observations import ArcScalarFlow, Observations


def _scalar_graph(edge_id: EdgeID, *, capacity_hint: float | None) -> Graph:
    n1, n2 = NodeID("n1"), NodeID("n2")
    return Graph(
        nodes=(
            Node(node_id=n1, kind=NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(node_id=n2, kind=NodeKind.GOAL, is_boundary=False, enabled=True),
        ),
        edges=(
            Edge(
                edge_id=edge_id,
                endpoint_a=n1,
                endpoint_b=n2,
                direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
                current_direction=CurrentDirection.BIDIRECTIONAL,
                enabled=True,
                observation_type=ObservationType.SCALAR,
                capacity_hint=capacity_hint,
            ),
        ),
    )


def _run(
    *,
    graph: Graph,
    observations: Observations,
    config: ResolvedConfig,
    server_time: datetime,
):
    return detect_metric_triggers(
        graph=graph,
        observations=observations,
        history_digest=HistoryDigest(),
        previous_state=DetectionState(),
        server_time=server_time,
        config=config,
    )


def _puncture_config(*, enabled: bool = True, ratio: float = 1.0) -> ResolvedConfig:
    return ResolvedConfig(
        surge_rate_threshold_percent_per_min=10.0,
        puncture_trigger_enabled=enabled,
        puncture_ratio_threshold=ratio,
    )


def test_puncture_fires_when_count_reaches_threshold(
    base_time: datetime,
    edge_id: EdgeID,
):
    # capacity_hint=100, ratio=1.0 → 閾値 100。観測 150 >= 100 で発火
    graph = _scalar_graph(edge_id, capacity_hint=100.0)
    observations = Observations(
        observed_at=base_time,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=150.0),),
    )

    result = _run(
        graph=graph,
        observations=observations,
        config=_puncture_config(),
        server_time=base_time,
    )

    assert result.triggered_edges == (edge_id,)
    assert result.fired_triggers[0].kind == QueuedTriggerKind.PUNCTURE
    puncture = [e for e in result.evidences if isinstance(e, PunctureEvidence)]
    assert len(puncture) == 1
    assert puncture[0].observed_count == 150.0
    assert puncture[0].capacity_threshold == 100.0


@pytest.mark.parametrize(
    ("observed_count", "should_fire"),
    [
        (99.0, False),  # 閾値 100 未満
        (100.0, True),  # 閾値ちょうど（σ_e >= ρ·C_e）
    ],
)
def test_puncture_threshold_boundary(
    base_time: datetime,
    edge_id: EdgeID,
    observed_count: float,
    should_fire: bool,
):
    graph = _scalar_graph(edge_id, capacity_hint=100.0)
    observations = Observations(
        observed_at=base_time,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=observed_count),),
    )

    result = _run(
        graph=graph,
        observations=observations,
        config=_puncture_config(),
        server_time=base_time,
    )

    if should_fire:
        assert result.triggered_edges == (edge_id,)
    else:
        assert result.triggered_edges == ()


def test_puncture_does_not_fire_without_capacity_hint(
    base_time: datetime,
    edge_id: EdgeID,
):
    # capacity_hint 未設定 → 発火しない（ノーハーム）
    graph = _scalar_graph(edge_id, capacity_hint=None)
    observations = Observations(
        observed_at=base_time,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=9_999.0),),
    )

    result = _run(
        graph=graph,
        observations=observations,
        config=_puncture_config(),
        server_time=base_time,
    )

    assert result.triggered_edges == ()


def test_puncture_does_not_fire_when_disabled(
    base_time: datetime,
    edge_id: EdgeID,
):
    # puncture_trigger_enabled=False → 既定でパンクは発火しない
    graph = _scalar_graph(edge_id, capacity_hint=100.0)
    observations = Observations(
        observed_at=base_time,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=150.0),),
    )

    result = _run(
        graph=graph,
        observations=observations,
        config=_puncture_config(enabled=False),
        server_time=base_time,
    )

    assert result.triggered_edges == ()


def test_puncture_ignores_vector_edge(
    base_time: datetime,
    basic_graph: Graph,
    edge_id: EdgeID,
):
    # VECTOR 型エッジはパンク対象外（capacity_hint を渡してもスカラー前処理は走らない）
    observations = Observations(
        observed_at=base_time,
        arc_scalar_flows=(ArcScalarFlow(edge_id=edge_id, observed_count=9_999.0),),
    )

    result = _run(
        graph=basic_graph,
        observations=observations,
        config=_puncture_config(),
        server_time=base_time,
    )

    assert result.triggered_edges == ()
