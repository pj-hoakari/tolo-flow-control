"""``compute_node_demand``（Step A: 点需要分解）のテスト"""

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
    Node,
    NodeID,
    NodeKind,
    NodeOccupancy,
    Observations,
    ObservationType,
)
from flow_control.forecasting.config import ResolvedConfig
from flow_control.forecasting.demand import (
    NodeDemand,
    compute_node_demand,
    compute_node_demand_result,
)


@pytest.fixture
def observed_at() -> datetime:
    return datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


def _node(
    node_id: str,
    *,
    kind: NodeKind = NodeKind.GOAL,
    enabled: bool = True,
) -> Node:
    return Node(
        node_id=NodeID(node_id),
        kind=kind,
        is_boundary=False,
        enabled=enabled,
    )


def _edge(
    edge_id: str,
    a: str,
    b: str,
    *,
    enabled: bool = True,
    observation_type: ObservationType = ObservationType.VECTOR,
) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID(a),
        endpoint_b=NodeID(b),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=enabled,
        observation_type=observation_type,
    )


def _flow(
    edge_id: str,
    direction: FlowDirection,
    rate: float,
    *,
    flag: ConfidenceFlag = ConfidenceFlag.OK,
) -> ArcFlow:
    return ArcFlow(
        edge_id=EdgeID(edge_id),
        direction=direction,
        flow_rate=rate,
        confidence_flag=flag,
    )


def _config(
    *,
    transit_time_prior_sec: float | None = None,
    dwell_time_prior_sec: float | None = None,
) -> ResolvedConfig:
    return ResolvedConfig(
        min_reference_sample_count=5,
        fallback_eta=1.0,
        transit_time_prior_sec=transit_time_prior_sec,
        dwell_time_prior_sec=dwell_time_prior_sec,
    )


def _demand_of(demands: tuple[NodeDemand, ...], node_id: str) -> NodeDemand:
    for demand in demands:
        if demand.node_id == NodeID(node_id):
            return demand
    raise AssertionError(f"node {node_id} not found in demands")


# ── 粗流出・粗流入（相殺しない） ──


def test_single_edge_a_to_b(observed_at: datetime) -> None:
    """A_TO_B: endpoint_a が粗流出 P_v，endpoint_b が粗流入 A_v"""
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e1", "n1", "n2"),))
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 4.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    n1 = _demand_of(demands, "n1")
    n2 = _demand_of(demands, "n2")
    assert (n1.gross_out, n1.gross_in) == (4.0, 0.0)
    assert (n2.gross_out, n2.gross_in) == (0.0, 4.0)


def test_single_edge_b_to_a(observed_at: datetime) -> None:
    """B_TO_A: 流出元・流入先が反転する"""
    graph = Graph(nodes=(_node("n1"), _node("n2")), edges=(_edge("e1", "n1", "n2"),))
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.B_TO_A, 3.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    assert _demand_of(demands, "n2").gross_out == 3.0
    assert _demand_of(demands, "n1").gross_in == 3.0


def test_scalar_edge_excluded(observed_at: datetime) -> None:
    """スカラー型アークは Step A の集計対象外（保存補完にも使わない）"""
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", "n1", "n2", observation_type=ObservationType.SCALAR),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 9.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    assert all(d.gross_out == 0.0 and d.gross_in == 0.0 for d in demands)


def test_hold_included(observed_at: datetime) -> None:
    """HOLD は全量寄与する"""
    graph = Graph(
        nodes=(_node("n2"), _node("n3")),
        edges=(_edge("e2", "n2", "n3"),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e2", FlowDirection.A_TO_B, 7.0, flag=ConfidenceFlag.HOLD),),
    )

    demands = compute_node_demand(graph, observations, _config())

    assert _demand_of(demands, "n2").gross_out == 7.0
    assert _demand_of(demands, "n3").gross_in == 7.0


def test_invalid_contributes_nothing(observed_at: datetime) -> None:
    """INVALID は需要寄与なし（単独アークは残差 0 で保存補完しても 0）"""
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", "n1", "n2"),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 5.0, flag=ConfidenceFlag.INVALID),),
    )

    demands = compute_node_demand(graph, observations, _config())

    assert all(d.gross_out == 0.0 and d.gross_in == 0.0 for d in demands)


