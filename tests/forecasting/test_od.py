"""``estimate_od``（Step B: OD 推定）のテスト

Step A（compute_node_demand）の出力を入力に，前方伝播（TURNING_EXACT）・
両制約 IPF（DOUBLY_CONSTRAINED）・距離 prior（DISTANCE_PRIOR）の各機構を検証
"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from flow_control.domain import (
    ArcFlow,
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
    TurningObservation,
)
from flow_control.forecasting.config import ResolvedConfig
from flow_control.forecasting.demand import compute_node_demand
from flow_control.forecasting.od import (
    ODDemand,
    ODResolutionMode,
    ODResolutionReason,
    estimate_od,
)

_OBSERVED_AT = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _node(
    node_id: str,
    kind: NodeKind = NodeKind.GOAL,
    *,
    boundary: bool = False,
) -> Node:
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


def _flow(edge_id: str, rate: float) -> ArcFlow:
    return ArcFlow(
        edge_id=EdgeID(edge_id), direction=FlowDirection.A_TO_B, flow_rate=rate
    )


def _occ(node_id: str, occupancy: float, delta: float) -> NodeOccupancy:
    return NodeOccupancy(
        node_id=NodeID(node_id), occupancy=occupancy, occupancy_delta=delta
    )


def _config(**overrides: float) -> ResolvedConfig:
    base = ResolvedConfig(min_reference_sample_count=5, fallback_eta=1.0)
    return replace(base, **overrides)


def _run(graph, observations, config, *, is_open_mode):
    node_demands = compute_node_demand(graph, observations, config)
    return estimate_od(
        graph, observations, node_demands, config, is_open_mode=is_open_mode
    )


def _find(ods: tuple[ODDemand, ...], origin: str, dest: str) -> ODDemand | None:
    for od in ods:
        if od.origin == NodeID(origin) and od.destination == NodeID(dest):
            return od
    return None


def _require(ods: tuple[ODDemand, ...], origin: str, dest: str) -> ODDemand:
    od = _find(ods, origin, dest)
    assert od is not None, f"OD ({origin} -> {dest}) not found in {ods}"
    return od


def _resolution(result, node_id: str):
    for res in result.resolutions:
        if res.node_id == NodeID(node_id):
            return res
    raise AssertionError(f"resolution for {node_id} not found")


def test_forward_propagation_separates_terminate_and_passthrough() -> None:
    """決定可能ネットワークで `A→B`（終端）と `A→（B→）C`（通過）を厳密分離

    s(境界生成) -e1-> B(MIXED, ΔOcc=6) -e2-> C(GOAL)
    e1=10, e2=4。B で滞在 6・通過 4 → δ(s,B)=6, δ(s,C)=4
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
        node_occupancies=(_occ("B", occupancy=20.0, delta=6.0),),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _require(result.od_matrix, "s", "B").demand == pytest.approx(6.0)
    assert _require(result.od_matrix, "s", "C").demand == pytest.approx(4.0)
    assert _resolution(result, "B").mode == ODResolutionMode.TURNING_EXACT
    assert _resolution(result, "B").reason == ODResolutionReason.DETERMINED


