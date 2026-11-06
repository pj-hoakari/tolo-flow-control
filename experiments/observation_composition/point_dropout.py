from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (
    EDGES,
    HOT,
    average,
    detect_series,
    dn,
    point_streams,
    settings,
    write_outputs,
)

GAINS = ((1.5, 0.6), (0.6, 1.5), (1.2, 0.8))
FLOWS = (5.0, 18.0, 90.0)
CADENCES = ("cont", "p10")
MISSING = (20.0, 50.0)


def run(gains, base, cadence, missing, seed):
    rng = random.Random(f"steady|{base}|{gains}|{cadence}|{seed}")
    per_edge = {}
    for edge in EDGES:
        if edge == HOT:
            per_edge[edge] = average(point_streams("steady", base, gains, cadence, rng), missing)
        else:
            streams = point_streams("steady", dn.OTHER_FLOW, (1.0,), cadence, rng)
            per_edge[edge] = average(streams, None)
    return detect_series(per_edge)


def main() -> None:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows, payload = [], []
    for gains in GAINS:
        for base in FLOWS:
            for cadence in CADENCES:
                for missing in (None, MISSING):
                    series = [run(gains, base, cadence, missing, seed) for seed in range(seeds)]
                    cycles = sum(len(s) for s in series)
                    surge = sum(r[2] for s in series for r in s)
                    stagnation = sum(r[3] for s in series for r in s)
                    fires = sum(r[4] for s in series for r in s)
                    peak = statistics.median(
                        max((r[1] for r in s if r[1] is not None), default=0.0) for s in series
                    )
                    label = "なし" if missing is None else f"{missing[0]:.0f}〜{missing[1]:.0f} 分"
                    rows.append(
                        [
                            f"{gains[0]} / {gains[1]}",
                            f"{base:g}",
                            cadence,
                            label,
                            str(cycles),
                            str(surge),
                            str(stagnation),
                            str(fires),
                            f"{peak:.2f}",
                        ]
                    )
                    payload.append(
                        {
                            "gains": gains,
                            "flow": base,
                            "cadence": cadence,
                            "missing": missing,
                            "cycles": cycles,
                            "surge_cycles": surge,
                            "stagnation_cycles": stagnation,
                            "fires": fires,
                            "max_rate_median": peak,
                        }
                    )
    write_outputs(
        "point_dropout",
        {"seeds": seeds, "rows": payload},
        [
            "ゲイン",
            "人/分",
            "撮り方",
            "2 点目の欠け",
            "サイクル",
            "急増",
            "停滞警戒",
            "発火",
            "傾き÷平均の最大の中央値（%/分）",
        ],
        rows,
        "観測点 2 つの平均で、片方が欠けたときの判定",
        settings(seeds),
    )


if __name__ == "__main__":
    main()
