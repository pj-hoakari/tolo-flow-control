"""devtools（開発用パイプライン可視化ツール）の軽量テスト

ソルバーを起動しない範囲（グラフ構築・直列化・シナリオ生成・検知のみ）を対象に、
回帰を素早く検出する。MILP を含む経路は別途 CLI/ファジングで確認する
"""

import json
from pathlib import Path

import pytest

from devtools import graph_builder, scenarios
from devtools.graph_builder import resolve_positions
from devtools.pipeline import run_pipeline
from devtools.serialize import to_jsonable


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
