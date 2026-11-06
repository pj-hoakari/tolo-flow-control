from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT,
    ROOT / "experiments" / "degraded_operation" / "gain",
    ROOT / "experiments" / "burst_noise",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import detection_noise as dn  # noqa: E402
from _common import md_table, production_configs  # noqa: E402
from _noise import FLOW_C_30S, OCC_D_30S  # noqa: E402

from devtools.scenario_base import default_configs  # noqa: E402
from flow_control.detection import VerdictHint, detect  # noqa: E402
from flow_control.detection.state import DetectionState  # noqa: E402
from flow_control.detection.triggers import _slope_percent_per_min  # noqa: E402
from flow_control.domain.element_state import assess_elements  # noqa: E402
from flow_control.domain.enums import FlowDirection  # noqa: E402
from flow_control.domain.history import ArcHistoryStat, ArcWindowSeries, HistoryDigest  # noqa: E402
from flow_control.domain.observations import ArcFlow, ArcStagnation, Observations  # noqa: E402

CFG = production_configs(default_configs()).detection
RESULTS = Path(__file__).resolve().parent / "results"
EDGES, HOT, GRAPH = dn.EDGES, dn.HOT, dn.GRAPH
PRE_LEN = int(dn.PRE_HOURS * 60 * 60 / dn.STEP_S) - 1

Snapshot = tuple[float, float, float | None]


def point_streams(
    scenario: str, base: float, gains: tuple[float, ...], cadence: str, rng: random.Random
) -> list[list[tuple[float, float, float]]]:
    steps = int((dn.PRE_HOURS * 60 + dn.RUN_MINUTES) * 60 / dn.STEP_S)
    out: list[list[tuple[float, float, float]]] = [[] for _ in gains]
    for k in range(steps):
        minute = k * dn.STEP_S / 60.0 - dn.PRE_HOURS * 60.0
        rate, standing = dn.profile(scenario, base, minute)
        count = dn.poisson(rng, rate * dn.STEP_S / 60.0)
        moving = count / dn.STEP_S * dn.DWELL_S
        sf = FLOW_C_30S[cadence] / math.sqrt(max(rate, 1.0))
        so = OCC_D_30S[cadence] / math.sqrt(max(rate / 60.0 * dn.DWELL_S, 1e-6))
        for i, gain in enumerate(gains):
            flow = gain * max(0.0, count * (1.0 + sf * rng.gauss(0.0, 1.0)))
            occ = gain * (standing + max(0.0, moving * (1.0 + so * rng.gauss(0.0, 1.0))))
            out[i].append((minute, flow, occ))
    return [dn.snapshots(stream, "none") for stream in out]


def average(
    streams: list[list[tuple[float, float, float]]], missing: tuple[float, float] | None
) -> list[Snapshot]:
    composed: list[Snapshot] = []
    for k in range(len(streams[0])):
        minute = streams[0][k][0]
        live = [
            stream[k]
            for i, stream in enumerate(streams)
            if not (i == 1 and missing is not None and missing[0] <= minute < missing[1])
        ]
        composed.append(
            (minute, statistics.mean(v[1] for v in live), statistics.mean(v[2] for v in live))
        )
    return composed


def history_stats(per_edge: dict[str, list[Snapshot]]) -> list[ArcHistoryStat]:
    stats = []
    for edge in EDGES:
        occs = sorted(s[2] for s in per_edge[edge][:PRE_LEN] if s[2] is not None)
        stats.append(
            ArcHistoryStat(
                edge_id=edge,
                p90_stagnation=occs[int(0.9 * (len(occs) - 1))],
                baseline_stagnation=statistics.mean(occs),
                available_span_hours=float(dn.PRE_HOURS),
            )
        )
    return stats


def detect_series(
    per_edge: dict[str, list[Snapshot]], skip: tuple[float, float] | None = None
) -> list[tuple[float, float | None, bool, bool, bool]]:
    def skipped(minute: float) -> bool:
        return skip is not None and skip[0] <= minute < skip[1]

    stats = history_stats(per_edge)
    state = DetectionState()
    rows = []
    for k in range(PRE_LEN, len(per_edge[HOT])):
        minute = per_edge[HOT][k][0]
        if skipped(minute):
            continue
        at = dn.at(minute)
        windows, flows, stags = [], [], []
        for edge in EDGES:
            hist = per_edge[edge][k - dn.HISTORY_POINTS : k]
            if edge == HOT:
                hist = [h for h in hist if not skipped(h[0])]
            windows.append(
                ArcWindowSeries(
                    edge_id=edge,
                    flow_samples=tuple((dn.at(m), f) for m, f, _ in hist),
                    stagnation_samples=tuple((dn.at(m), o) for m, _, o in hist if o is not None),
                )
            )
            _, flow, occ = per_edge[edge][k]
            flows.append(ArcFlow(edge_id=edge, direction=FlowDirection.A_TO_B, flow_rate=flow))
            if occ is not None:
                stags.append(ArcStagnation(edge_id=edge, stagnation=occ))
        obs = Observations(observed_at=at, arc_flows=tuple(flows), arc_stagnations=tuple(stags))
        digest = HistoryDigest(
            arc_stats=tuple(stats), window_series=tuple(windows), completeness=1.0
        )
        elements = assess_elements(GRAPH, obs, digest, at)
        line = elements[HOT].surge_line()
        rate = _slope_percent_per_min(line) if line is not None else None
        result = detect(GRAPH, obs, elements, state, (), CFG, at)
        triggered = result.verdict_hint == VerdictHint.TRIGGERED
        state = result.new_state if triggered else result.abort_state
        watch = state.watch_state_of(HOT)
        since = None if watch is None else watch.stagnation_watch_since
        stagnation = (
            since is not None
            and (at - since).total_seconds() >= CFG.high_stagnation_duration_min * 60 - 1e-6
        )
        surge = rate is not None and rate > CFG.surge_rate_threshold_percent_per_min
        rows.append((minute, rate, surge, stagnation, triggered and HOT in result.triggered_edges))
    return rows


def write_outputs(
    name: str, payload: dict, header: list[str], rows: list[list[str]], title: str, note: str
) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    markdown = "\n".join([f"# {title}", "", note, "", md_table(header, rows), ""])
    (RESULTS / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {RESULTS / name}.json and .md", file=sys.stderr)


def settings(seeds: int) -> str:
    return (
        f"急増の閾値 {CFG.surge_rate_threshold_percent_per_min}%/分、"
        f"β {CFG.beta}、停滞の継続 {CFG.high_stagnation_duration_min} 分、"
        f"キューのしきい値 {CFG.queue_score_threshold}、各条件 {seeds} 回。"
    )
