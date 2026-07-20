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
    """1 実行の数値要約 dict（run.json／横断インデックス／compare の共通ソース）

    個別モジュール JSON を開かずとも `index.json` 1 ファイルで解析が完結するよう、
    分析でよく使う派生指標（信頼度レンジ・OD 解像度モード・フォールバックエッジ・
    重要度リスト・方向提案分布・境界制御・evidence 種別）まで畳み込んで持たせる。
    """
    det = run.detection
    summary: dict[str, Any] = {
        "scenario": run.scenario_name,
        "mode": run.mode.value,
        "verdict": det.verdict_hint.value,
        "downstream_ran": run.downstream_ran,
        "triggered_edges": [e.value for e in det.triggered_edges],
        "triggered_nodes": [n.value for n in det.triggered_nodes],
        "evidence_kinds": _counts(type(ev).__name__ for ev in det.evidences),
        "timings_ms": {k: round(v, 2) for k, v in run.timings_ms.items()},
        "notes": run.notes,
        "invariants": invariants or [],
    }
    if run.forecast is not None:
        fc = run.forecast
        confs = [c.confidence for c in fc.node_confidence]
        summary["forecast"] = {
            "od_pairs": len(fc.od_matrix),
            "reproduction_error": fc.reproduction_error,
            "node_confidence_min": min(confs) if confs else None,
            "node_confidence_max": max(confs) if confs else None,
            "resolution_modes": sorted({r.mode.value for r in fc.estimation_resolution}),
            "resolution_reasons": _counts(
                resolution.reason.value for resolution in fc.estimation_resolution
            ),
            "imputed_arcs": sorted(
                {
                    edge_id.value
                    for resolution in fc.estimation_resolution
                    for edge_id in resolution.imputed_arcs
                }
            ),
            "fallback_default_edges": [
                e.value for e in fc.fallback_usage.used_default_edges
            ],
            "staying_nodes": [d.node_id.value for d in fc.node_demand if d.staying > 0.0],
        }
    if run.detour is not None:
        summary["detour"] = {
            "trigger_sets": len(run.detour.detour_sets),
            "k_effective": {
                detour.origin_edge.value: detour.k_effective
                for detour in run.detour.detour_sets
            },
            "path_counts": {
                detour.origin_edge.value: len(detour.paths)
                for detour in run.detour.detour_sets
            },
            "trigger_edge_union": sorted(
                edge_id.value for edge_id in run.detour.trigger_edge_set()
            ),
        }
    if run.optimization is not None:
        res = run.optimization.optimization_result
        st = run.optimization.solver_stats
        cr = run.optimization.constraint_report
        summary["optimization"] = {
            "solver_status": res.solver_status.value,
            "phase1": {"status": st.phase1_status.value, "ms": st.phase1_ms},
            "phase2": {"status": st.phase2_status.value, "ms": st.phase2_ms},
            "lightweight": {
                "assign_lp_ms": st.assign_lp_ms,
                "build_ms": st.build_ms,
                "greedy_ms": st.greedy_ms,
                "greedy_iterations": st.greedy_iterations,
                "greedy_truncated": st.greedy_truncated,
                "zones_processed": st.zones_processed,
                "localization_capped": st.localization_capped,
                "tau_residual": st.tau_residual,
            },
            "tau_star": res.objective_values.tau_star,
            "throughput": res.objective_values.throughput,
            "fallback_to_previous": cr.fallback_to_previous,
            "local_reachability": cr.local_reachability_satisfied,
            "boundary_reachability": cr.boundary_reachability_satisfied,
            "legal_fixed_violations": [e.value for e in cr.legal_fixed_violations],
            "route_importance_nonzero": [
                [r.edge_id.value, r.direction.value, round(r.importance, 4)]
                for r in res.route_importance
                if r.importance > 1e-9
            ],
            "direction_proposals": _counts(
                dp.proposed_direction.value for dp in res.direction_proposal
            ),
            "direction_change_types": _counts(
                dp.change_type.value for dp in res.direction_proposal
            ),
            "restriction_proposals": [
                {
                    "edge_id": proposal.edge_id.value,
                    "action": proposal.action.value,
                    "limit_value": proposal.limit_value,
                    "reason": proposal.reason.value,
                    "confidence": proposal.confidence,
                }
                for proposal in res.restriction_proposal
            ],
            "boundary_controls": [
                [bc.node_id.value, bc.action.value] for bc in res.boundary_control
            ],
        }
    return summary


def _counts(values: Any) -> dict[str, int]:
    """イテラブルの出現回数を {キー: 件数} に畳む（決定的に key ソート）"""
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return {k: out[k] for k in sorted(out)}


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


def build_index(
    entries: list[dict[str, Any]],
    *,
    label: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "created_at": created_at,
        "count": len(entries),
        "runs": entries,
    }


def write_index(
    out_dir: Path,
    entries: list[dict[str, Any]],
    *,
    label: str | None = None,
    created_at: str | None = None,
) -> Path:
    """複数 run の横断インデックス（最新版 index.json）を書き出す"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.json"
    dump_json(build_index(entries, label=label, created_at=created_at), path)
    return path


def save_history_snapshot(
    out_dir: Path,
    entries: list[dict[str, Any]],
    *,
    label: str,
    created_at: str | None = None,
) -> Path:
    """数値スナップショットを履歴として保存（`_devout/history/<label>/index.json`）

    画像や個別モジュール JSON は残さず、比較に使う数値要約のみを保持する。
    """
    path = out_dir / "history" / label / "index.json"
    dump_json(build_index(entries, label=label, created_at=created_at), path)
    return path
