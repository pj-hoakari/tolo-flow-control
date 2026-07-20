"""開発用 CLI

サブコマンド:
- ``list``    : シナリオ・グラフプリセットの一覧
- ``run``     : シナリオ 1 件をパイプライン実行し、各モジュール結果を JSON＋PNG 出力
- ``run-all`` : 全シナリオを実行し、横断インデックス（index.json）＋履歴スナップショットを出力
- ``compare`` : 2 つの数値スナップショットを比較（履歴ベースの回帰/改善追跡）
- ``fuzz``    : ランダムシナリオを多数実行し不変条件を検証、違反ケースの成果物を保存
- ``graph``   : グラフ（プリセット or ファイル）を構築・描画し、必要なら YAML/JSON へ保存

実行例: ``uv run python -m devtools run multi-route-surge --out ./_devout``
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import compare as compare_mod
from . import fuzzer, graph_builder, report, scenarios, visualize
from .pipeline import run_pipeline

_DEFAULT_OUT = "_devout"


def cmd_list(_args: argparse.Namespace) -> int:
    print("scenarios:")
    for name in scenarios.SCENARIOS:
        scen = scenarios.get_scenario(name)
        print(f"  {name:22s} {scen.description}")
    print("\ngraph presets:")
    for name in sorted(graph_builder.PRESETS):
        print(f"  {name}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        scen = scenarios.get_scenario(args.scenario)
    except KeyError as e:
        print(e)
        return 2

    if args.seed is not None:
        new_opt = replace(scen.configs.optimization, solver_seed=args.seed)
        scen = replace(scen, configs=replace(scen.configs, optimization=new_opt))

    run = run_pipeline(scen, force=args.force, time_limit=args.time_limit)

    out = Path(args.out) / args.scenario
    written = report.dump_run(run, scen.built_graph, out, images=not args.no_images)

    det = run.detection
    print(f"[{scen.name}] mode={run.mode.value} verdict={det.verdict_hint.value}")
    if det.triggered_edges:
        print("  triggered edges:", ", ".join(e.value for e in det.triggered_edges))
    if det.triggered_nodes:
        print("  triggered nodes:", ", ".join(n.value for n in det.triggered_nodes))
    for note in run.notes:
        print(f"  note: {note}")
    if run.optimization is not None:
        r = run.optimization.optimization_result
        print(
            f"  solver={r.solver_status.value} tau*={r.objective_values.tau_star:.4g} "
            f"throughput={r.objective_values.throughput:.4g} "
            f"fallback={run.optimization.constraint_report.fallback_to_previous}"
        )
        stats = run.optimization.solver_stats
        if r.solver_status.value == "LIGHTWEIGHT":
            print(
                "  lightweight:"
                f" zones={stats.zones_processed}"
                f" greedy_iterations={stats.greedy_iterations}"
                f" assign_lp_ms={stats.assign_lp_ms}"
                f" build_ms={stats.build_ms}"
                f" greedy_ms={stats.greedy_ms}"
                + (" [TRUNCATED]" if stats.greedy_truncated else "")
            )
        if stats.demand_all_cut:
            print(
                "  WARNING: DEMAND_ALL_CUT"
                f" (od_pairs_input={stats.od_pairs_input} が delta_min で全カット。提案は実質空)"
            )
        if r.restriction_proposal:
            print("  restrictions:", ", ".join(
                f"{proposal.edge_id.value}:{proposal.action.value}"
                for proposal in r.restriction_proposal
            ))
    if run.forecast is not None:
        print(f"  OD pairs={len(run.forecast.od_matrix)} "
              f"reproduction_error={run.forecast.reproduction_error:.4g}")
    print("  timings(ms):", {k: round(v, 1) for k, v in run.timings_ms.items()})
    print(f"  wrote {len(written)} files under {out}/")
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    out_root = Path(args.out)
    entries: list[dict[str, object]] = []
    targets: list = []
    skipped: list[str] = []
    for name in scenarios.SCENARIOS:
        scen = scenarios.get_scenario(name)
        if scen.skip_in_run_all:
            skipped.append(name)
        else:
            targets.append((name, scen))
    print(f"running {len(targets)} scenarios ...")
    for skip_name in skipped:
        print(f"  {skip_name:24s} SKIPPED (skip_in_run_all; 単独 run で実行可)")
    for name, scen in targets:
        run = run_pipeline(scen, force=args.force, time_limit=args.time_limit)
        report.dump_run(run, scen.built_graph, out_root / name, images=not args.no_images)
        entries.append(report.run_summary(run))
        det = run.detection
        ostr = ""
        if run.optimization is not None:
            r = run.optimization.optimization_result
            ostr = (
                f" solver={r.solver_status.value}"
                f" tau*={r.objective_values.tau_star:.3g}"
                f" thru={r.objective_values.throughput:.3g}"
            )
            if r.solver_status.value == "LIGHTWEIGHT":
                ostr += f" zones={run.optimization.solver_stats.zones_processed}"
            if run.optimization.solver_stats.demand_all_cut:
                ostr += " [DEMAND_ALL_CUT]"
        print(f"  {name:24s} {run.mode.value:6s} {det.verdict_hint.value:12s}{ostr}")
    created_at = datetime.now().isoformat(timespec="seconds")
    label = args.label or datetime.now().strftime("%Y%m%d-%H%M%S")
    idx = report.write_index(out_root, entries, label=label, created_at=created_at)
    snap = report.save_history_snapshot(
        out_root, entries, label=label, created_at=created_at
    )
    print(f"wrote index: {idx}")
    print(f"history snapshot [{label}]: {snap}")
    print(f"比較: uv run python -m devtools compare <base> {label}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    try:
        base, base_path = compare_mod.resolve_index(args.base, out_dir)
        against, against_path = compare_mod.resolve_index(args.against, out_dir)
    except FileNotFoundError as e:
        print(e)
        return 2
    rows = compare_mod.compare(base, against)
    print(f"base    : {base_path}")
    print(f"against : {against_path}")
    print(compare_mod.format_report(rows, args.base, args.against))
    # 数値結果系に差分（回帰の可能性）があれば非ゼロ終了
    changed = any(r.get("result_changed") or r.get("presence") != "BOTH" for r in rows)
    return 1 if changed else 0


def cmd_fuzz(args: argparse.Namespace) -> int:
    out = Path(args.out) / "fuzz"
    summary, outcomes = fuzzer.run_fuzz(
        args.graph,
        count=args.count,
        seed=args.seed,
        out_dir=out,
        save_all=args.save_all,
        time_limit=args.time_limit,
    )
    print(
        f"fuzz: total={summary.total} failed={summary.failed} "
        f"triggered={summary.triggered} downstream={summary.downstream} "
        f"infeasible={summary.infeasible} fallback={summary.fallback}"
    )
    if summary.by_violation:
        print("violations by kind:")
        for kind, n in sorted(summary.by_violation.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {kind}")
    failing = [o for o in outcomes if o.failed]
    if failing:
        print(f"failing cases ({len(failing)}):")
        for o in failing[:20]:
            print(f"  {o.name} [{o.graph_name}] verdict={o.verdict} "
                  f"solver={o.solver_status}: {'; '.join(o.violations)}")
        if len(failing) > 20:
            print(f"  ... and {len(failing) - 20} more")
        print(f"artifacts saved under {out}/fail/")
    else:
        print("不変条件違反・例外なし（全ケース pass）")
    if args.save_all:
        print(f"全ケースの成果物を {out}/case/ に保存しました")
    print(f"summary: {out}/summary.json")
    return 1 if summary.failed else 0


def cmd_graph(args: argparse.Namespace) -> int:
    try:
        built = graph_builder.resolve_graph_arg(args.graph)
    except KeyError as e:
        print(e)
        return 2
    label = args.graph if args.graph in graph_builder.PRESETS else Path(args.graph).stem
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"graph_{label}.png"
    visualize.render_graph(built, png, title=label)
    print(f"wrote {png}")
    if args.save:
        graph_builder.save(built, Path(args.save))
        print(f"saved spec to {args.save}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m devtools",
        description="flow_control 開発用パイプライン可視化ツール",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="シナリオ・グラフプリセット一覧")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="シナリオを実行し各モジュール結果を出力")
    p_run.add_argument("scenario", help="シナリオ名（list で確認）")
    p_run.add_argument("--out", default=_DEFAULT_OUT, help="出力ディレクトリ（既定: _devout）")
    p_run.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="MILP タイムアウト秒（未指定ならシナリオ設定値を使用）",
    )
    p_run.add_argument("--seed", type=int, default=None, help="最適化ソルバーseedの上書き")
    p_run.add_argument("--no-images", action="store_true", help="PNG を出力しない")
    p_run.add_argument("--force", action="store_true", help="未発火でも下流を実行")
    p_run.set_defaults(func=cmd_run)

    p_runall = sub.add_parser("run-all", help="全シナリオを実行し index.json を出力")
    p_runall.add_argument("--out", default=_DEFAULT_OUT, help="出力ディレクトリ（既定: _devout）")
    p_runall.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="MILP タイムアウト秒（未指定ならシナリオ設定値を使用）",
    )
    p_runall.add_argument("--no-images", action="store_true", help="PNG を出力しない")
    p_runall.add_argument("--force", action="store_true", help="未発火でも下流を実行")
    p_runall.add_argument(
        "--label",
        default=None,
        help="履歴スナップショットのラベル（既定: タイムスタンプ）",
    )
    p_runall.set_defaults(func=cmd_run_all)

    p_cmp = sub.add_parser("compare", help="2 つの数値スナップショットを比較（履歴回帰/改善）")
    p_cmp.add_argument("base", help="基準: ラベル / 'latest' / ファイルパス")
    p_cmp.add_argument("against", help="比較対象: ラベル / 'latest' / ファイルパス")
    p_cmp.add_argument("--out", default=_DEFAULT_OUT, help="出力ディレクトリ（履歴の探索元）")
    p_cmp.set_defaults(func=cmd_compare)

    p_fuzz = sub.add_parser("fuzz", help="ランダムシナリオで不変条件を検証")
    p_fuzz.add_argument("--graph", default=None, help="プリセット名/ファイル（既定: 毎回ランダム）")
    p_fuzz.add_argument("--count", type=int, default=20, help="ケース数")
    p_fuzz.add_argument("--seed", type=int, default=0, help="マスターseed")
    p_fuzz.add_argument("--out", default=_DEFAULT_OUT, help="出力ディレクトリ")
    p_fuzz.add_argument("--time-limit", type=float, default=5.0, help="MILP タイムアウト秒")
    p_fuzz.add_argument("--save-all", action="store_true", help="違反なしケースも成果物保存")
    p_fuzz.set_defaults(func=cmd_fuzz)

    p_graph = sub.add_parser("graph", help="グラフを構築・描画（必要なら保存）")
    p_graph.add_argument("graph", help="プリセット名 or YAML/JSON ファイルパス")
    p_graph.add_argument("--out", default=_DEFAULT_OUT, help="PNG 出力ディレクトリ")
    p_graph.add_argument("--save", default=None, help="グラフ spec の保存先（.yaml/.json）")
    p_graph.set_defaults(func=cmd_graph)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
