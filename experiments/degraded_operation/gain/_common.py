from __future__ import annotations

import json
import math
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devtools.pipeline import PipelineRun, run_pipeline  # noqa: E402
from devtools.scenario_base import PipelineConfigs, Scenario  # noqa: E402
from devtools.scenarios import get_scenario  # noqa: E402
from devtools.scenarios._observation import observation_config  # noqa: E402
from flow_control.detection.triggers import EventKind  # noqa: E402
from flow_control.domain import EdgeID, NodeID  # noqa: E402
from flow_control.optimization.results import DirectionChangeType, SolverStatus  # noqa: E402
from flow_control.rpc.codec import _decode_config  # noqa: E402
from flow_control.service.handler import (  # noqa: E402
    _detection_config,
    _detour_config,
    _forecast_config,
    _optimization_config,
)

RESULTS = ROOT / "experiments" / "degraded_operation" / "results"

PROFILE = os.environ.get("EXPERIMENT_CONFIG", "devtools")
assert PROFILE in ("devtools", "production"), (
    f"EXPERIMENT_CONFIG must be devtools or production, got {PROFILE}"
)


def production_configs(scenario_configs: PipelineConfigs) -> PipelineConfigs:
    proto = observation_config()
    proto.surge_rate_threshold_percent_per_min = 10
    proto.fallback_eta = 0.25
    service = _decode_config(proto)
    assert service.delta_min == 0.5, "production delta_min must be 0.5"
    assert service.optimization_mode.value == "LIGHTWEIGHT", "production mode must be LIGHTWEIGHT"
    assert not service.restriction_proposal_enabled, "production disables restriction proposals"
    optimization = replace(
        _optimization_config(service),
        restriction_proposal_enabled=scenario_configs.optimization.restriction_proposal_enabled,
        tau_danger_threshold=scenario_configs.optimization.tau_danger_threshold,
    )
    return PipelineConfigs(
        detection=_detection_config(service),
        forecasting=_forecast_config(service),
        detour=_detour_config(service),
        optimization=optimization,
    )


def load_scenario(name: str) -> Scenario:
    scenario = get_scenario(name)
    if PROFILE == "devtools":
        return scenario
    return replace(scenario, configs=production_configs(scenario.configs))


def result_name(name: str) -> str:
    return name if PROFILE == "devtools" else f"{name}.{PROFILE}"


SCENARIO_KINDS: dict[str, str] = {
    "reversible-corridor-flip": "direction",
    "stadium-egress-concourse": "direction",
    "station-transfer-peak": "direction",
    "expo-gate-overcrowded": "boundary",
    "expo-incident-resume": "boundary",
    "museum-special-exhibit-limit": "restriction",
    "restriction-undrainable": "restriction",
    "festival-gate-split": "restriction",
    "crossing-detour": "detour",
    "school-north-stair-peak": "detour",
    "multi-route-surge": "detour",
}

DECISION_KINDS = (
    "verdict",
    "triggered",
    "direction",
    "boundary",
    "restriction",
    "restriction_limit",
    "detour",
    "emphasis",
)

OBS_FIELDS = frozenset(
    {
        "flow_rate",
        "stagnation",
        "observed_count",
        "occupancy",
        "occupancy_delta",
        "p90_stagnation",
        "baseline_stagnation",
        "flow_samples",
        "stagnation_samples",
        "directional_flow_samples",
    }
)
CAP_FIELDS = frozenset({"capacity_hint", "danger_capacity"})

CONST_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "delta_min": (("forecasting", "delta_min"), ("optimization", "delta_min")),
    "fallback_baseline": (
        ("detection", "fallback_baseline_stagnation"),
        ("optimization", "fallback_baseline_stagnation"),
    ),
    "ipf_tolerance": (("forecasting", "ipf_tolerance"),),
    "epsilon_0": (
        ("detection", "epsilon_0"),
        ("forecasting", "epsilon_0"),
        ("optimization", "epsilon_0"),
    ),
}


@dataclass(frozen=True)
class Task:
    name: str
    history: bool = True
    common: float = 1.0
    per_point: tuple[tuple[str, float], ...] = ()
    cap_factor: float = 1.0
    const_groups: tuple[str, ...] = ()
    const_k: float = 1.0
    out_k: float = 1.0
    tag: str = ""


def owner_of(obj: object, inherited: str) -> str:
    edge_id = getattr(obj, "edge_id", None)
    if isinstance(edge_id, EdgeID):
        return f"edge:{edge_id.value}"
    node_id = getattr(obj, "node_id", None)
    if isinstance(node_id, NodeID):
        return f"node:{node_id.value}"
    return inherited


