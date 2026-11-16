from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT / "experiments" / "degraded_operation" / "gain",
    ROOT / "experiments" / "burst_noise",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _common import md_table  # noqa: E402
from _noise import FLOW_C_30S, OCC_D_30S  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
TICK_MIN = 5.0 / 60.0
MEASURE_MIN = 0.5
WARMUP_MIN = 60.0
RUN_MIN = 120.0
ONSET = 40.0
SURGE_MIN = 20.0
DWELL_MIN = 10.0
TRANSIT_MIN = (0.3, 0.7)
SPANS = (1.0, 3.0, 5.0, 10.0)
CADENCES = ("cont", "p10")
NODES = {"小": (5.0, 0.5), "中": (18.0, 2.0), "大": (90.0, 10.0)}
SURGE_FACTOR = 3.0
ROUTE_GAINS = ((1.0, 1.0), (1.2, 0.8))


def stay_rate(base: float, minute: float, scenario: str) -> float:
    if scenario == "accumulate" and ONSET <= minute < ONSET + SURGE_MIN:
        return base * SURGE_FACTOR
    return base


def simulate(transit: float, stay: float, scenario: str, cadence: str, rng: random.Random):
    leaving: list[float] = []
    ticks = int((WARMUP_MIN + RUN_MIN) / TICK_MIN)
    per_measure = round(MEASURE_MIN / TICK_MIN)
    counts: list[float] = []
    arrived = departed = 0
    measurements: list[tuple[float, float]] = []
    routes: list[tuple[float, float, float]] = []
    for k in range(ticks):
        minute = k * TICK_MIN - WARMUP_MIN
        before = len(leaving)
        for _ in range(poisson(rng, transit * TICK_MIN)):
            leaving.append(minute + rng.uniform(*TRANSIT_MIN))
        for _ in range(poisson(rng, stay_rate(stay, minute, scenario) * TICK_MIN)):
            leaving.append(minute + rng.expovariate(1.0 / DWELL_MIN))
        arrived += len(leaving) - before
        before = len(leaving)
        leaving = [t for t in leaving if t > minute]
        departed += before - len(leaving)
        counts.append(float(len(leaving)))
        if len(counts) == per_measure:
            mean = statistics.mean(counts)
            noise = OCC_D_30S[cadence] * math.sqrt(max(mean, 1e-6)) * rng.gauss(0.0, 1.0)
            measurements.append((minute + TICK_MIN, max(0.0, mean + noise)))
            routes.append(
                (
                    minute + TICK_MIN,
                    route_rate(arrived, cadence, rng),
                    route_rate(departed, cadence, rng),
                )
            )
            counts = []
            arrived = departed = 0
    return measurements, routes


def route_rate(count: int, cadence: str, rng: random.Random) -> float:
    rate = count / MEASURE_MIN
    relative = FLOW_C_30S[cadence] / math.sqrt(max(rate, 1.0))
    return max(0.0, rate * (1.0 + relative * rng.gauss(0.0, 1.0)))


def conservation(
    routes: list[tuple[float, float, float]], gains: tuple[float, float]
) -> list[tuple[float, float]]:
    return [(m, gains[0] * a - gains[1] * d) for m, a, d in routes if m >= 0.0]


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def expected_rates(stay: float, scenario: str) -> dict[float, float]:
    occupied = stay * DWELL_MIN
    step = 1.0 / 600.0
    rates: dict[float, float] = {}
    for k in range(int((WARMUP_MIN + RUN_MIN) / step) + 1):
        t = k * step - WARMUP_MIN
        half = round(t * 2.0) / 2.0
        if t >= 0.0 and abs(t - half) < step / 2.0:
            rates[half] = stay_rate(stay, t, scenario) - occupied / DWELL_MIN
        occupied += (stay_rate(stay, t, scenario) - occupied / DWELL_MIN) * step
    return rates


def slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    mt = statistics.mean(p[0] for p in points)
    mv = statistics.mean(p[1] for p in points)
    var = sum((p[0] - mt) ** 2 for p in points)
    if var <= 0.0:
        return None
    return sum((p[0] - mt) * (p[1] - mv) for p in points) / var


def estimates(measurements: list[tuple[float, float]], span: float) -> list[tuple[float, float]]:
    out = []
    start = 0
    for i, (end, _) in enumerate(measurements):
        while measurements[start][0] <= end - span + 1e-9:
            start += 1
        if end < 0.0:
            continue
        value = slope(measurements[start : i + 1])
        if value is not None:
            out.append((end, value))
    return out