def test_disabled_edge_excluded(observed_at: datetime) -> None:
    """無効エッジの観測は無視（保存補完の隣接にも含めない）"""
    graph = Graph(
        nodes=(_node("n1"), _node("n2")),
        edges=(_edge("e1", "n1", "n2", enabled=False),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 5.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    assert all(d.gross_out == 0.0 and d.gross_in == 0.0 for d in demands)


def test_aggregation_at_shared_node(observed_at: datetime) -> None:
    """中心ノードで複数アークの流入・流出が相殺されず合算される（Y 型）

    e1: nc->n1 (A_TO_B, 2.0), e2: nc->n2 (A_TO_B, 3.0) → nc は粗流出 5.0
    e3: nc->n3 を B_TO_A 4.0 で nc へ流入 → nc は粗流入 4.0（ネットに潰さない）
    """
    graph = Graph(
        nodes=(_node("nc"), _node("n1"), _node("n2"), _node("n3")),
        edges=(
            _edge("e1", "nc", "n1"),
            _edge("e2", "nc", "n2"),
            _edge("e3", "nc", "n3"),
        ),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(
            _flow("e1", FlowDirection.A_TO_B, 2.0),
            _flow("e2", FlowDirection.A_TO_B, 3.0),
            _flow("e3", FlowDirection.B_TO_A, 4.0),
        ),
    )

    demands = compute_node_demand(graph, observations, _config())

    nc = _demand_of(demands, "nc")
    assert nc.gross_out == 5.0
    assert nc.gross_in == 4.0


def test_disabled_node_excluded_and_ordering(observed_at: datetime) -> None:
    """無効ノードは結果に含まれず，順序は enabled_nodes() の順に従う"""
    graph = Graph(
        nodes=(_node("n1"), _node("n2", enabled=False), _node("n3")),
        edges=(_edge("e1", "n1", "n3"),),
    )
    observations = Observations(observed_at=observed_at)

    demands = compute_node_demand(graph, observations, _config())

    assert tuple(d.node_id for d in demands) == (NodeID("n1"), NodeID("n3"))


# ── 滞在需要 stay_v（Node.kind 分岐） ──


def test_transit_only_no_staying(observed_at: datetime) -> None:
    """TRANSIT_ONLY は滞在 0・全量通過，内部ノードでは生成 0

    a->m=10, m->b=10 → m は P=10,A=10。stay=0, trans=10, prod=0, absorb=0
    """
    graph = Graph(
        nodes=(
            _node("a"),
            _node("m", kind=NodeKind.TRANSIT_ONLY),
            _node("b"),
        ),
        edges=(_edge("e1", "a", "m"), _edge("e2", "m", "b")),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(
            _flow("e1", FlowDirection.A_TO_B, 10.0),
            _flow("e2", FlowDirection.A_TO_B, 10.0),
        ),
    )

    m = _demand_of(compute_node_demand(graph, observations, _config()), "m")
    assert m.staying == 0.0
    assert m.transit == 10.0
    assert m.production == 0.0
    assert m.absorption == 0.0


def test_goal_all_arrivals_terminate_with_regeneration(observed_at: datetime) -> None:
    """GOAL は全到着が終端。流出があれば再生成として prod に計上

    a->g=10, g->b=4 → g は P=4,A=10。stay=A=10, trans=0, prod=max(0,4-10+10)=4, absorb=10
    """
    graph = Graph(
        nodes=(_node("a"), _node("g", kind=NodeKind.GOAL), _node("b")),
        edges=(_edge("e1", "a", "g"), _edge("e2", "g", "b")),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(
            _flow("e1", FlowDirection.A_TO_B, 10.0),
            _flow("e2", FlowDirection.A_TO_B, 4.0),
        ),
    )

    g = _demand_of(compute_node_demand(graph, observations, _config()), "g")
    assert g.staying == 10.0
    assert g.transit == 0.0
    assert g.production == 4.0
    assert g.absorption == 10.0


def test_mixed_accumulation_uses_occupancy_delta(observed_at: datetime) -> None:
    """GOAL_TRANSIT_MIXED 蓄積フェーズ: stay = max(0, ΔOcc)（通過と分離）

    a->v=10, v->b=6, ΔOcc=3 → stay=3, trans=7, prod=max(0,6-10+3)=0, absorb=3
    """
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED), _node("b")),
        edges=(_edge("e1", "a", "v"), _edge("e2", "v", "b")),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(
            _flow("e1", FlowDirection.A_TO_B, 10.0),
            _flow("e2", FlowDirection.A_TO_B, 6.0),
        ),
        node_occupancies=(NodeOccupancy(node_id=NodeID("v"), occupancy=20.0, occupancy_delta=3.0),),
    )

    v = _demand_of(compute_node_demand(graph, observations, _config()), "v")
    assert v.staying == 3.0
    assert v.transit == 7.0
    assert v.production == 0.0
    assert v.absorption == 3.0


