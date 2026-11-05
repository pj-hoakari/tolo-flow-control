from __future__ import annotations

import math
import os
import random
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT,
    ROOT / "experiments" / "degraded_operation" / "gain",
    Path(__file__).resolve().parent,
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _common import md_table, production_configs  # noqa: E402
from _noise import FLOW_C_30S, OCC_D_30S, write_outputs  # noqa: E402

from devtools import graph_builder  # noqa: E402
from devtools.scenario_base import DEFAULT_TIME, default_configs  # noqa: E402
from flow_control.detection import VerdictHint, detect  # noqa: E402
from flow_control.detection.state import DetectionState  # noqa: E402
from flow_control.detection.triggers import _slope_percent_per_min  # noqa: E402
from flow_control.domain import EdgeID  # noqa: E402
from flow_control.domain.element_state import assess_elements  # noqa: E402
from flow_control.domain.enums import FlowDirection  # noqa: E402
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest  # noqa: E402
from flow_control.domain.observations import ArcFlow, ArcStagnation, Observations  # noqa: E402

STEP_S = 30
DWELL_S = 5.0 / 1.2
HOT = EdgeID("e_in_j1")
OTHER_FLOW = 18.0
PRE_HOURS = 4
RUN_MINUTES = 120
HISTORY_POINTS = 60
ONSET = 40.0
MA_SNAPSHOTS = 6
SHORT_WINDOW_MIN = 10
RECENT_MIN = 5

BUILT = graph_builder.venue()
GRAPH = BUILT.graph
EDGES = [e.edge_id for e in GRAPH.enabled_edges()]
STUDIED_SURGE_THRESHOLD = 10.0
STUDIED_QUEUE_SCORE_THRESHOLD = 5.0
CFG = replace(
    production_configs(default_configs()).detection,
    surge_rate_threshold_percent_per_min=STUDIED_SURGE_THRESHOLD,
    queue_score_threshold=STUDIED_QUEUE_SCORE_THRESHOLD,
)

SCENARIOS = ("steady", "surge", "ramp4", "stagnation", "combined")
FLOWS = (5.0, 18.0, 90.0)
CADENCES = ("cont", "p3", "p5", "p10")
SMOOTHINGS = ("none", "ma3")
SURGE_RULES = ("surge", "surge10", "surge_hist")


@dataclass(frozen=True)
class Case:
    scenario: str
    base_flow: float
    cadence: str
    smoothing: str
    seed: int


def profile(scenario: str, base: float, minute: float) -> tuple[float, float]:
    flow, standing = base, 0.0
    if minute < ONSET:
        return flow, standing
    elapsed = minute - ONSET
    if scenario in ("surge", "combined"):
        flow = base * min(20.0, math.exp(0.15 * elapsed))
    if scenario == "ramp4":
        flow = base * min(4.0, 1.0 + 0.2 * elapsed)
    if scenario == "step3":
        flow = base * 3.0
    if scenario == "diurnal":
        flow = base * min(4.0, 1.0 + 3.0 * elapsed / 120.0)
    if scenario == "recover":
        flow = base * (0.3 if elapsed < 10.0 else 1.0)
    if scenario in ("stagnation", "combined"):
        occ0 = base / 60.0 * DWELL_S
        standing = 3.0 * max(occ0, 0.5) * min(1.0, elapsed / 5.0)
    return flow, standing


def poisson(rng: random.Random, lam: float) -> int:
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def measurements(case: Case, edge: EdgeID, rng: random.Random) -> list[tuple[float, float, float]]:
    base = case.base_flow if edge == HOT else OTHER_FLOW
    scenario = case.scenario if edge == HOT else "steady"
    out = []
    steps = int((PRE_HOURS * 60 + RUN_MINUTES) * 60 / STEP_S)
    for k in range(steps):
        minute = k * STEP_S / 60.0 - PRE_HOURS * 60.0
        rate, standing = profile(scenario, base, minute)
        count = poisson(rng, rate * STEP_S / 60.0)
        moving = count / STEP_S * DWELL_S
        sf = FLOW_C_30S[case.cadence] / math.sqrt(max(rate, 1.0))
        so = OCC_D_30S[case.cadence] / math.sqrt(max(rate / 60.0 * DWELL_S, 1e-6))
        flow = max(0.0, count * (1.0 + sf * rng.gauss(0.0, 1.0)))
        occ = standing + max(0.0, moving * (1.0 + so * rng.gauss(0.0, 1.0)))
        out.append((minute, flow, occ))
    return out