def test_forward_propagation_excludes_boundary_to_boundary() -> None:
    """Open モードの ext→ext（境界生成→境界吸収）は前方伝播後に除外"""
    graph = Graph(
        nodes=(
            _node("ent", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("ex", NodeKind.GOAL, boundary=True),
        ),
        edges=(_edge("e1", "ent", "ex"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0),),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert result.od_matrix == ()


def test_ipf_doubly_constrained_satisfies_both_marginals() -> None:
    """合流＋分岐ノードを含む場合は両制約 IPF で行・列周辺を同時に満たす

    s1,s2 -> m(合流+分岐) -> t1,t2。prod(s1)=6, prod(s2)=4, absorb(t1)=absorb(t2)=5
    等距離 prior → δ(s1,t1)=3, δ(s1,t2)=3, δ(s2,t1)=2, δ(s2,t2)=2
    """
    graph = Graph(
        nodes=(
            _node("s1", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("s2", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s1", "m"),
            _edge("e2", "s2", "m"),
            _edge("e3", "m", "t1"),
            _edge("e4", "m", "t2"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(
            _flow("e1", 6.0),
            _flow("e2", 4.0),
            _flow("e3", 5.0),
            _flow("e4", 5.0),
        ),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _require(result.od_matrix, "s1", "t1").demand == pytest.approx(3.0)
    assert _require(result.od_matrix, "s1", "t2").demand == pytest.approx(3.0)
    assert _require(result.od_matrix, "s2", "t1").demand == pytest.approx(2.0)
    assert _require(result.od_matrix, "s2", "t2").demand == pytest.approx(2.0)

    # 行周辺（生成）と列周辺（吸収）が同時に満たされる
    row_s1 = sum(od.demand for od in result.od_matrix if od.origin == NodeID("s1"))
    col_t1 = sum(od.demand for od in result.od_matrix if od.destination == NodeID("t1"))
    assert row_s1 == pytest.approx(6.0)
    assert col_t1 == pytest.approx(5.0)

    # 合流＋分岐の m は不定（追加観測の優先対象）
    assert _resolution(result, "m").mode == ODResolutionMode.DOUBLY_CONSTRAINED
    assert _resolution(result, "m").reason == ODResolutionReason.MERGE_SPLIT_AMBIGUOUS


def test_complete_external_turning_observation_enables_exact_propagation() -> None:
    """合流＋分岐でも入口別転換率が完全なら、IPF でなく前方伝播を用いる。"""
    graph = Graph(
        nodes=(
            _node("s1", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("s2", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s1", "m"),
            _edge("e2", "s2", "m"),
            _edge("e3", "m", "t1"),
            _edge("e4", "m", "t2"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(
            _flow("e1", 6.0),
            _flow("e2", 4.0),
            _flow("e3", 6.0),
            _flow("e4", 4.0),
        ),
        node_turning=(
            TurningObservation(NodeID("m"), EdgeID("e1"), EdgeID("e3"), 1.0),
            TurningObservation(NodeID("m"), EdgeID("e2"), EdgeID("e4"), 1.0),
        ),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _require(result.od_matrix, "s1", "t1").demand == pytest.approx(6.0)
    assert _require(result.od_matrix, "s2", "t2").demand == pytest.approx(4.0)
    assert _find(result.od_matrix, "s1", "t2") is None
    assert _resolution(result, "m").mode == ODResolutionMode.TURNING_EXACT


def test_sparse_observation_reason() -> None:
    """観測欠落の有効ベクトルアークを持つノードは SPARSE_OBSERVATION"""
    graph = Graph(
        nodes=(
            _node("s1", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("s2", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
            _node("t3", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s1", "m"),
            _edge("e2", "s2", "m"),
            _edge("e3", "m", "t1"),
            _edge("e4", "m", "t2"),
            _edge("e5", "m", "t3"),  # 観測なし → m は欠測あり
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(
            _flow("e1", 6.0),
            _flow("e2", 4.0),
            _flow("e3", 5.0),
            _flow("e4", 5.0),
        ),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _resolution(result, "m").reason == ODResolutionReason.SPARSE_OBSERVATION


def test_distance_prior_from_occupancy_only() -> None:
    """流量観測が無く占有のみの場合は距離 prior の純再配分に縮退する

    三角形 a-b-c（全エッジ未観測）で各ノードに 2 本の未観測アーク → 保存補完は働かない
    a,c は MIXED で ΔOcc=10（b は ΔOcc=0）。Closed モード，等距離 → δ(a,c)=δ(c,a)=10
    """
    graph = Graph(
        nodes=(
            _node("a", NodeKind.GOAL_TRANSIT_MIXED),
            _node("b", NodeKind.GOAL_TRANSIT_MIXED),
            _node("c", NodeKind.GOAL_TRANSIT_MIXED),
        ),
        edges=(
            _edge("e_ab", "a", "b"),
            _edge("e_bc", "b", "c"),
            _edge("e_ca", "c", "a"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        node_occupancies=(
            _occ("a", occupancy=10.0, delta=10.0),
            _occ("b", occupancy=0.0, delta=0.0),
            _occ("c", occupancy=10.0, delta=10.0),
        ),
    )

    result = _run(graph, observations, _config(), is_open_mode=False)

    assert _require(result.od_matrix, "a", "c").demand == pytest.approx(10.0)
    assert _require(result.od_matrix, "c", "a").demand == pytest.approx(10.0)
    assert _resolution(result, "a").mode == ODResolutionMode.DISTANCE_PRIOR
    assert _resolution(result, "a").reason == ODResolutionReason.NODE_ONLY


def test_closed_mode_equalizes_marginals() -> None:
    """Closed モードは生成・吸収を共通量 T=½(Σprod+Σabsorb) へ補正する

    s1,s2 -> m -> t1,t2。Σprod=10, Σabsorb=8（観測誤差で不均衡）→ T=9
    合流＋分岐 m により IPF
    OD 総量は T=9 に補正される
    """
    graph = Graph(
        nodes=(
            _node("s1", NodeKind.TRANSIT_ONLY),
            _node("s2", NodeKind.TRANSIT_ONLY),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s1", "m"),
            _edge("e2", "s2", "m"),
            _edge("e3", "m", "t1"),
            _edge("e4", "m", "t2"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(
            _flow("e1", 6.0),
            _flow("e2", 4.0),  # Σprod = 10
            _flow("e3", 6.0),
            _flow("e4", 2.0),  # Σabsorb = 8
        ),
    )

    result = _run(graph, observations, _config(), is_open_mode=False)

    total = sum(od.demand for od in result.od_matrix)
    assert total == pytest.approx(9.0)  # T = (10 + 8) / 2
    # δ(s1,t1) = prod(s1)*absorb(t1)/T = 5.4 * 6.75 / 9
    assert _require(result.od_matrix, "s1", "t1").demand == pytest.approx(4.05)


def test_delta_min_cut_and_renormalize() -> None:
    """微小 OD をカットし，残った要素で行周辺を再正規化して総量を回復する

    s -> m -> t1(9.9), t2(0.1)。delta_min=0.5 で t2 をカット →
    t1 に再正規化され δ(s,t1)=10.0
    """
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s", "m"),
            _edge("e2", "m", "t1"),
            _edge("e3", "m", "t2"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0), _flow("e2", 9.9), _flow("e3", 0.1)),
    )

    result = _run(graph, observations, _config(delta_min=0.5), is_open_mode=True)

    assert _find(result.od_matrix, "s", "t2") is None
    assert _require(result.od_matrix, "s", "t1").demand == pytest.approx(10.0)


def test_open_mode_releasing_mixed_node_is_origin() -> None:
    """Open モードで放出中（ΔOcc<0）の混在ノードが生成源になる（退場需要の導出）

    H(MIXED, ΔOcc=-10) -e1-> j -e2-> ex(境界 GOAL)。H から 10 が流出しており、
    int→ext の OD δ(H, ex)=10 が導出される
    """
    graph = Graph(
        nodes=(
            _node("H", NodeKind.GOAL_TRANSIT_MIXED),
            _node("j", NodeKind.TRANSIT_ONLY),
            _node("ex", NodeKind.GOAL, boundary=True),
        ),
        edges=(_edge("e1", "H", "j"), _edge("e2", "j", "ex")),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0), _flow("e2", 10.0)),
        node_occupancies=(_occ("H", occupancy=30.0, delta=-10.0),),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _require(result.od_matrix, "H", "ex").demand == pytest.approx(10.0)
    # 逆向き（ex→H）の幻需要は生じない
    assert _find(result.od_matrix, "ex", "H") is None


def test_open_mode_accumulating_mixed_node_is_not_origin() -> None:
    """Open モードで蓄積中（ΔOcc>=0）の混在ノードは生成源にならない（従来挙動の維持）"""
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("H", NodeKind.GOAL_TRANSIT_MIXED),
        ),
        edges=(_edge("e1", "s", "H"),),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0),),
        node_occupancies=(_occ("H", occupancy=20.0, delta=10.0),),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    assert _require(result.od_matrix, "s", "H").demand == pytest.approx(10.0)
    assert all(od.origin != NodeID("H") for od in result.od_matrix)


def test_empty_when_no_observations() -> None:
    """観測が無ければ生成源・吸収先が空で OD も空（解像度は NODE_ONLY）"""
    graph = Graph(
        nodes=(_node("a", NodeKind.GOAL), _node("b", NodeKind.GOAL)),
        edges=(_edge("e1", "a", "b"),),
    )
    observations = Observations(observed_at=_OBSERVED_AT)

    result = _run(graph, observations, _config(), is_open_mode=False)

    assert result.od_matrix == ()
    assert _resolution(result, "a").mode == ODResolutionMode.DISTANCE_PRIOR


def test_output_is_deterministic_in_node_order() -> None:
    """出力は node_demands（= enabled_nodes()）順の (origin, destination) で決定的"""
    graph = Graph(
        nodes=(
            _node("s", NodeKind.TRANSIT_ONLY, boundary=True),
            _node("m", NodeKind.TRANSIT_ONLY),
            _node("t1", NodeKind.GOAL),
            _node("t2", NodeKind.GOAL),
        ),
        edges=(
            _edge("e1", "s", "m"),
            _edge("e2", "m", "t1"),
            _edge("e3", "m", "t2"),
        ),
    )
    observations = Observations(
        observed_at=_OBSERVED_AT,
        arc_flows=(_flow("e1", 10.0), _flow("e2", 5.0), _flow("e3", 5.0)),
    )

    result = _run(graph, observations, _config(), is_open_mode=True)

    pairs = [(od.origin.value, od.destination.value) for od in result.od_matrix]
    assert pairs == sorted(
        pairs,
        key=lambda p: (
            ["s", "m", "t1", "t2"].index(p[0]),
            ["s", "m", "t1", "t2"].index(p[1]),
        ),
    )
