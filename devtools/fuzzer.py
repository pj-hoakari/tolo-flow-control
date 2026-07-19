"""ファジング: ランダムシナリオ生成 ＋ 不変条件チェック

``random.Random(seed)`` で観測・履歴・イベントをランダム生成し（プリセットグラフ上）、
各実行に対しスモーク（例外・空結果・INFEASIBLE の検出）に加えて不変条件を検証する:

- 決定性: 同一入力の再実行で verdict・重要度・方向・目的関数が一致するか
- 制約レポート: 非フォールバック解で local/boundary 可達性・法規制違反 0 が満たされるか
- 需要予測: reproduction_error が有限・node_confidence∈[0,1]・OD 需要 ≥ 0
- 例外を投げない

違反/例外のあるケースは成果物（JSON＋PNG）を保存する。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from flow_control.detection.state import ArcWatchState, DetectionState
from flow_control.detection.triggers import Event, EventKind
from flow_control.domain import Mode

from . import graph_builder, report
from .graph_builder import BuiltGraph
from .pipeline import PipelineRun, run_pipeline
from .scenario_base import (
    DEFAULT_REFERENCE,
    DEFAULT_TIME,
    Scenario,
    build_observations_and_history,
    default_configs,
    with_edge_danger,
)
from .serialize import dump_json


def random_scenario(
    rng: random.Random, base: BuiltGraph, label: str, index: int
) -> Scenario:
    """ランダムな観測・履歴・イベントを持つシナリオを 1 件生成する"""
    built = base
    edge_ids = [e.edge_id for e in built.graph.enabled_edges()]
    server_time = DEFAULT_TIME

    n_surge = rng.randint(0, min(3, len(edge_ids)))
    surge = frozenset(rng.sample(edge_ids, n_surge)) if edge_ids else frozenset()
    n_stag = rng.randint(0, min(2, len(edge_ids)))
    stag = frozenset(rng.sample(edge_ids, n_stag)) if edge_ids else frozenset()

    events: tuple[Event, ...] = ()
    if edge_ids and rng.random() < 0.35:
        target = rng.choice(edge_ids)
        built = with_edge_danger(built, target.value, rng.uniform(1.0, 12.0))
        events = (
            Event(
                kind=EventKind.DANGER_FLAG_UP,
                target_id=f"edge:{target.value}",
                occurred_at=server_time,
            ),
        )

    # 高停滞は M 分継続が必要。確率的に前サイクルの両条件成立 watch を与えて発火可能にする
    if stag and rng.random() < 0.6:
        prev_watch = tuple(
            ArcWatchState(
                edge_id=eid,
                percentile_breached=True,
                delta_breached=True,
                stagnation_watch_since=server_time - timedelta(minutes=6),
            )
            for eid in stag
        )
    else:
        prev_watch = ()

    obs, hist = build_observations_and_history(
        built.graph,
        server_time,
        surge_edges=surge,
        stagnation_edges=stag,
        base_flow=rng.uniform(5.0, 40.0),
        surge_start=rng.uniform(2.0, 8.0),
        surge_slope=rng.uniform(8.0, 20.0),
        base_stag=rng.uniform(1.0, 4.0),
        hot_stag=rng.uniform(8.0, 20.0),
        p90_stag=rng.uniform(5.0, 12.0),
        baseline_stag=rng.uniform(1.0, 5.0),
        recent_stag_ma=rng.uniform(1.0, 6.0),
        eta=rng.choice([0.02, 0.05, 0.1]),
    )
    return Scenario(
        name=f"fuzz-{label}-{index:04d}",
        description="randomized fuzz case",
        built_graph=built,
        observations=obs,
        history_digest=hist,
        references=DEFAULT_REFERENCE,
        previous_state=DetectionState(arc_watch_states=prev_watch),
        events=events,
        server_time=server_time,
        configs=default_configs(),
        expect_trigger=bool(surge) or bool(events) or bool(prev_watch),
    )


def _signature(run: PipelineRun) -> dict[str, object]:
    """決定性比較用の主要出力シグネチャ"""
    d: dict[str, object] = {
        "verdict": run.detection.verdict_hint.value,
        "tedges": sorted(e.value for e in run.detection.triggered_edges),
        "tnodes": sorted(n.value for n in run.detection.triggered_nodes),
    }
    if run.optimization is not None:
        r = run.optimization.optimization_result
        d["solver"] = r.solver_status.value
        d["tau"] = round(r.objective_values.tau_star, 6)
        d["thru"] = round(r.objective_values.throughput, 6)
        d["importance"] = sorted(
            (ri.edge_id.value, ri.direction.value, round(ri.importance, 6))
            for ri in r.route_importance
        )
        d["direction"] = sorted(
            (dp.edge_id.value, dp.proposed_direction.value)
            for dp in r.direction_proposal
        )
    return d


def check_invariants(
    scen: Scenario, *, time_limit: float = 5.0, determinism: bool = False
) -> tuple[PipelineRun | None, list[str]]:
    """シナリオを実行し不変条件違反のリストを返す。例外時は run=None"""
    violations: list[str] = []
    try:
        run = run_pipeline(scen, time_limit=time_limit)
    except Exception as e:  # noqa: BLE001 - ファジングなのであらゆる例外を捕捉
        return None, [f"exception in pipeline: {e!r}"]

    if determinism:
        try:
            run2 = run_pipeline(scen, time_limit=time_limit)
            if _signature(run) != _signature(run2):
                violations.append("non-deterministic: outputs differ across identical runs")
        except Exception as e:  # noqa: BLE001
            violations.append(f"exception in determinism re-run: {e!r}")

    fc = run.forecast
    if fc is not None:
        if not math.isfinite(fc.reproduction_error):
            violations.append(f"reproduction_error not finite: {fc.reproduction_error}")
        for c in fc.node_confidence:
            if not (-1e-9 <= c.confidence <= 1.0 + 1e-9):
                violations.append(
                    f"node_confidence out of [0,1]: {c.node_id.value}={c.confidence}"
                )
        for o in fc.od_matrix:
            if o.demand < -1e-9:
                violations.append(
                    f"negative OD demand: {o.origin.value}->{o.destination.value}={o.demand}"
                )

    opt = run.optimization
    if opt is not None:
        cr = opt.constraint_report
        status = opt.optimization_result.solver_status.value
        if cr.legal_fixed_violations:
            violations.append(
                "legal_fixed_violations: "
                + ",".join(e.value for e in cr.legal_fixed_violations)
            )
        # 可達性は「解が得られた正常系（非フォールバック）」でのみ要求する。
        # TIMEOUT/INFEASIBLE（フォールバック）はインカンベント不在で False になり得るため除外
        if not cr.fallback_to_previous and status in ("OPTIMAL", "FEASIBLE"):
            if not cr.local_reachability_satisfied:
                violations.append("local_reachability not satisfied (non-fallback)")
            if run.mode == Mode.OPEN and not cr.boundary_reachability_satisfied:
                violations.append(
                    "boundary_reachability not satisfied (non-fallback, open)"
                )
        for ri in opt.optimization_result.route_importance:
            if not (-1e-9 <= ri.importance <= 1.0 + 1e-9):
                violations.append(
                    f"importance out of [0,1]: {ri.edge_id.value}={ri.importance}"
                )

    return run, violations


@dataclass
class CaseOutcome:
    index: int
    name: str
    graph_name: str
    verdict: str
    downstream: bool
    solver_status: str | None
    fallback: bool
    violations: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.violations)


@dataclass
class FuzzSummary:
    total: int = 0
    failed: int = 0
    triggered: int = 0
    downstream: int = 0
    infeasible: int = 0
    fallback: int = 0
    by_violation: dict[str, int] = field(default_factory=dict)


def run_fuzz(
    graph_arg: str | None,
    *,
    count: int,
    seed: int,
    out_dir: Path,
    save_all: bool = False,
    time_limit: float = 5.0,
) -> tuple[FuzzSummary, list[CaseOutcome]]:
    """``count`` 件のランダムケースを実行し、サマリと各ケースの結果を返す

    違反/例外のあるケース（``save_all`` 指定時は全件）は成果物を保存する。
    ``graph_arg`` がプリセット名/ファイルなら固定、None なら毎回ランダムなプリセットを使う。
    """
    master = random.Random(seed)
    # ランダムローテーションからは重いグラフ（expo）を除外し、所要時間を抑える。
    # 明示的に --graph expo を指定すれば対象にできる
    _heavy = {"expo"}
    presets = [p for p in sorted(graph_builder.PRESETS) if p not in _heavy]
    fixed_base: BuiltGraph | None = None
    fixed_label = ""
    if graph_arg is not None:
        fixed_base = graph_builder.resolve_graph_arg(graph_arg)
        fixed_label = graph_arg if graph_arg in graph_builder.PRESETS else Path(graph_arg).stem

    summary = FuzzSummary()
    outcomes: list[CaseOutcome] = []

    for i in range(count):
        case_seed = master.randint(0, 2**31 - 1)
        rng = random.Random(case_seed)
        if fixed_base is not None:
            base, label = fixed_base, fixed_label
        else:
            label = rng.choice(presets)
            base = graph_builder.get_preset(label)

        determinism = i % 5 == 0
        scen = random_scenario(rng, base, label, i)
        run, violations = check_invariants(
            scen, time_limit=time_limit, determinism=determinism
        )

        summary.total += 1
        if violations:
            summary.failed += 1
            for v in violations:
                key = v.split(":")[0]
                summary.by_violation[key] = summary.by_violation.get(key, 0) + 1

        solver_status: str | None = None
        fallback = False
        verdict = "ERROR"
        downstream = False
        if run is not None:
            verdict = run.detection.verdict_hint.value
            downstream = run.downstream_ran
            if verdict == "TRIGGERED":
                summary.triggered += 1
            if downstream:
                summary.downstream += 1
            if run.optimization is not None:
                solver_status = run.optimization.optimization_result.solver_status.value
                fallback = run.optimization.constraint_report.fallback_to_previous
                if solver_status == "INFEASIBLE":
                    summary.infeasible += 1
                if fallback:
                    summary.fallback += 1

        outcome = CaseOutcome(
            index=i,
            name=scen.name,
            graph_name=label,
            verdict=verdict,
            downstream=downstream,
            solver_status=solver_status,
            fallback=fallback,
            violations=violations,
        )
        outcomes.append(outcome)

        if save_all or violations:
            sub = "fail" if violations else "case"
            case_dir = out_dir / sub / scen.name
            if run is not None:
                report.dump_run(
                    run,
                    scen.built_graph,
                    case_dir,
                    images=True,
                    invariants=violations or ["ok"],
                )
            else:
                # 例外でパイプラインが走らなかったケース。再現用に入力だけ保存する
                case_dir.mkdir(parents=True, exist_ok=True)
                dump_json(graph_builder.to_dict(scen.built_graph), case_dir / "graph.json")
                dump_json(
                    {"seed": case_seed, "violations": violations},
                    case_dir / "error.json",
                )

    # 違反有無に関わらず、実行統計と全ケースの結果を残す（後から件数・内訳を追える）
    dump_json({"summary": summary, "cases": outcomes}, out_dir / "summary.json")
    return summary, outcomes
