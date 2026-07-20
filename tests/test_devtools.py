"""devtools（開発用パイプライン可視化ツール）の軽量テスト

ソルバーを起動しない範囲（グラフ構築・直列化・シナリオ生成・検知のみ）を対象に、
回帰を素早く検出する。MILP を含む経路は別途 CLI/ファジングで確認する
"""

import json
from pathlib import Path

import pytest

from devtools import compare, graph_builder, report, scenarios
from devtools.graph_builder import resolve_positions
from devtools.pipeline import run_pipeline
from devtools.serialize import to_jsonable


def _index(scenario: str, *, tau: float, thru: float, p1: int, p2: int):
    return {
        "runs": [
            {
                "scenario": scenario,
                "verdict": "TRIGGERED",
                "forecast": {"od_pairs": 7},
                "optimization": {
                    "solver_status": "OPTIMAL",
                    "phase1": {"ms": p1},
                    "phase2": {"ms": p2},
                    "tau_star": tau,
                    "throughput": thru,
                    "fallback_to_previous": False,
                },
            }
        ]
    }


def test_compare_flags_result_change_and_computes_perf_delta() -> None:
    base = _index("s", tau=0.333, thru=75.0, p1=3000, p2=7000)
    against = _index("s", tau=0.333, thru=242.0, p1=3000, p2=3000)
    rows = compare.compare(base, against)
    assert len(rows) == 1
    row = rows[0]
    # 結果系（throughput）の変化を検出、tau* は不変
    assert "thru" in row["result_changed"]
    assert "tau*" not in row["result_changed"]
    # 性能（phase1+phase2）の相対差: 10000 → 6000 = -40%
    assert row["ms"] == (10000, 6000)
    assert row["ms_delta_pct"] == pytest.approx(-40.0)
    # 結果不変なら result_changed は空
    same = compare.compare(base, base)
    assert same[0]["result_changed"] == []


def test_compare_flags_demand_all_cut_change() -> None:
    base = _index("s", tau=1.0, thru=10.0, p1=1, p2=1)
    against = _index("s", tau=1.0, thru=10.0, p1=1, p2=1)
    base["runs"][0]["optimization"]["demand_all_cut"] = False
    against["runs"][0]["optimization"]["demand_all_cut"] = True
    rows = compare.compare(base, against)
    assert "demand_all_cut" in rows[0]["result_changed"]


def test_compare_ignores_demand_all_cut_when_missing_on_one_side() -> None:
    # 旧スナップショット（キーなし）との比較でノイズを出さない
    base = _index("s", tau=1.0, thru=10.0, p1=1, p2=1)
    against = _index("s", tau=1.0, thru=10.0, p1=1, p2=1)
    against["runs"][0]["optimization"]["demand_all_cut"] = False
    against["runs"][0]["optimization"]["commodities_used"] = 3
    rows = compare.compare(base, against)
    assert rows[0]["result_changed"] == []


def test_compare_marks_added_and_removed() -> None:
    base = _index("a", tau=0.0, thru=0.0, p1=1, p2=1)
    against = _index("b", tau=0.0, thru=0.0, p1=1, p2=1)
    presences = {r["scenario"]: r["presence"] for r in compare.compare(base, against)}
    assert presences == {"a": "REMOVED", "b": "ADDED"}


def test_graph_roundtrip_json_and_yaml(tmp_path: Path) -> None:
    built = graph_builder.venue()
    # dict 経由のラウンドトリップでグラフ構造が保たれる
    restored = graph_builder.from_dict(graph_builder.to_dict(built))
    assert restored.graph == built.graph

    for suffix in (".json", ".yaml"):
        path = tmp_path / f"venue{suffix}"
        graph_builder.save(built, path)
        loaded = graph_builder.load(path)
        assert loaded.graph == built.graph


@pytest.mark.parametrize("name", sorted(graph_builder.PRESETS))
def test_graph_presets_build_and_layout(name: str) -> None:
    built = graph_builder.get_preset(name)
    assert built.graph.nodes
    pos = resolve_positions(built)
    # 全ノードに座標が解決される
    assert {n.node_id.value for n in built.graph.nodes} == set(pos)