def transform(obj: Any, rule: Callable[[str, str], float], attr: str = "", owner: str = "") -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int | float):
        factor = rule(attr, owner)
        return obj if factor == 1.0 else obj * factor
    if isinstance(obj, tuple):
        return tuple(transform(x, rule, attr, owner) for x in obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        own = owner_of(obj, owner)
        return replace(
            obj,
            **{f.name: transform(getattr(obj, f.name), rule, f.name, own) for f in fields(obj)},
        )
    return obj


def leaves(obj: Any, path: str = "", owner: str = "") -> Iterator[tuple[str, str, float]]:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str | datetime):
        return
    if isinstance(obj, int | float):
        yield path, owner, float(obj)
        return
    if isinstance(obj, tuple | list):
        for i, x in enumerate(obj):
            yield from leaves(x, f"{path}[{i}]", owner)
        return
    if is_dataclass(obj) and not isinstance(obj, type):
        own = owner_of(obj, owner)
        for f in fields(obj):
            yield from leaves(getattr(obj, f.name), f"{path}.{f.name}", own)


def last_attr(path: str) -> str:
    return re.findall(r"\.([A-Za-z_0-9]+)", path)[-1]


def make_rule(task: Task) -> Callable[[str, str], float]:
    per_point = dict(task.per_point)

    def rule(attr: str, owner: str) -> float:
        if attr in OBS_FIELDS:
            return task.common * per_point.get(owner, 1.0)
        if attr in CAP_FIELDS:
            return task.cap_factor
        return 1.0

    return rule


def strip_history(scen: Scenario) -> Scenario:
    stats = tuple(
        replace(s, p90_stagnation=None, baseline_stagnation=None, flow_sensitivity_eta=None)
        for s in scen.history_digest.arc_stats
    )
    return replace(scen, history_digest=replace(scen.history_digest, arc_stats=stats))


def scale_configs(scen: Scenario, groups: Sequence[str], k: float) -> Scenario:
    configs = scen.configs
    for group in groups:
        for module, name in CONST_GROUPS[group]:
            sub = getattr(configs, module)
            configs = replace(configs, **{module: replace(sub, **{name: getattr(sub, name) * k})})
    return replace(scen, configs=configs)


def assert_no_unscaled_people_inputs(scen: Scenario) -> None:
    assert not scen.references.by_attribute_tag, f"{scen.name}: references carry people values"
    assert all(e.kind != EventKind.SCHEDULED_INFLOW for e in scen.events), (
        f"{scen.name}: SCHEDULED_INFLOW params present"
    )
    prev = scen.previous_opt_result
    assert prev is None or not prev.restriction_proposal, f"{scen.name}: previous limits present"


def build_task_scenario(task: Task) -> tuple[Scenario, dict[str, Any]]:
    base = load_scenario(task.name)
    assert_no_unscaled_people_inputs(base)
    if not task.history:
        base = strip_history(base)
    rule = make_rule(task)
    parts = {
        "observations": base.observations,
        "history_digest": base.history_digest,
        "graph": base.built_graph.graph,
    }
    new_parts = {key: transform(value, rule) for key, value in parts.items()}
    census: dict[str, Any] = {"scaled": {}, "unchanged_fields": set()}
    for key, part in parts.items():
        old = list(leaves(part, key))
        new = list(leaves(new_parts[key], key))
        assert [p for p, _, _ in old] == [p for p, _, _ in new], f"{key}: leaf layout changed"
        for (path, owner, before), (_, _, after) in zip(old, new, strict=True):
            attr = last_attr(path)
            expected = rule(attr, owner)
            assert math.isclose(after, before * expected, rel_tol=1e-12, abs_tol=1e-15), (
                f"{task.name}: {path} scaled {before}->{after}, expected factor {expected}"
            )
            if expected != 1.0 and before != 0.0:
                census["scaled"][attr] = census["scaled"].get(attr, 0) + 1
            else:
                census["unchanged_fields"].add(attr)
    census["unchanged_fields"] = sorted(census["unchanged_fields"] - set(census["scaled"]))
    scen = replace(
        base,
        observations=new_parts["observations"],
        history_digest=new_parts["history_digest"],
        built_graph=replace(base.built_graph, graph=new_parts["graph"]),
    )
    if task.const_groups:
        scen = scale_configs(scen, task.const_groups, task.const_k)
    return scen, census


def emphasis_ranking(run: PipelineRun) -> list[list[str]]:
    assert run.optimization is not None
    items = [
        (round(ri.importance, 6), f"{ri.edge_id.value}:{ri.direction.value}")
        for ri in run.optimization.optimization_result.route_importance
        if ri.importance > 1e-9
    ]
    groups: dict[float, list[str]] = {}
    for value, key in items:
        groups.setdefault(value, []).append(key)
    return [sorted(groups[v]) for v in sorted(groups, reverse=True)]


