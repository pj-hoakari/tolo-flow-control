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

STALLS = ((20.0, 25.0), (20.0, 30.0), (20.0, 34.0))
FLOWS = (5.0, 18.0, 90.0)
CADENCES = ("cont", "p10")
MODES = {"zero": "流量 0 で渡す", "hold": "標本を除き判定しない"}


def run(base, cadence, stall, mode, seed):
    rng = random.Random(f"stall|{base}|{cadence}|{seed}")
    per_edge = {}
    for edge in EDGES:
        flow = base if edge == HOT else dn.OTHER_FLOW
        per_edge[edge] = average(point_streams("steady", flow, (1.0,), cadence, rng), None)
    if mode == "zero":
        per_edge[HOT] = [
            (m, 0.0, None) if stall[0] <= m < stall[1] else (m, f, o) for m, f, o in per_edge[HOT]
        ]
        return detect_series(per_edge)
    return detect_series(per_edge, skip=stall)


def main() -> None:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows, payload = [], []
    for stall in STALLS:
        for base in FLOWS:
            for cadence in CADENCES:
                for mode, label in MODES.items():
                    after = [
                        [r for r in run(base, cadence, stall, mode, seed) if r[0] >= stall[1]]
                        for seed in range(seeds)
                    ]
                    runs = sum(any(r[2] for r in s) for s in after)
                    cycles = sum(r[2] for s in after for r in s)
                    peak = statistics.median(
                        max((r[1] for r in s if r[1] is not None), default=0.0) for s in after
                    )
                    rows.append(
                        [
                            f"{stall[1] - stall[0]:.0f} 分",
                            f"{base:g}",
                            cadence,
                            label,
                            f"{runs}/{seeds}",
                            str(cycles),
                            f"{peak:.2f}",
                        ]
                    )
                    payload.append(
                        {
                            "stall": stall,
                            "flow": base,
                            "cadence": cadence,
                            "mode": mode,
                            "runs_with_surge": runs,
                            "surge_cycles": cycles,
                            "max_rate_median": peak,
                        }
                    )
    write_outputs(
        "inference_stall",
        {"seeds": seeds, "rows": payload},
        [
            "止まった時間",
            "人/分",
            "撮り方",
            "止まった間の扱い",
            "戻った後に急増が成り立った回",
            "急増のサイクル",
            "戻った後の傾き÷平均の最大の中央値（%/分）",
        ],
        rows,
        "観測点 1 つで推論が止まり、戻ったあとの急増",
        settings(seeds) + "推論は 20 分から止まる。",
    )


if __name__ == "__main__":
    main()