@pytest.mark.parametrize("name", sorted(scenarios.SCENARIOS))
def test_scenarios_build(name: str) -> None:
    scen = scenarios.get_scenario(name)
    assert scen.graph.nodes
    assert scen.observations.observed_at == scen.server_time
    # 登録キーと生成された Scenario.name の一致（新規ファイル追加時の取り違え検出）
    assert scen.name == name


@pytest.mark.parametrize("name", sorted(scenarios.SCENARIOS))
def test_scenarios_trigger_as_expected(name: str) -> None:
    # 検出仕様の変更でシナリオが発火しなくなる「検証空洞化」を CI で検知する。
    # Detection のみ実行するため軽量（ソルバーは起動しない）
    from flow_control.detection import VerdictHint, detect

    scen = scenarios.get_scenario(name)
    detection = detect(
        graph=scen.graph,
        observations=scen.observations,
        history_digest=scen.history_digest,
        previous_state=scen.previous_state,
        events=scen.events,
        config=scen.configs.detection,
        server_time=scen.server_time,
        references=scen.references,
    )
    triggered = detection.verdict_hint == VerdictHint.TRIGGERED
    assert triggered == scen.expect_trigger, (
        f"{name}: expect_trigger={scen.expect_trigger} but verdict="
        f"{detection.verdict_hint.value}"
    )


def test_consistent_observations_conserve_flow() -> None:
    """保存則整合生成器: 通過ノードで流入=流出、混在ホールで流入超過=ΔOcc。"""
    from collections import defaultdict

    from flow_control.domain import EdgeID, FlowDirection, NodeID, NodeKind
    from devtools.scenario_base import ODSpec, build_consistent_observations_and_history

    built = graph_builder.venue()
    graph = built.graph
    od = (
        ODSpec(NodeID("in"), NodeID("hallA"), 30.0, surge=True),
        ODSpec(NodeID("in"), NodeID("hallB"), 10.0),
        ODSpec(NodeID("in"), NodeID("out"), 20.0),
    )
    obs, hist = build_consistent_observations_and_history(graph, od)

    inflow: dict[NodeID, float] = defaultdict(float)
    outflow: dict[NodeID, float] = defaultdict(float)
    for af in obs.arc_flows:
        edge = graph.edge_of(af.edge_id)
        if af.direction == FlowDirection.A_TO_B:
            src, dst = edge.endpoint_a, edge.endpoint_b
        else:
            src, dst = edge.endpoint_b, edge.endpoint_a
        outflow[src] += af.flow_rate
        inflow[dst] += af.flow_rate

    occ = {o.node_id: o for o in obs.node_occupancies}
    for node in graph.enabled_nodes():
        nid = node.node_id
        net_in = inflow[nid] - outflow[nid]
        if node.kind == NodeKind.TRANSIT_ONLY:
            # 通過ノード: 保存則が厳密に成立
            assert abs(net_in) < 1e-9, f"{nid.value}: net={net_in}"
        elif node.kind == NodeKind.GOAL_TRANSIT_MIXED:
            # 混在ホール: 流入超過（負なら放出超過）がそのまま ΔOcc
            assert occ[nid].occupancy_delta == pytest.approx(net_in)

    # surge 成分の経路上エッジのみ履歴系列が立ち上がる
    series = {w.edge_id: w.flow_samples for w in hist.window_series}
    surge_series = series[EdgeID("e_j1_hallA")]
    flat_series = series[EdgeID("e_j1_hallB")]
    assert surge_series[-1][1] > surge_series[0][1]
    assert flat_series[0][1] == pytest.approx(flat_series[-1][1])

    # 決定性
    obs2, hist2 = build_consistent_observations_and_history(graph, od)
    assert obs == obs2 and hist == hist2