def signature(run: PipelineRun, out_k: float) -> dict[str, Any]:
    assert run.optimization is not None
    res = run.optimization.optimization_result
    return {
        "verdict": run.detection.verdict_hint.value,
        "triggered": [
            sorted(e.value for e in run.detection.triggered_edges),
            sorted(n.value for n in run.detection.triggered_nodes),
        ],
        "direction": sorted(
            [d.edge_id.value, d.proposed_direction.value, d.change_type.value]
            for d in res.direction_proposal
            if d.change_type != DirectionChangeType.KEEP
        ),
        "boundary": sorted([b.node_id.value, b.action.value] for b in res.boundary_control),
        "restriction": sorted(
            [p.edge_id.value, p.action.value, p.reason.value] for p in res.restriction_proposal
        ),
        "restriction_limit": sorted(
            [p.edge_id.value, None if p.limit_value is None else f"{p.limit_value / out_k:.6g}"]
            for p in res.restriction_proposal
        ),
        "detour": sorted(
            [d.origin_edge_id.value, *(e.value for e in d.edge_ids)] for d in res.detour_paths
        ),
        "emphasis": emphasis_ranking(run),
    }


def continuous(run: PipelineRun, out_k: float) -> dict[str, Any]:
    assert run.optimization is not None
    assert run.forecast is not None
    res = run.optimization.optimization_result
    return {
        "od": {
            f"{o.origin.value}>{o.destination.value}": o.demand / out_k
            for o in run.forecast.od_matrix
        },
        "throughput": None
        if res.objective_values.throughput is None
        else res.objective_values.throughput / out_k,
        "tau": res.objective_values.tau_star,
        "importance": {
            f"{ri.edge_id.value}:{ri.direction.value}": ri.importance for ri in res.route_importance
        },
    }


def evaluate(task: Task) -> dict[str, Any]:
    scen, census = build_task_scenario(task)
    run = run_pipeline(scen, force=True)
    assert run.optimization is not None, f"{task}: optimization missing"
    assert run.forecast is not None, f"{task}: forecast missing"
    stats = run.optimization.solver_stats
    status = run.optimization.optimization_result.solver_status
    assert not stats.greedy_truncated, f"{task}: greedy truncated by time budget"
    assert status != SolverStatus.TIMEOUT, f"{task}: solver timeout"
    return {
        "task": task,
        "sig": signature(run, task.out_k),
        "cont": continuous(run, task.out_k),
        "diag": {
            "solver": status.value,
            "degraded": run.optimization.constraint_report.degraded_mode,
            "od_pairs_input": stats.od_pairs_input,
            "commodities": stats.commodities_used,
            "demand_all_cut": stats.demand_all_cut,
            "resolution_modes": sorted({r.mode.value for r in run.forecast.estimation_resolution}),
        },
        "census": census,
    }


def _silence_stdout() -> None:
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)


def run_all(tasks: Sequence[Task], label: str) -> list[dict[str, Any]]:
    print(f"[{label}] {len(tasks)} engine runs", file=sys.stderr, flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count(), initializer=_silence_stdout) as pool:
        return list(pool.map(evaluate, tasks, chunksize=4))


def has_kind(sig: dict[str, Any], kind: str) -> bool:
    return bool(sig[kind])


def diff_kinds(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return [k for k in DECISION_KINDS if a[k] != b[k]]


def max_rel(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    worst = 0.0
    for key in keys:
        x, y = a.get(key, 0.0), b.get(key, 0.0)
        worst = max(worst, abs(x - y) / max(abs(x), abs(y), 1e-12))
    return worst


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pct(x: float) -> str:
    return "-" if math.isnan(x) else f"{100 * x:.1f}%"


def frac_cell(hits: int, n: int) -> str:
    if n == 0:
        return "-"
    lo, hi = wilson(hits, n)
    return f"{hits}/{n} ({pct(hits / n)}, CI {pct(lo)}–{pct(hi)})"


def md_table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join(lines)


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Task):
        return {f.name: getattr(obj, f.name) for f in fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, set | frozenset):
        return sorted(to_jsonable(v) for v in obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def write_outputs(name: str, payload: dict[str, Any], markdown: str) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = result_name(name)
    (RESULTS / f"{name}.json").write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if PROFILE == "production":
        head, _, rest = markdown.partition("\n")
        markdown = (
            f"{head}\n\n設定: tolo-observation の defaultFlowConfig。"
            f"ただし通行制限のスイッチとしきい値はシナリオの値を使う（本番では通行制限は無効）。\n{rest}"
        )
    (RESULTS / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {RESULTS / name}.json and .md", file=sys.stderr)
