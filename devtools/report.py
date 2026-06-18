"""実行結果の成果物出力（JSON ＋ PNG）

1 回のパイプライン実行について、各モジュール結果の JSON（検証ログ兼リプレイ素材）と、
グラフ spec、および可視化 PNG をひとつの出力ディレクトリへ書き出す。CLI の run / fuzz の
双方から利用する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import graph_builder, visualize
from .graph_builder import BuiltGraph
from .pipeline import PipelineRun
from .serialize import dump_json


def run_summary(
    run: PipelineRun, invariants: list[str] | None = None
) -> dict[str, Any]:
    """1 実行の要約 dict（run.json／横断インデックスの双方で使う）"""
    det = run.detection
    summary: dict[str, Any] = {
        "scenario": run.scenario_name,
        "mode": run.mode.value,
        "verdict": det.verdict_hint.value,
        "downstream_ran": run.downstream_ran,
        "triggered_edges": [e.value for e in det.triggered_edges],
        "triggered_nodes": [n.value for n in det.triggered_nodes],
        "timings_ms": {k: round(v, 2) for k, v in run.timings_ms.items()},
        "notes": run.notes,
        "invariants": invariants or [],
    }
    if run.forecast is not None:
        summary["forecast"] = {
            "od_pairs": len(run.forecast.od_matrix),
            "reproduction_error": run.forecast.reproduction_error,
        }
    if run.optimization is not None:
        res = run.optimization.optimization_result
        st = run.optimization.solver_stats
        cr = run.optimization.constraint_report
        summary["optimization"] = {
            "solver_status": res.solver_status.value,
            "phase1": {"status": st.phase1_status.value, "ms": st.phase1_ms},
            "phase2": {"status": st.phase2_status.value, "ms": st.phase2_ms},
            "tau_star": res.objective_values.tau_star,
            "throughput": res.objective_values.throughput,
            "fallback_to_previous": cr.fallback_to_previous,
            "local_reachability": cr.local_reachability_satisfied,
            "boundary_reachability": cr.boundary_reachability_satisfied,
            "legal_fixed_violations": [e.value for e in cr.legal_fixed_violations],
        }
    return summary


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

    # run.json は要約（triggered・solver・forecast 集約）＋次サイクル用の検知状態
    _json({**run_summary(run, invariants), "committed_state": run.committed_state}, "run.json")

    if images:
        written.extend(visualize.render_all(run, built, out_dir, invariants=invariants))
    return written


def write_index(out_dir: Path, entries: list[dict[str, Any]]) -> Path:
    """複数 run の横断インデックス（index.json）を書き出す"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.json"
    dump_json({"count": len(entries), "runs": entries}, path)
    return path
