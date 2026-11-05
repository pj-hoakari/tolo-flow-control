from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for extra in (ROOT, ROOT / "experiments" / "degraded_operation" / "gain", HERE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _common import md_table  # noqa: E402
from _noise import write_outputs  # noqa: E402
from detection_noise import CADENCES, FLOWS, ONSET, STEP_S, Case, run_case  # noqa: E402

SCENARIOS = ("steady", "surge", "ramp4", "step3", "diurnal", "recover")
THRESHOLDS = {
    "surge": (3.0, 4.0, 5.0, 6.0, 8.0, 10.0),
    "surge10": (10.0, 15.0, 20.0, 30.0),
    "surge_hist": (3.0, 5.0, 8.0, 10.0),
    "surge_early": (10.0, 15.0, 20.0, 30.0),
    "ratio5": (30.0, 50.0, 100.0),
}
LABELS = {
    "surge": "現行（30 分の傾き ÷ 窓の平均、%/分）",
    "surge10": "10 分の傾き ÷ 窓の平均（%/分）",
    "surge_hist": "30 分の傾き ÷ 履歴の平均流量（%/分）",
    "surge_early": "30 分の傾き ÷ 窓の前半の平均（%/分）",
    "ratio5": "直近 5 分の平均 ÷ それより前の平均 − 1（%）",
}
DETECT = ("surge", "ramp4", "step3")
ABSTAIN = ("diurnal", "recover")


def first_breach(rows: list[dict[str, Any]], key: str, threshold: float) -> float | None:
    for row in rows:
        value = row["values"][key]
        if row["minute"] >= ONSET and value is not None and value > threshold:
            return row["minute"] - ONSET
    return None


def summarize(results: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    runs: dict[tuple[str, float, str], list[list[dict[str, Any]]]] = defaultdict(list)
    for r in results:
        c = r["case"]
        runs[(c["scenario"], c["base_flow"], c["cadence"])].append(r["rows"])
    payload: dict[str, Any] = {}
    sections = [
        "# 急増の定式と閾値の比較",
        (
            f"変化の始まりは {ONSET:g} 分。本番の設定。各 {len(next(iter(runs.values())))} 回。"
            "誤成立は一定の流れで閾値を超えた 30 秒の割合（%）。"
            "遅れは変化の始まりから初めて閾値を超えるまでの分（中央値、80 分以内に超えなかった回数）。"
            "反応は、diurnal（120 分で 4 倍）と recover（10 分だけ 0.3 倍、その後もとに戻る）で閾値を一度でも超えた回の割合。"
        ),
    ]
    for key, thresholds in THRESHOLDS.items():
        rows = []
        for threshold in thresholds:
            for flow in FLOWS:
                for cadence in ("cont", "p10"):
                    steady = [q for rr in runs[("steady", flow, cadence)] for q in rr]
                    false_share = sum(
                        q["values"][key] is not None and q["values"][key] > threshold
                        for q in steady
                    ) / len(steady)
                    cells = [f"{threshold:g}", f"{flow:g}", cadence, f"{100 * false_share:.2f}"]
                    entry: dict[str, Any] = {"false_share": false_share}
                    for scenario in DETECT:
                        delays = [
                            first_breach(rr, key, threshold)
                            for rr in runs[(scenario, flow, cadence)]
                        ]
                        hits = [d for d in delays if d is not None]
                        miss = len(delays) - len(hits)
                        entry[scenario] = delays
                        if hits:
                            text = f"{statistics.median(hits):.1f}"
                            cells.append(text + (f"（{miss}）" if miss else ""))
                        else:
                            cells.append(f"なし（{miss}）")
                    for scenario in ABSTAIN:
                        delays = [
                            first_breach(rr, key, threshold)
                            for rr in runs[(scenario, flow, cadence)]
                        ]
                        share = sum(d is not None for d in delays) / len(delays)
                        entry[scenario] = delays
                        cells.append(f"{100 * share:.0f}%")
                    payload[f"{key}|{threshold:g}|{flow:g}|{cadence}"] = entry
                    rows.append(cells)
        sections.append(f"## {LABELS[key]}")
        sections.append(
            md_table(
                [
                    "閾値",
                    "流量（人/分）",
                    "撮り方",
                    "誤成立",
                    "surge の遅れ",
                    "ramp4 の遅れ",
                    "step3 の遅れ",
                    "diurnal の反応",
                    "recover の反応",
                ],
                rows,
            )
        )
    return payload, "\n\n".join(sections) + "\n"


def main() -> None:
    seeds = range(int(os.environ.get("SEEDS", "20")))
    cases = [
        Case(s, f, c, "none", i) for s in SCENARIOS for f in FLOWS for c in CADENCES for i in seeds
    ]
    print(f"{len(cases)} cases, {STEP_S}s steps", file=sys.stderr, flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        results = list(pool.map(run_case, cases, chunksize=2))
    payload, markdown = summarize(results)
    write_outputs("surge_formulation", payload, markdown)


if __name__ == "__main__":
    main()