def test_mixed_steady_uses_littles_law(observed_at: datetime) -> None:
    """GOAL_TRANSIT_MIXED 定常フェーズ（ΔOcc=0）: リトルの法則で滞在を復元

    a->v=10, ΔOcc=0, O_v=60, τ_pass=2, W_dwell=10
    stay = max(0, (60 - 10*2)/(10-2)) = 5
    """
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED)),
        edges=(_edge("e1", "a", "v"),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 10.0),),
        node_occupancies=(
            NodeOccupancy(
                node_id=NodeID("v"),
                occupancy=60.0,
                occupancy_delta=0.0,
                same_sensor_arrival=True,
            ),
        ),
    )
    config = _config(transit_time_prior_sec=2.0, dwell_time_prior_sec=10.0)

    v = _demand_of(compute_node_demand(graph, observations, config), "v")
    assert v.staying == pytest.approx(5.0)
    assert v.transit == pytest.approx(5.0)
    assert v.absorption == pytest.approx(5.0)


def test_mixed_steady_skips_littles_law_without_shared_sensor(
    observed_at: datetime,
) -> None:
    """リトル型復元は到着率と占有が同一センサー由来のときだけ適用する。"""
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED)),
        edges=(_edge("e1", "a", "v"),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 10.0),),
        node_occupancies=(NodeOccupancy(node_id=NodeID("v"), occupancy=60.0, occupancy_delta=0.0),),
    )

    v = _demand_of(
        compute_node_demand(
            graph,
            observations,
            _config(transit_time_prior_sec=2.0, dwell_time_prior_sec=10.0),
        ),
        "v",
    )
    assert v.staying == 0.0


def test_mixed_without_signal_degrades_to_zero(observed_at: datetime) -> None:
    """GOAL_TRANSIT_MIXED で占有も prior も無ければ滞在 0 に縮退（通過扱い）"""
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED)),
        edges=(_edge("e1", "a", "v"),),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 10.0),),
    )

    v = _demand_of(compute_node_demand(graph, observations, _config()), "v")
    assert v.staying == 0.0
    assert v.transit == 10.0


def test_mixed_occupancy_only_drives_demand(observed_at: datetime) -> None:
    """流量観測が無く占有変化のみでも ΔOcc がそのまま生成・吸収となる

    arc_flows 無し・v は GOAL_TRANSIT_MIXED で ΔOcc=8 → A_v=0, stay=8
    prod=max(0,0-0+8)=8, absorb=8（Step B の距離 prior 階層へ供給される）
    """
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED)),
        edges=(_edge("e1", "a", "v"),),
    )
    observations = Observations(
        observed_at=observed_at,
        node_occupancies=(NodeOccupancy(node_id=NodeID("v"), occupancy=8.0, occupancy_delta=8.0),),
    )

    v = _demand_of(compute_node_demand(graph, observations, _config()), "v")
    assert v.gross_in == 0.0
    assert v.staying == 8.0
    assert v.production == 8.0
    assert v.absorption == 8.0


# ── 単一未観測アークの保存補完 ──