def snapshots(
    stream: list[tuple[float, float, float]], smoothing: str
) -> list[tuple[float, float, float]]:
    snaps = [
        (stream[k][0], stream[k][1] + stream[k - 1][1], (stream[k][2] + stream[k - 1][2]) / 2.0)
        for k in range(1, len(stream))
    ]
    if smoothing == "none":
        return snaps
    smoothed = []
    for k, (minute, _, _) in enumerate(snaps):
        window = snaps[max(0, k - MA_SNAPSHOTS + 1) : k + 1]
        smoothed.append(
            (minute, statistics.mean(s[1] for s in window), statistics.mean(s[2] for s in window))
        )
    return smoothed


def at(minute: float):
    return DEFAULT_TIME + timedelta(minutes=minute)


def run_case(case: Case) -> dict[str, Any]:
    rng = random.Random(f"{case.scenario}|{case.base_flow}|{case.cadence}|{case.seed}")
    per_edge = {e: snapshots(measurements(case, e, rng), case.smoothing) for e in EDGES}
    pre_len = int(PRE_HOURS * 60 * 60 / STEP_S) - 1
    stats = []
    for e in EDGES:
        occs = sorted(s[2] for s in per_edge[e][:pre_len])
        stats.append(
            ArcHistoryStat(
                edge_id=e,
                p90_stagnation=occs[int(0.9 * (len(occs) - 1))],
                baseline_stagnation=statistics.mean(occs),
                available_span_hours=float(PRE_HOURS),
            )
        )
    hot_base_flow = statistics.mean(s[1] for s in per_edge[HOT][:pre_len])
    state = DetectionState()
    rows = []
    for k in range(pre_len, len(per_edge[HOT])):
        minute = per_edge[HOT][k][0]
        server_time = at(minute)
        windows, flows, stags = [], [], []
        for e in EDGES:
            hist = per_edge[e][k - HISTORY_POINTS : k]
            windows.append(
                ArcWindowSeries(
                    edge_id=e,
                    flow_samples=tuple((at(m), f) for m, f, _ in hist),
                    stagnation_samples=tuple((at(m), o) for m, _, o in hist),
                )
            )
            _, f, o = per_edge[e][k]
            flows.append(ArcFlow(edge_id=e, direction=FlowDirection.A_TO_B, flow_rate=f))
            stags.append(ArcStagnation(edge_id=e, stagnation=o))
        obs = Observations(
            observed_at=server_time, arc_flows=tuple(flows), arc_stagnations=tuple(stags)
        )
        digest = HistoryDigest(
            arc_stats=tuple(stats), window_series=tuple(windows), completeness=1.0
        )
        elements = assess_elements(GRAPH, obs, digest, server_time)
        line = elements[HOT].surge_line()
        rate = rate10 = rate_hist = rate_early = ratio5 = None
        if line is not None:
            rate = _slope_percent_per_min(line)
            short = tuple(
                p for p in line if (server_time - p[0]).total_seconds() <= SHORT_WINDOW_MIN * 60 + 1
            )
            rate10 = _slope_percent_per_min(short) if len(short) >= 5 else None
            line_mean = statistics.mean(v for _, v in line)
            if rate is not None and hot_base_flow > 0:
                rate_hist = rate * line_mean / hot_base_flow
            span = (line[-1][0] - line[0][0]).total_seconds()
            older = [v for t, v in line if (line[-1][0] - t).total_seconds() >= span / 2]
            if rate is not None and older and statistics.mean(older) > 0:
                rate_early = rate * line_mean / statistics.mean(older)
            recent = [
                v for t, v in line if (server_time - t).total_seconds() <= RECENT_MIN * 60 + 1
            ]
            before = [v for t, v in line if (server_time - t).total_seconds() > RECENT_MIN * 60 + 1]
            if recent and before and statistics.mean(before) > 0:
                ratio5 = (statistics.mean(recent) / statistics.mean(before) - 1.0) * 100.0
        result = detect(GRAPH, obs, elements, state, (), CFG, server_time)
        triggered = result.verdict_hint == VerdictHint.TRIGGERED
        state = result.new_state if triggered else result.abort_state
        watch = state.watch_state_of(HOT)
        since = None if watch is None else watch.stagnation_watch_since
        threshold = CFG.surge_rate_threshold_percent_per_min
        rows.append(
            {
                "minute": minute,
                "surge": rate is not None and rate > threshold,
                "surge10": rate10 is not None and rate10 > threshold,
                "surge_hist": rate_hist is not None and rate_hist > threshold,
                "stag": since is not None
                and (server_time - since).total_seconds()
                >= CFG.high_stagnation_duration_min * 60 - 1e-6,
                "fire": triggered and HOT in result.triggered_edges,
                "values": {
                    "surge": rate,
                    "surge10": rate10,
                    "surge_hist": rate_hist,
                    "surge_early": rate_early,
                    "ratio5": ratio5,
                },
            }
        )
    return {"case": asdict(case), "rows": rows}