def first_reach(series: list[tuple[float, float]], after: float, level: float) -> float | None:
    for minute, value in series:
        if minute >= after and value >= level:
            return minute - after
    return None


def methods():
    for span in SPANS:
        yield f"人数の傾き {span:g} 分", span, lambda run, span=span: estimates(run[0], span)
    for gains in ROUTE_GAINS:
        label = f"保存則（ゲイン {gains[0]:g} / {gains[1]:g}）"
        yield label, None, lambda run, gains=gains: conservation(run[1], gains)


def summarize(series_runs, truth, peak):
    steady = [v for series in series_runs["steady"] for _, v in series]
    errors, delays, release_negative = [], [], []
    for series in series_runs["accumulate"]:
        errors.extend((v - truth[round(m * 2) / 2.0]) ** 2 for m, v in series)
        delays.append(first_reach(series, ONSET, peak / 2.0))
        release_negative.extend(
            v < 0.0 for m, v in series if ONSET + SURGE_MIN + 2.0 <= m < ONSET + SURGE_MIN + 12.0
        )
    reached = [d for d in delays if d is not None]
    return {
        "steady_sd": statistics.pstdev(steady),
        "steady_positive_mean": statistics.mean(max(0.0, v) for v in steady),
        "accumulate_rmse": math.sqrt(statistics.mean(errors)),
        "half_peak_delay_median": statistics.median(reached) if reached else None,
        "half_peak_reached": len(reached),
        "release_negative_share": statistics.mean(release_negative),
    }


def main() -> None:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rows, payload = [], []
    for name, (transit, stay) in NODES.items():
        peak = stay * (SURGE_FACTOR - 1.0)
        truth = expected_rates(stay, "accumulate")
        for cadence in CADENCES:
            runs = {
                scenario: [
                    simulate(
                        transit,
                        stay,
                        scenario,
                        cadence,
                        random.Random(f"{name}|{scenario}|{cadence}|{seed}"),
                    )
                    for seed in range(seeds)
                ]
                for scenario in ("steady", "accumulate")
            }
            mean_people = statistics.mean(v for run in runs["steady"] for _, v in run[0])
            for label, span, method in methods():
                result = summarize(
                    {scenario: [method(run) for run in group] for scenario, group in runs.items()},
                    truth,
                    peak,
                )
                delay = result["half_peak_delay_median"]
                rows.append(
                    [
                        name,
                        f"{transit:g} / {stay:g}",
                        f"{mean_people:.1f}",
                        cadence,
                        label,
                        f"{result['steady_sd']:.2f}",
                        f"{result['steady_positive_mean']:.2f}",
                        f"{result['accumulate_rmse']:.2f}",
                        "-"
                        if delay is None
                        else f"{delay:.1f} 分（{result['half_peak_reached']}/{seeds}）",
                        f"{result['release_negative_share']:.0%}",
                    ]
                )
                payload.append(
                    {
                        "node": name,
                        "transit_per_min": transit,
                        "stay_per_min": stay,
                        "mean_people": mean_people,
                        "cadence": cadence,
                        "method": label,
                        "span_min": span,
                        **result,
                    }
                )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "node_occupancy_trend.json").write_text(
        json.dumps({"seeds": seeds, "rows": payload}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    header = [
        "ノード",
        "通過 / 滞在の到着（人/分）",
        "平均人数",
        "撮り方",
        "求め方",
        "一定の流れでの標準偏差（人/分）",
        "一定の流れでの正の部分の平均（人/分）",
        "増減する場面の二乗平均誤差（人/分）",
        "真の最大の半分に届くまで（届いた回）",
        "はける間に負になった割合",
    ]
    note = (
        f"人数の傾きは、30 秒ごとの計測（窓の平均人数に揺れを加える）から、直近の幅の最小二乗の傾きを占有量変化とする。"
        f"保存則は、同じ人の出入りを数えた入りと出のルートの 30 秒の流量（人/分）の差とする。"
        f"滞在の到着は {ONSET:g} 分から {SURGE_MIN:g} 分のあいだ {SURGE_FACTOR:g} 倍にし、"
        f"滞在時間は平均 {DWELL_MIN:g} 分の指数分布、通過は {TRANSIT_MIN[0]}〜{TRANSIT_MIN[1]} 分とした。"
        f"はける間は {ONSET + SURGE_MIN + 2:g}〜{ONSET + SURGE_MIN + 12:g} 分。各条件 {seeds} 回。"
    )
    markdown = "\n".join(
        ["# ノードの占有量変化を人数の傾きで作るときの幅", "", note, "", md_table(header, rows), ""]
    )
    (RESULTS / "node_occupancy_trend.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