def test_consistent_observations_yield_low_reproduction_error() -> None:
    """保存則整合な観測では Forecasting の OD 再現誤差が構造的に小さい。"""
    from flow_control.domain import Mode, NodeID
    from flow_control.forecasting import forecast
    from devtools.scenario_base import (
        DEFAULT_REFERENCE,
        ODSpec,
        build_consistent_observations_and_history,
        default_configs,
    )

    built = graph_builder.venue()
    graph = built.graph
    # ホールを終点としてのみ使う OD 構成（ホール通過は帰属曖昧で誤差が残るため）
    obs, hist = build_consistent_observations_and_history(
        graph,
        (
            ODSpec(NodeID("in"), NodeID("hallA"), 30.0, surge=True),
            ODSpec(NodeID("in"), NodeID("hallB"), 10.0),
        ),
    )
    fc = forecast(
        graph=graph,
        observations=obs,
        history_digest=hist,
        references=DEFAULT_REFERENCE,
        triggered_edges=(),
        config=default_configs().forecasting,
        mode=Mode.OPEN,
    )
    # 従来生成器では 0.36〜1.05 だった再現誤差が 1 桁以上下がる
    assert fc.reproduction_error < 0.05
    # 真の OD（in→hallA 30 / in→hallB 10）が需要として残る
    demands = {
        (od.origin.value, od.destination.value): od.demand for od in fc.od_matrix
    }
    assert demands.get(("in", "hallA"), 0.0) == pytest.approx(30.0, rel=0.25)
    assert demands.get(("in", "hallB"), 0.0) == pytest.approx(10.0, rel=0.35)


def test_consistent_observations_respect_oneway() -> None:
    """current 方向が一方通行のエッジには逆向きフローを載せない。"""
    from flow_control.domain import FlowDirection, NodeID
    from devtools.scenario_base import ODSpec, build_consistent_observations_and_history

    built = graph_builder.expo()  # 一方通行ループを含む
    graph = built.graph
    obs, _ = build_consistent_observations_and_history(
        graph, (ODSpec(NodeID("gate"), NodeID("hallD"), 12.0),)
    )
    oneway = {
        e.edge_id: e.current_direction.value
        for e in graph.enabled_edges()
        if e.current_direction.value != "BIDIRECTIONAL"
    }
    for af in obs.arc_flows:
        if af.edge_id in oneway:
            assert af.direction == FlowDirection(oneway[af.edge_id])


def test_serialize_is_json_dumpable() -> None:
    scen = scenarios.get_scenario("multi-route-surge")
    payload = to_jsonable(scen.observations)
    # ラウンドトリップ可能な素朴構造であること
    text = json.dumps(payload, ensure_ascii=False)
    assert "_type" in text
    # EdgeID はラップを剥がして文字列化される
    serialized = to_jsonable(scen.graph.edges[0].edge_id)
    assert serialized == scen.graph.edges[0].edge_id.value


def test_pipeline_no_trigger_skips_downstream() -> None:
    # NO_TRIGGER ではソルバーを起動せず下流をスキップする（高速・決定的）
    scen = scenarios.get_scenario("normal-no-trigger")
    run = run_pipeline(scen)
    assert not run.downstream_ran
    assert run.forecast is None
    assert run.optimization is None


def test_pipeline_force_runs_downstream_without_trigger() -> None:
    scen = scenarios.get_scenario("normal-no-trigger")
    run = run_pipeline(scen, force=True, time_limit=10.0)
    assert run.downstream_ran
    assert run.optimization is not None


def test_report_writes_images_in_module_directories(tmp_path: Path) -> None:
    scen = scenarios.get_scenario("normal-no-trigger")
    run = run_pipeline(scen)
    written = report.dump_run(run, scen.built_graph, tmp_path, images=True)

    assert tmp_path / "01_detection" / "trigger.png" in written
    assert tmp_path / "01_detection" / "trigger_legend.png" in written
    assert tmp_path / "00_summary" / "summary.png" in written
    assert (tmp_path / "01_detection" / "trigger.png").is_file()
    assert (tmp_path / "01_detection" / "trigger_legend.png").is_file()
    assert (tmp_path / "00_summary" / "summary.png").is_file()
    assert not (tmp_path / "01_detection.png").exists()