def first_after_onset(rows: list[dict[str, Any]], key: str) -> float | None:
    for row in rows:
        if row["minute"] >= ONSET and row[key]:
            return row["minute"] - ONSET
    return None


def delay_cell(values: list[float | None]) -> str:
    hits = sorted(v for v in values if v is not None)
    miss = len(values) - len(hits)
    if not hits:
        return f"miss {miss}/{len(values)}"
    lo, hi = hits[int(0.1 * (len(hits) - 1))], hits[int(0.9 * (len(hits) - 1))]
    tail = f", miss {miss}" if miss else ""
    return f"{statistics.median(hits):.1f} [{lo:.1f}-{hi:.1f}]{tail}"


def summarize(results: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    groups: dict[tuple[str, float, str, str], list[list[dict[str, Any]]]] = defaultdict(list)
    for r in results:
        c = r["case"]
        groups[(c["scenario"], c["base_flow"], c["cadence"], c["smoothing"])].append(r["rows"])
    steady_rows, delay_rows, payload = [], [], {}
    for key in sorted(groups):
        scenario, flow, cadence, smoothing = key
        runs = groups[key]
        name = f"{scenario}|{flow:g}|{cadence}|{smoothing}"
        if scenario == "steady":
            steps = [q for rows in runs for q in rows]
            hours = len(steps) * STEP_S / 3600
            shares = {k: sum(q[k] for q in steps) / len(steps) for k in (*SURGE_RULES, "stag")}
            fires = sum(q["fire"] for q in steps) / hours
            payload[name] = {"share": shares, "fires_per_hour": fires}
            steady_rows.append(
                [f"{flow:g}", cadence, smoothing]
                + [f"{100 * shares[k]:.2f}" for k in (*SURGE_RULES, "stag")]
                + [f"{fires:.3f}"]
            )
            continue
        cells = {
            k: [first_after_onset(rows, k) for rows in runs] for k in (*SURGE_RULES, "stag", "fire")
        }
        payload[name] = cells
        delay_rows.append(
            [scenario, f"{flow:g}", cadence, smoothing]
            + [delay_cell(cells[k]) for k in (*SURGE_RULES, "stag", "fire")]
        )
    markdown = "\n\n".join(
        [
            "# 判定への揺れの影響（時間を 30 秒ずつ進める）",
            (
                "設定: tolo-observation の defaultFlowConfig。"
                f"変化の始まりは {ONSET:g} 分。各 {len(groups[next(iter(groups))])} 回。"
                "surge は現行の急増判定、surge10 は直近 10 分の傾き ÷ 窓の平均、"
                "surge_hist は 30 分の傾き ÷ 履歴の平均流量。閾値はどれも 10%/分。"
            ),
            "## 一定の流れで成立した割合（%）と発火（回/時）",
            md_table(
                ["流量（人/分）", "撮り方", "手当て", *SURGE_RULES, "停滞警戒", "発火/時"],
                steady_rows,
            ),
            "## 変化の始まりから成立までの分（中央値 [p10-p90]、80 分以内の見逃し）",
            md_table(
                ["場面", "流量（人/分）", "撮り方", "手当て", *SURGE_RULES, "停滞警戒", "発火"],
                delay_rows,
            ),
        ]
    )
    return payload, markdown + "\n"


def main() -> None:
    seeds = range(int(os.environ.get("SEEDS", "20")))
    cases = [
        Case(s, f, c, m, i)
        for s in SCENARIOS
        for f in FLOWS
        for c in CADENCES
        for m in SMOOTHINGS
        for i in seeds
    ]
    print(f"{len(cases)} cases", file=sys.stderr, flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        results = list(pool.map(run_case, cases, chunksize=2))
    payload, markdown = summarize(results)
    write_outputs("detection_noise", payload, markdown)


if __name__ == "__main__":
    main()
