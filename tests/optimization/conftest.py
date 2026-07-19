"""Optimization テスト用の共有フィクスチャ"""

from datetime import datetime, timezone

import pytest

from flow_control.detour_routing import DetourPath, DetourResult, DetourSet
from flow_control.domain import (
    ArcStagnation,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    HistoryDigest,
    ArcHistoryStat,
    Node,
    NodeID,
    NodeKind,
    Observations,
    ObservationType,
)
from flow_control.forecasting import ForecastResult, ODDemand
from flow_control.forecasting.sensitivity import ArcFlowSensitivity
from flow_control.forecasting.validation import NodeConfidence
from flow_control.optimization import OptimizationMode, ResolvedConfig


@pytest.fixture
def observed_at() -> datetime:
    return datetime(2026, 6, 18, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def config() -> ResolvedConfig:
    # 数理ワークド例は STRICT の基準系として検証する。
    return ResolvedConfig(optimization_mode=OptimizationMode.STRICT)


# 数理補助ドキュメント §27 の 3 ノード・3 エッジ Open モード手計算例
_N1, _N2, _N3 = NodeID("n1"), NodeID("n2"), NodeID("n3")
_E12, _E23, _E13 = EdgeID("e12"), EdgeID("e23"), EdgeID("e13")


def _edge(eid: EdgeID, a: NodeID, b: NodeID, obs=ObservationType.VECTOR) -> Edge:
    return Edge(
        edge_id=eid,
        endpoint_a=a,
        endpoint_b=b,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=True,
        observation_type=obs,
    )


@pytest.fixture
def worked_example_graph() -> Graph:
    return Graph(
        nodes=(
            Node(_N1, NodeKind.GOAL, is_boundary=True, enabled=True),
            Node(_N2, NodeKind.TRANSIT_ONLY, is_boundary=False, enabled=True),
            Node(_N3, NodeKind.GOAL, is_boundary=False, enabled=True),
        ),
        edges=(
            _edge(_E12, _N1, _N2),
            _edge(_E23, _N2, _N3),
            _edge(_E13, _N1, _N3),
        ),
    )


@pytest.fixture
def worked_example_observations(observed_at: datetime) -> Observations:
    return Observations(
        observed_at=observed_at,
        arc_stagnations=(
            ArcStagnation(_E12, 30.0),
            ArcStagnation(_E23, 6.0),
            ArcStagnation(_E13, 2.0),
        ),
    )


@pytest.fixture
def worked_example_history() -> HistoryDigest:
    return HistoryDigest(
        arc_stats=(
            ArcHistoryStat(_E12, baseline_stagnation=10.0),
            ArcHistoryStat(_E23, baseline_stagnation=8.0),
            ArcHistoryStat(_E13, baseline_stagnation=4.0),
        )
    )


@pytest.fixture
def worked_example_forecast() -> ForecastResult:
    return ForecastResult(
        od_matrix=(ODDemand(_N1, _N3, 12.0),),
        node_confidence=(
            NodeConfidence(_N1, 1.0),
            NodeConfidence(_N2, 1.0),
            NodeConfidence(_N3, 1.0),
        ),
        arc_flow_sensitivity=(
            ArcFlowSensitivity(_E12, 0.5),
            ArcFlowSensitivity(_E23, 0.4),
            ArcFlowSensitivity(_E13, 0.3),
        ),
    )


@pytest.fixture
def worked_example_detour() -> DetourResult:
    # 起点 e12 の迂回路: 直行 e12 ＋ n1→n3→n2（e13, e23）。P_trigger = {e12, e13, e23}
    return DetourResult(
        detour_sets=(
            DetourSet(
                origin_edge=_E12,
                endpoint_pair=(_N1, _N2),
                paths=(
                    DetourPath(edge_ids=(_E12,), total_length=1.0, contains_trigger=True),
                    DetourPath(
                        edge_ids=(_E13, _E23), total_length=2.0, contains_trigger=False
                    ),
                ),
                k_effective=1,
            ),
        )
    )
