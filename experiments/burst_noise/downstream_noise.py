from __future__ import annotations

import math
import os
import random
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

os.environ.setdefault("EXPERIMENT_CONFIG", "production")
ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT,
    ROOT / "experiments" / "degraded_operation" / "gain",
    Path(__file__).resolve().parent,
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _common import (  # noqa: E402
    PROFILE,
    SCENARIO_KINDS,
    continuous,
    diff_kinds,
    load_scenario,
    md_table,
    signature,
)
from _noise import FLOW_C_60S, OCC_D_60S, write_outputs  # noqa: E402
from detection_noise import (  # noqa: E402
    STUDIED_QUEUE_SCORE_THRESHOLD,
    STUDIED_SURGE_THRESHOLD,
)

from devtools.pipeline import run_pipeline  # noqa: E402

WIDTH = 3
CADENCES = ("cont", "p3", "p5", "p10", "tiny")
MITIGATIONS = ("none", "obs_ma3", "fc_mean3")


@dataclass(frozen=True)
class Case:
    scenario: str
    cadence: str
    mitigation: str
    seed: int


def eps(value: float, coef: float, rng: random.Random) -> float:
    if coef == 0.0 or value <= 0.0:
        return 0.0
    return coef / math.sqrt(max(value, 1.0)) * rng.gauss(0.0, 1.0)


def noisy_series(samples, coef: float, rng: random.Random) -> list:
    return [(t, max(0.0, v * (1.0 + eps(v, coef, rng)))) for t, v in samples]


def smooth(samples: list) -> list:
    return [
        (t, statistics.mean(v for _, v in samples[max(0, i - WIDTH + 1) : i + 1]))
        for i, (t, _) in enumerate(samples)
    ]


def current_of(seq: list, mitigation: str) -> float:
    if mitigation == "none":
        return seq[-1][1]
    return statistics.mean(v for _, v in seq[-WIDTH:])


def past_only(samples, observed_at) -> list:
    samples = list(samples)
    if samples and samples[-1][0] >= observed_at:
        return samples[:-1]
    return samples


def perturb(scen, cadence: str, mitigation: str, rng: random.Random):
    fc, oc = FLOW_C_60S[cadence], OCC_D_60S[cadence]
    obs = scen.observations
    observed_at = obs.observed_at
    flows_by_edge: dict[Any, list] = defaultdict(list)
    for f in obs.arc_flows:
        flows_by_edge[f.edge_id].append(f)
    windows, current_dir, total_ratio = [], {}, {}
    for w in scen.history_digest.window_series:
        edge_flows = flows_by_edge.get(w.edge_id, [])
        total_now = sum(f.flow_rate for f in edge_flows)
        past = past_only(w.flow_samples, observed_at)
        seq = noisy_series(past + ([(observed_at, total_now)] if edge_flows else []), fc, rng)
        sent = smooth(seq) if mitigation == "obs_ma3" else seq
        if edge_flows and total_now > 0:
            total_ratio[w.edge_id] = current_of(seq, mitigation) / total_now
        directional = None
        if w.directional_flow_samples is not None:
            directional = []
            for direction, samples in w.directional_flow_samples:
                now = [f.flow_rate for f in edge_flows if f.direction == direction]
                dpast = past_only(samples, observed_at)
                dseq = noisy_series(dpast + ([(observed_at, now[0])] if now else []), fc, rng)
                dsent = smooth(dseq) if mitigation == "obs_ma3" else dseq
                if now:
                    current_dir[(w.edge_id, direction)] = current_of(dseq, mitigation)
                    dsent = dsent[:-1]
                directional.append((direction, tuple(dsent)))
            directional = tuple(directional)
        windows.append(
            replace(
                w,
                flow_samples=tuple(sent[:-1] if edge_flows else sent),
                stagnation_samples=tuple(noisy_series(w.stagnation_samples, oc, rng)),
                directional_flow_samples=directional,
            )
        )
    scale = 1.0 / math.sqrt(WIDTH) if mitigation != "none" else 1.0

    def jitter(value: float, coef: float) -> float:
        return max(0.0, value * (1.0 + scale * eps(value, coef, rng)))

    def current_flow(f):
        if (f.edge_id, f.direction) in current_dir:
            return replace(f, flow_rate=current_dir[(f.edge_id, f.direction)])
        if f.edge_id in total_ratio:
            return replace(f, flow_rate=f.flow_rate * total_ratio[f.edge_id])
        return replace(f, flow_rate=jitter(f.flow_rate, fc))

    new_obs = replace(
        obs,
        arc_flows=tuple(current_flow(f) for f in obs.arc_flows),
        arc_stagnations=tuple(
            replace(s, stagnation=jitter(s.stagnation, oc)) for s in obs.arc_stagnations
        ),
        arc_scalar_flows=tuple(
            replace(s, observed_count=jitter(s.observed_count, fc)) for s in obs.arc_scalar_flows
        ),
        node_occupancies=tuple(
            n if n.occupancy is None else replace(n, occupancy=jitter(n.occupancy, oc))
            for n in obs.node_occupancies
        ),
    )
    return replace(
        scen,
        observations=new_obs,
        history_digest=replace(scen.history_digest, window_series=tuple(windows)),
    )


