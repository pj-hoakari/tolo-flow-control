"""実行結果の成果物出力（JSON ＋ PNG）

1 回のパイプライン実行について、各モジュール結果の JSON（検証ログ兼リプレイ素材）と、
グラフ spec、および可視化 PNG をひとつの出力ディレクトリへ書き出す。CLI の run / fuzz の
双方から利用する。
"""

from __future__ import annotations

from pathlib import Path

from . import graph_builder, visualize
from .graph_builder import BuiltGraph
from .pipeline import PipelineRun
from .serialize import dump_json


def dump_run(
    run: PipelineRun,
    built: BuiltGraph,
    out_dir: Path,
    *,
    images: bool = True,
    invariants: list[str] | None = None,
) -> list[Path]:
    """各モジュール結果の JSON・グラフ spec・（任意で）PNG を書き出す"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _json(obj: object, name: str) -> None:
        p = out_dir / name
        dump_json(obj, p)
        written.append(p)

    _json(graph_builder.to_dict(built), "graph.json")
    _json(run.detection, "detection.json")
    if run.forecast is not None:
        _json(run.forecast, "forecasting.json")
    if run.detour is not None:
        _json(run.detour, "detour.json")
    if run.optimization is not None:
        _json(run.optimization, "optimization.json")

    _json(
        {
            "scenario": run.scenario_name,
            "mode": run.mode.value,
            "verdict": run.detection.verdict_hint.value,
            "downstream_ran": run.downstream_ran,
            "timings_ms": run.timings_ms,
            "notes": run.notes,
            "invariants": invariants or [],
            "committed_state": run.committed_state,
        },
        "run.json",
    )

    if images:
        written.extend(visualize.render_all(run, built, out_dir, invariants=invariants))
    return written