def test_conservation_imputes_single_unobserved_outflow(observed_at: datetime) -> None:
    """通過ノードの単一未観測流出を保存則で復元

    line a - m(TRANSIT_ONLY) - c。観測は e1(a->m=10)のみ，e2(m-c)は未観測，ΔOcc=0
    残差 A-P-ΔOcc = 10>0 → e2 は m からの流出 10 と確定 → c へ 10 流入
    """
    graph = Graph(
        nodes=(_node("a"), _node("m", kind=NodeKind.TRANSIT_ONLY), _node("c")),
        edges=(_edge("e1", "a", "m"), _edge("e2", "m", "c")),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 10.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    m = _demand_of(demands, "m")
    c = _demand_of(demands, "c")
    assert m.gross_out == 10.0  # 未観測流出を復元
    assert m.transit == 10.0
    assert c.gross_in == 10.0  # 復元した流量が c へ伝播

    result = compute_node_demand_result(graph, observations, _config())
    assert result.imputed_arcs == (EdgeID("e2"),)


def test_conservation_accounts_for_occupancy_delta(observed_at: datetime) -> None:
    """保存補完は ΔOcc 分を差し引いて未観測流量を復元する

    a->v=10, e2(v-c) 未観測, v は GOAL_TRANSIT_MIXED で ΔOcc=4
    残差 10-0-4 = 6 → e2 流出 6, c へ 6 流入。v は stay=4, trans=6
    """
    graph = Graph(
        nodes=(_node("a"), _node("v", kind=NodeKind.GOAL_TRANSIT_MIXED), _node("c")),
        edges=(_edge("e1", "a", "v"), _edge("e2", "v", "c")),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e1", FlowDirection.A_TO_B, 10.0),),
        node_occupancies=(NodeOccupancy(node_id=NodeID("v"), occupancy=10.0, occupancy_delta=4.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    v = _demand_of(demands, "v")
    c = _demand_of(demands, "c")
    assert v.gross_out == pytest.approx(6.0)
    assert v.staying == pytest.approx(4.0)
    assert v.transit == pytest.approx(6.0)
    assert c.gross_in == pytest.approx(6.0)


def test_conservation_propagates_through_observed_frontier(
    observed_at: datetime,
) -> None:
    """観測フロンティアを持つ中間ノードから内側へ補完が伝播する

    line x - a(TRANSIT_ONLY) - g(TRANSIT_ONLY) - b。観測は e0(x->a=7), e2(g->b=7)。
    a は e0 観測・e1 未観測の 1 本のみ → 残差 7>0 で e1=7（a→g 流出）を復元 → g へ流入 7
    （x は単独観測アークで未観測 0 本，葉が 0 で先取りする縮退を避ける構成）
    """
    graph = Graph(
        nodes=(
            _node("x"),
            _node("a", kind=NodeKind.TRANSIT_ONLY),
            _node("g", kind=NodeKind.TRANSIT_ONLY),
            _node("b"),
        ),
        edges=(
            _edge("e0", "x", "a"),
            _edge("e1", "a", "g"),
            _edge("e2", "g", "b"),
        ),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(
            _flow("e0", FlowDirection.A_TO_B, 7.0),
            _flow("e2", FlowDirection.A_TO_B, 7.0),
        ),
    )

    demands = compute_node_demand(graph, observations, _config())

    a = _demand_of(demands, "a")
    g = _demand_of(demands, "g")
    assert a.gross_out == 7.0  # 未観測の a->g を復元
    assert g.gross_in == 7.0  # 復元した流量が g へ伝播
    assert g.transit == 7.0  # 通過として整合


def test_conservation_skips_when_two_unobserved(observed_at: datetime) -> None:
    """未観測アークが 2 本以上あるノードは劣決定として補完しない

    star: c(中心) と a,b,d。観測は e_a(a->c=10)のみ。
    c は e_b, e_d の 2 本が未観測 → 補完されず gross_in=10 のまま
    """
    graph = Graph(
        nodes=(
            _node("c", kind=NodeKind.TRANSIT_ONLY),
            _node("a"),
            _node("b"),
            _node("d"),
        ),
        edges=(
            _edge("e_a", "a", "c"),
            _edge("e_b", "c", "b"),
            _edge("e_d", "c", "d"),
        ),
    )
    observations = Observations(
        observed_at=observed_at,
        arc_flows=(_flow("e_a", FlowDirection.A_TO_B, 10.0),),
    )

    demands = compute_node_demand(graph, observations, _config())

    c = _demand_of(demands, "c")
    assert c.gross_in == 10.0
    assert c.gross_out == 0.0  # 2 本未観測 → 流出は復元されない
    assert _demand_of(demands, "b").gross_in == 0.0
    assert _demand_of(demands, "d").gross_in == 0.0