def evaluate(case: Case) -> dict[str, Any]:
    loaded = load_scenario(case.scenario)
    base = replace(
        loaded,
        configs=replace(
            loaded.configs,
            detection=replace(
                loaded.configs.detection,
                surge_rate_threshold_percent_per_min=STUDIED_SURGE_THRESHOLD,
                queue_score_threshold=STUDIED_QUEUE_SCORE_THRESHOLD,
            ),
        ),
    )
    rng = random.Random(f"{case.scenario}|{case.cadence}|{case.mitigation}|{case.seed}")
    clean = case.cadence == "cont" and case.mitigation == "none"
    run = run_pipeline(
        base if clean else perturb(base, case.cadence, case.mitigation, rng), force=True
    )
    return {"case": asdict(case), "sig": signature(run, 1.0), "cont": continuous(run, 1.0)}


def quantile(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[int(p * (len(values) - 1))]


def weighted_od(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys) / max(
        sum(abs(v) for v in b.values()), 1e-12
    )


def relative(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a - b) / max(abs(a), abs(b), 1e-12)


def limit_relative(sig: dict[str, Any], ref: dict[str, Any]) -> float | None:
    a = {e: float(v) for e, v in sig["restriction_limit"] if v is not None}
    b = {e: float(v) for e, v in ref["restriction_limit"] if v is not None}
    return max((relative(a[k], b[k]) or 0.0 for k in set(a) & set(b)), default=None)


def pct(values: list[float]) -> str:
    if not values:
        return "-"
    return f"{100 * quantile(values, 0.5):.0f}/{100 * quantile(values, 0.9):.0f}"


def summarize(results: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    base = {
        r["case"]["scenario"]: r
        for r in results
        if r["case"]["cadence"] == "cont" and r["case"]["mitigation"] == "none"
    }
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        c = r["case"]
        if not (c["cadence"] == "cont" and c["mitigation"] == "none"):
            groups[(c["scenario"], c["cadence"], c["mitigation"])].append(r)
    order = {c: i for i, c in enumerate(CADENCES)}
    rows, payload = [], {}
    for key in sorted(groups, key=lambda k: (k[0], order[k[1]], k[2])):
        scenario, cadence, mitigation = key
        runs, ref = groups[key], base[scenario]
        flips = sum(r["sig"]["verdict"] != ref["sig"]["verdict"] for r in runs)
        other = sum(
            bool(
                set(diff_kinds(r["sig"], ref["sig"]))
                - {"verdict", "triggered", "emphasis", "restriction_limit"}
            )
            for r in runs
        )
        od = [weighted_od(r["cont"]["od"], ref["cont"]["od"]) for r in runs]
        thr = [
            x
            for x in (relative(r["cont"]["throughput"], ref["cont"]["throughput"]) for r in runs)
            if x is not None
        ]
        lim = [x for x in (limit_relative(r["sig"], ref["sig"]) for r in runs) if x is not None]
        payload["|".join(key)] = {
            "runs": len(runs),
            "verdict_flips": flips,
            "other_decision_changes": other,
            "od_weighted": od,
            "throughput": thr,
            "restriction_limit": lim,
        }
        rows.append(
            [
                scenario,
                cadence,
                mitigation,
                f"{flips}/{len(runs)}",
                f"{other}/{len(runs)}",
                pct(od),
                pct(thr),
                pct(lim),
            ]
        )
    markdown = "\n\n".join(
        [
            "# 今回値を使う処理への揺れの影響（devtools のシナリオ）",
            (
                f"設定: {PROFILE}。揺れのない連続観測の出力と比べた。"
                "obs_ma3 は Observation が 3 点の移動平均を送る案、fc_mean3 は flow-control が今回値を直近 3 点の平均にする案。"
                "tiny は約 1% の揺れで、需要推定の感度を見るためのもの。値は中央値/p90（%）。"
            ),
            md_table(
                [
                    "シナリオ",
                    "撮り方",
                    "手当て",
                    "判定の変化",
                    "そのほかの決定の変化",
                    "需要（重み付き）",
                    "通過量",
                    "通行制限の上限値",
                ],
                rows,
            ),
        ]
    )
    return payload, markdown + "\n"


def main() -> None:
    seeds = range(int(os.environ.get("SEEDS", "30")))
    cases = [Case(s, "cont", "none", 0) for s in SCENARIO_KINDS]
    for s in SCENARIO_KINDS:
        for c in CADENCES:
            for m in MITIGATIONS:
                if c == "cont" and m == "none":
                    continue
                if c == "tiny" and m != "none":
                    continue
                cases += [Case(s, c, m, i) for i in (range(1) if c == "cont" else seeds)]
    print(f"{len(cases)} runs", file=sys.stderr, flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        results = list(pool.map(evaluate, cases, chunksize=2))
    payload, markdown = summarize(results)
    write_outputs(
        f"downstream_noise.{PROFILE}" if PROFILE != "production" else "downstream_noise",
        payload,
        markdown,
    )


if __name__ == "__main__":
    main()
