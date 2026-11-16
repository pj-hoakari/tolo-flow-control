from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for extra in (ROOT, ROOT / "experiments" / "degraded_operation" / "gain", HERE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _common import md_table  # noqa: E402
from _noise import write_outputs  # noqa: E402
from detection_noise import CFG, Case, run_case  # noqa: E402

SCENARIOS = ("combined", "ramp4stag")
FLOW = 18.0
SEEDS = range(10)
THRESHOLDS = ((10.0, 5.0), (5.0, 5.0), (5.0, 20.0), (5.0, 80.0))


def fires(case: Case, surge: float, queue: float) -> dict[str, Any]:
    cfg = replace(CFG, surge_rate_threshold_percent_per_min=surge, queue_score_threshold=queue)
    minutes = [row["minute"] for row in run_case(case, cfg)["rows"] if row["fire"]]
    return {
        "seed": case.seed,
        "fires": len(minutes),
        "gaps_min": [b - a for a, b in pairwise(minutes)],
    }


def main() -> None:
    jobs = [
        (Case(s, FLOW, "cont", "none", i), surge, queue)
        for s in SCENARIOS
        for surge, queue in THRESHOLDS
        for i in SEEDS
    ]
    with ProcessPoolExecutor() as pool:
        runs = list(pool.map(fires, *zip(*jobs, strict=True)))
    payload: dict[str, Any] = {}
    rows = []
    for (case, surge, queue), run in zip(jobs, runs, strict=True):
        payload.setdefault(f"{case.scenario}|{surge:g}|{queue:g}", []).append(run)
    for key, group in payload.items():
        scenario, surge, queue = key.split("|")
        counts = [r["fires"] for r in group]
        gaps = sorted({g for r in group for g in r["gaps_min"]})
        rows.append(
            [
                scenario,
                surge,
                queue,
                f"{min(counts)}-{max(counts)}",
                ", ".join(f"{g:g}" for g in gaps) or "-",
            ]
        )
    markdown = "\n\n".join(
        [
            "# クールタイム中の再発火",
            (
                f"流量 {FLOW:g} 人/分、撮り方 cont、手当てなし、各 {len(SEEDS)} 回。"
                "ramp4stag は ramp4 の流量に stagnation の停滞の積み上がりを重ねた場面。"
            ),
            md_table(
                [
                    "場面",
                    "急増の閾値",
                    "キューのしきい値",
                    f"発火の回数（{len(SEEDS)} 回の範囲）",
                    "発火の間隔（分、出た値）",
                ],
                rows,
            ),
        ]
    )
    write_outputs("cooldown_refire", payload, markdown + "\n")


if __name__ == "__main__":
    main()
