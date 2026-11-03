import json
import math
import warnings
from pathlib import Path

import numpy as np

RESULTS = Path(__file__).resolve().parents[1] / "results"
BASE_SEED = 20261103
SEEDS = 100
DAY_MIN = 480
BIN_S = 30
BINS = DAY_MIN * 60 // BIN_S
SMOOTH_MIN = 3.0
VIEW_LEN = 20.0
WIDTH = 4.0
CELLS = 10
DT = 1.0
V_FREE = 1.34
K_JAM = 5.4
K_CRIT_TRI = 0.9
RHO = 1.0
KNEE_RATIO = 1.5
KNEE_MIN_WINDOWS = 10
KNEE_RUN_MIN = 5.0
DETECT_BEFORE = 15.0
DETECT_AFTER = 30.0
FA_BUDGET = 0.05
DETECT_FLOOR = 0.95
DAYS = [*(f"h2_{i}" for i in range(7)), *(f"h1_{i}" for i in range(7))]
DAYS += ["normal", "ramp", "dwell_low", "dwell_peak"]
H2 = slice(0, 7)
H1 = slice(7, 14)
TEST = {name: DAYS.index(name) for name in ("normal", "ramp", "dwell_low", "dwell_peak")}
FDS = ("triangular", "greenshields")
SEVERITIES = (0.5, 0.7, 0.85, 0.95)
GAINS = (0.5, 0.7, 1.0, 1.4, 2.0)
WINDOWS = (30, 60)
KAPPAS = (1.2, 1.3, 1.5, 2.0, 2.5, 3.0)
PLEVELS = (0.8, 0.9, 0.95)
DRIFTS = (0.7, 0.85, 1.0, 1.2, 1.4)
RATIOS = (0.5, 2.0)
MISSES = (
    (0.0, 0.0),
    (0.3, 0.0),
    (0.6, 0.0),
    (0.9, 0.0),
    (1.2, 0.0),
    (0.0, 0.3),
    (0.0, 0.6),
    (0.3, 0.3),
)
MISSES += ((0.6, 0.6),)


def rng_for(*key):
    return np.random.default_rng([BASE_SEED, *key])


def q_max(fd):
    return V_FREE * K_CRIT_TRI if fd == "triangular" else V_FREE * K_JAM / 4


def send_recv(fd, k):
    k = np.clip(k, 0.0, K_JAM)
    if fd == "triangular":
        qc = q_max(fd)
        wave = qc / (K_JAM - K_CRIT_TRI)
        return np.minimum(V_FREE * k, qc), np.minimum(qc, wave * (K_JAM - k))
    qk = V_FREE * k * (1 - k / K_JAM)
    free = k < K_JAM / 2
    return np.where(free, qk, q_max(fd)), np.where(free, q_max(fd), qk)


def plateau_ratio(fd, sev):
    per_m = sev * q_max(fd)
    if fd == "triangular":
        k_eq = K_JAM - per_m / (q_max(fd) / (K_JAM - K_CRIT_TRI))
    else:
        k_eq = K_JAM * (1 + math.sqrt(1 - 4 * per_m / (V_FREE * K_JAM))) / 2
    return k_eq * V_FREE / per_m


def free_ratio_at(fd, frac_of_cell):
    if fd == "triangular":
        return 1.0
    per_m = frac_of_cell * q_max(fd)
    k = K_JAM * (1 - math.sqrt(1 - 4 * per_m / (V_FREE * K_JAM))) / 2
    return 1 / (1 - k / K_JAM)


def build_demand():
    rng = rng_for(0)
    t = np.arange(DAY_MIN, dtype=float)
    shape = (SEEDS, len(DAYS))
    centers = np.stack([rng.uniform(90, 150, shape), rng.uniform(300, 360, shape)], -1)
    widths = rng.uniform(30, 50, (*shape, 2))
    amps = rng.uniform(0.7, 1.0, (*shape, 2))
    bumps = (
        amps[..., None] * np.exp(-0.5 * ((t - centers[..., None]) / widths[..., None]) ** 2)
    ).sum(-2)
    base = 0.35 + 0.65 * bumps / bumps.max(-1, keepdims=True)
    periods = rng.uniform(10, 60, (*shape, 3))
    phases = rng.uniform(0, 2 * np.pi, (*shape, 3))
    noise = 1 + 0.03 * np.sin(2 * np.pi * t / periods[..., None] + phases[..., None]).sum(-2)
    peak = rng.uniform(0.45, 0.8, shape)
    peak[:, [DAYS.index("h1_5"), DAYS.index("h1_6")]] = rng.uniform(1.05, 1.2, (SEEDS, 2))
    peak[:, TEST["ramp"]] = rng.uniform(0.45, 0.65, SEEDS)
    peak[:, TEST["dwell_low"]] = rng.uniform(0.3, 0.4, SEEDS)
    peak[:, TEST["dwell_peak"]] = rng.uniform(0.7, 0.8, SEEDS)
    frac = peak[..., None] * base
    start = rng.uniform(150, 300, SEEDS)
    rise = rng.uniform(15, 60, SEEDS)
    over = rng.uniform(1.05, 1.4, SEEDS)
    ramp_meta = []
    for s in range(SEEDS):
        xp = [start[s], start[s] + rise[s], start[s] + rise[s] + 30, start[s] + rise[s] + 45]
        ramp = np.interp(t, xp, [0.6, over[s], over[s], 0.3], left=0.0, right=0.0)
        frac[s, TEST["ramp"]] = np.maximum(frac[s, TEST["ramp"]], ramp)
        ramp_meta.append(
            {"start": start[s], "rise": rise[s], "overload": over[s], "hold_end": xp[2]}
        )
    frac *= noise
    booth = np.zeros_like(frac)
    dwell = np.ones(shape)
    for name in ("dwell_low", "dwell_peak"):
        i = TEST[name]
        booth[:, i, 60:420] = rng.uniform(0.3, 0.6, SEEDS)[:, None]
        dwell[:, i] = rng.uniform(2, 6, SEEDS)
    onset = np.array([np.argmax(frac[s, TEST["ramp"]] > 1.0) + 1.0 for s in range(SEEDS)])
    assert (frac[:, TEST["ramp"]].max(-1) > 1.0).all(), "every ramp day exceeds capacity"
    assert (frac[:, H2].max(-1).max(-1) < 0.9).all(), "H2 history stays below 0.9 C_b"
    assert frac[:, [TEST["normal"], TEST["dwell_low"], TEST["dwell_peak"]]].max() < 0.9, (
        "non-ramp test days stay below capacity"
    )
    assert (frac[:, H1].max(-1).max(-1) > 1.0).all(), "H1 history touches capacity"
    h2_p90 = np.quantile(frac[:, H2].reshape(SEEDS, -1), 0.9, axis=1)
    assert (frac[:, TEST["dwell_low"]].max(-1) < h2_p90).all(), "low dwell day stays below H2 p90"
    assert (frac[:, TEST["dwell_peak"]].max(-1) > h2_p90).all(), "peak dwell day exceeds H2 p90"
    return frac, booth, dwell, onset, ramp_meta


def simulate(fd, sev, frac, booth, dwell):
    rows = frac.shape[0] * frac.shape[1]
    frac = frac.reshape(rows, DAY_MIN)
    booth = booth.reshape(rows, DAY_MIN)
    release_rate = 1.0 / (dwell.reshape(rows) * 60.0)
    cap_b = sev * q_max(fd) * WIDTH
    area = VIEW_LEN / CELLS * WIDTH
    n = np.zeros((rows, CELLS))
    pool = np.zeros(rows)
    upstream = np.zeros(rows)
    count = np.zeros((rows, BINS))
    occ = np.zeros((rows, BINS))
    acc_c = np.zeros(rows)
    acc_n = np.zeros(rows)
    per_bin = int(BIN_S / DT)
    for step in range(DAY_MIN * 60):
        minute = step // 60
        demand = frac[:, minute] * cap_b
        f = booth[:, minute]
        snd, rcv = send_recv(fd, n / area)
        snd *= WIDTH
        rcv *= WIDTH
        inflow = np.minimum(demand + upstream / DT, rcv[:, 0])
        upstream += (demand - inflow) * DT
        inner = np.minimum(snd[:, :-1], rcv[:, 1:])
        out = np.minimum(snd[:, -1], cap_b)
        release = pool * release_rate
        pool += (f * inflow - release) * DT
        n[:, 0] += (1 - f) * inflow * DT
        n[:, :-1] -= inner * DT
        n[:, 1:] += inner * DT
        n[:, -1] += (release - out) * DT
        acc_c += out * DT
        acc_n += n.sum(1) + pool
        if (step + 1) % per_bin == 0:
            b = step // per_bin
            count[:, b] = acc_c
            occ[:, b] = acc_n / per_bin
            acc_c[:] = 0
            acc_n[:] = 0
    shape = (SEEDS, len(DAYS), BINS)
    return count.reshape(shape), occ.reshape(shape), cap_b * 60.0


def downstream_view(count):
    return count, count / BIN_S * VIEW_LEN / V_FREE


def trailing_mean(x, width):
    cs = np.cumsum(x, -1)
    out = np.full_like(x, np.nan, dtype=float)
    out[..., width - 1 :] = cs[..., width - 1 :]
    out[..., width:] -= cs[..., :-width]
    out[..., width - 1 :] /= width
    return out


def observe(truth, window_s, gain_q, gain_n, rng, drift=1.0, miss_q=0.0, miss_n=0.0):
    count, occ = truth
    m = window_s // BIN_S
    c = count.reshape(*count.shape[:-1], -1, m).sum(-1)
    o = occ.reshape(*occ.shape[:-1], -1, m).mean(-1)
    dens = o / (VIEW_LEN * WIDTH) / K_JAM
    gn = np.full(len(DAYS), gain_n)
    gn[min(TEST.values()) :] *= drift
    lam_q = gain_q * np.clip(1 - miss_q * dens, 0, 1) * c
    lam_n = gn[None, :, None] * np.clip(1 - miss_n * dens, 0, 1) * o
    q_win = rng.poisson(lam_q) / (window_s / 60)
    n_win = rng.poisson(lam_n).astype(float)
    width = int(SMOOTH_MIN * 60 / window_s)
    return q_win, trailing_mean(q_win, width), trailing_mean(n_win, width)


def dwell_time(q_bar, n_bar):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(q_bar > 0, n_bar / q_bar, np.nan)


def history_stats(q_bar, n_bar, days):
    q3 = q_bar[:, days]
    w3 = dwell_time(q3, n_bar[:, days])
    q = q3.reshape(SEEDS, -1)
    n = n_bar[:, days].reshape(SEEDS, -1)
    w = w3.reshape(SEEDS, -1)
    pq = {p: np.nanquantile(q, p, axis=1) for p in (*PLEVELS, 0.25, 0.5, 0.75)}
    band = (q >= pq[0.25][:, None]) & (q <= pq[0.75][:, None])
    w0 = np.nanmedian(np.where(band, w, np.nan), axis=1)
    valid = np.isfinite(q) & np.isfinite(n)
    eta = np.where(valid, n * q, 0).sum(1) / np.where(valid, q * q, 0).sum(1)
    with np.errstate(invalid="ignore"):
        queued = (w3 / w0[:, None, None] >= KNEE_RATIO) & (q3 >= pq[0.5][:, None, None])
    run = int(KNEE_RUN_MIN * q3.shape[-1] / DAY_MIN)
    sustained = (trailing_mean(queued.astype(float), run) == 1).reshape(SEEDS, -1)
    knee = np.nanmedian(np.where(sustained, q, np.nan), axis=1)
    knee[sustained.sum(1) < KNEE_MIN_WINDOWS] = np.nan
    return {"pq": pq, "w0": w0, "eta": eta, "knee": knee}


def first_time(fire, window_s, lo=None, hi=None):
    t = (np.arange(fire.shape[-1]) + 1) * window_s / 60
    ok = fire.copy()
    if lo is not None:
        ok &= t[None, :] >= lo[:, None]
    if hi is not None:
        ok &= t[None, :] <= hi[:, None]
    return np.where(ok.any(-1), t[np.argmax(ok, -1)], np.nan)


def wilson(k, n):
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": [None, None]}
    z = 1.96
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": int(k), "n": int(n), "rate": p, "ci95": [centre - half, centre + half]}


def dist(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"n": 0, "median": None, "p25": None, "p75": None}
    p25, med, p75 = np.quantile(x, [0.25, 0.5, 0.75])
    return {"n": int(x.size), "median": med, "p25": p25, "p75": p75}


def outcome(fires, window_s, onset):
    ramp = fires["ramp"]
    early = first_time(ramp, window_s, hi=onset - DETECT_BEFORE)
    hit = first_time(ramp, window_s, lo=onset - DETECT_BEFORE, hi=onset + DETECT_AFTER)
    res = {
        "detect": wilson(np.isfinite(hit).sum(), SEEDS),
        "lag_min": dist(hit - onset),
        "premature": wilson(np.isfinite(early).sum(), SEEDS),
    }
    for name in ("normal", "dwell_low", "dwell_peak"):
        res[f"fa_{name}"] = wilson(fires[name].any(-1).sum(), SEEDS)
    return res


def new_fires(q_bar, n_bar, stats, p, kappa, gate=None):
    w = dwell_time(q_bar, n_bar)
    gate_q = stats["pq"][p] if gate is None else gate
    out = {}
    for name, i in TEST.items():
        q = q_bar[:, i]
        with np.errstate(invalid="ignore"):
            out[name] = (q >= gate_q[:, None]) & (w[:, i] >= kappa * stats["w0"][:, None])
    return out


def old_fires(series, cap_min):
    with np.errstate(invalid="ignore"):
        return {name: series[:, i] >= RHO * cap_min for name, i in TEST.items()}


def ratio_profile(q_bar, n_bar, stats, window_s, onset, ramp_meta):
    w = dwell_time(q_bar, n_bar) / stats["w0"][:, None, None]
    gated = q_bar >= stats["pq"][0.9][:, None, None]
    normal = np.where(gated[:, TEST["normal"]], w[:, TEST["normal"]], np.nan)
    peak = np.where(gated[:, TEST["dwell_peak"]], w[:, TEST["dwell_peak"]], np.nan)
    t = (np.arange(q_bar.shape[-1]) + 1) * window_s / 60
    hold_end = np.array([m["hold_end"] for m in ramp_meta])
    tail = (t[None, :] >= hold_end[:, None] - 10) & (t[None, :] <= hold_end[:, None])
    plateau = np.where(tail, w[:, TEST["ramp"]], np.nan)
    with np.errstate(all="ignore"):
        day_max = np.nan_to_num(np.nanmax(normal, 1), nan=1.0)
        peak_max = np.nan_to_num(np.nanmax(peak, 1), nan=1.0)
        plateau_med = np.nanmedian(plateau, 1)
    return {
        "normal_gated_p99": float(np.nanquantile(normal, 0.99))
        if np.isfinite(normal).any()
        else None,
        "normal_daymax": dist(day_max),
        "normal_daymax_p95": float(np.quantile(day_max, 0.95)),
        "dwell_peak_daymax": dist(peak_max),
        "observed_plateau": dist(plateau_med),
        "onset_gate_open_fraction": float(np.mean(np.isfinite(onset))),
    }


def recommend(cells):
    rows = []
    for kappa in KAPPAS:
        c = cells[kappa]
        worst_fa = max(
            max(c[g]["fa_normal"]["rate"], c[g]["fa_dwell_low"]["rate"], c[g]["premature"]["rate"])
            for g in GAINS
        )
        worst_det = min(c[g]["detect"]["rate"] for g in GAINS)
        rows.append(
            {
                "kappa": kappa,
                "worst_detect": worst_det,
                "worst_fa": worst_fa,
                "lag_g1": c[1.0]["lag_min"]["median"],
                "feasible": bool(worst_fa <= FA_BUDGET and worst_det >= DETECT_FLOOR),
            }
        )
    return rows


def run():
    frac, booth, dwell, onset, ramp_meta = build_demand()
    truths = {}
    for fd in FDS:
        for sev in SEVERITIES:
            truths[fd, sev] = simulate(fd, sev, frac, booth, dwell)
    report = {
        "params": {
            "seeds": SEEDS,
            "day_min": DAY_MIN,
            "view_len_m": VIEW_LEN,
            "width_m": WIDTH,
            "cells": CELLS,
            "v_free_mps": V_FREE,
            "k_jam": K_JAM,
            "k_crit_triangular": K_CRIT_TRI,
            "smooth_min": SMOOTH_MIN,
            "rho": RHO,
            "w0_true_min": VIEW_LEN / V_FREE / 60,
            "knee_ratio": KNEE_RATIO,
            "detect_window_min": [-DETECT_BEFORE, DETECT_AFTER],
            "fa_budget": FA_BUDGET,
        },
        "premises": {},
        "main": {},
        "bounds": {},
        "recommend": {},
        "drift": {},
        "static_ratio": {},
        "miss": {},
        "knee": {},
        "downstream": {},
    }
    report["premises"]["onset_min"] = dist(onset)
    report["premises"]["ramp_overload"] = dist([m["overload"] for m in ramp_meta])
    report["premises"]["h2_max_frac"] = float(frac[:, H2].max())
    report["premises"]["h1_max_frac"] = dist(frac[:, H1].max(-1).max(-1))
    for fi, fd in enumerate(FDS):
        for si, sev in enumerate(SEVERITIES):
            truth = truths[fd, sev]
            count, occ, cap_min = truth
            key = f"{fd}|{sev}"
            report["bounds"][key] = {
                "plateau_theory": plateau_ratio(fd, sev),
                "free_ratio_at_cap": free_ratio_at(fd, sev),
            }
            for wi, window_s in enumerate(WINDOWS):
                cells = {(p, k): {} for p in PLEVELS for k in KAPPAS}
                old = {"window": {}, "smooth": {}}
                knee_rows = {}
                for gi, g in enumerate(GAINS):
                    q_win, q_bar, n_bar = observe(
                        truth[:2], window_s, g, g, rng_for(1, fi, si, wi, gi)
                    )
                    hist = history_stats(q_bar, n_bar, H2)
                    for p in PLEVELS:
                        for kappa in KAPPAS:
                            fires = new_fires(q_bar, n_bar, hist, p, kappa)
                            cells[p, kappa][g] = outcome(fires, window_s, onset)
                    old["window"][g] = outcome(old_fires(q_win, cap_min), window_s, onset)
                    old["smooth"][g] = outcome(old_fires(q_bar, cap_min), window_s, onset)
                    if window_s == 30 and g == 1.0:
                        report["bounds"][key].update(
                            ratio_profile(q_bar, n_bar, hist, window_s, onset, ramp_meta)
                        )
                        report["bounds"][key]["w0_est_over_true"] = dist(
                            hist["w0"] / (VIEW_LEN / V_FREE / 60)
                        )
                        report["bounds"][key]["eta_over_true"] = dist(
                            hist["eta"] / (VIEW_LEN / V_FREE / 60)
                        )
                        report["bounds"][key]["p90_over_cap"] = dist(hist["pq"][0.9] / cap_min)
                    h1 = history_stats(q_bar, n_bar, H1)
                    knee_rows[g] = {
                        "h2_abstain": wilson(np.isnan(hist["knee"]).sum(), SEEDS),
                        "h1_abstain": wilson(np.isnan(h1["knee"]).sum(), SEEDS),
                        "h1_knee_rel_err": dist(h1["knee"] / (g * cap_min) - 1),
                        "h1_p90_over_cap": dist(h1["pq"][0.9] / (g * cap_min)),
                        "rule_b_h1": outcome(
                            new_fires(q_bar, n_bar, h1, 0.9, 1.5), window_s, onset
                        ),
                        "rule_c_h1": outcome(
                            new_fires(q_bar, n_bar, h1, 0.9, 1.5, gate=0.9 * h1["knee"]),
                            window_s,
                            onset,
                        ),
                        "rule_c_h2": outcome(
                            new_fires(q_bar, n_bar, hist, 0.9, 1.5, gate=0.9 * hist["knee"]),
                            window_s,
                            onset,
                        ),
                    }
                wkey = f"{key}|{window_s}"
                report["main"][wkey] = {
                    "old_window": old["window"],
                    "old_smooth": old["smooth"],
                    "new": {f"{p}|{k}": v for (p, k), v in cells.items()},
                }
                report["knee"][wkey] = knee_rows
                report["recommend"][wkey] = {
                    str(p): recommend({k: cells[p, k] for k in KAPPAS}) for p in PLEVELS
                }
    count, occ, cap_min = truths["triangular", 0.7]
    for di, d in enumerate(DRIFTS):
        q_win, q_bar, n_bar = observe((count, occ), 30, 1.0, 1.0, rng_for(2, di), drift=d)
        hist = history_stats(q_bar, n_bar, H2)
        report["drift"][str(d)] = {
            str(k): outcome(new_fires(q_bar, n_bar, hist, 0.9, k), 30, onset) for k in KAPPAS
        }
    for ri, r in enumerate(RATIOS):
        q_win, q_bar, n_bar = observe((count, occ), 30, 1.0, r, rng_for(3, ri))
        hist = history_stats(q_bar, n_bar, H2)
        report["static_ratio"][str(r)] = {
            str(k): outcome(new_fires(q_bar, n_bar, hist, 0.9, k), 30, onset) for k in (1.5, 2.0)
        }
    hold_end = np.array([m["hold_end"] for m in ramp_meta])
    for mi, (mq, mn) in enumerate(MISSES):
        q_win, q_bar, n_bar = observe(
            (count, occ), 30, 1.0, 1.0, rng_for(4, mi), miss_q=mq, miss_n=mn
        )
        hist = history_stats(q_bar, n_bar, H2)
        h1 = history_stats(q_bar, n_bar, H1)
        t = (np.arange(q_bar.shape[-1]) + 1) * 0.5
        tail = (t[None, :] >= hold_end[:, None] - 10) & (t[None, :] <= hold_end[:, None])
        q_tail = np.nanmedian(np.where(tail, q_bar[:, TEST["ramp"]], np.nan), 1)
        w_tail = np.nanmedian(np.where(tail, dwell_time(q_bar, n_bar)[:, TEST["ramp"]], np.nan), 1)
        report["miss"][f"{mq}|{mn}"] = {
            "queue_q_over_p90": dist(q_tail / hist["pq"][0.9]),
            "queue_q_over_p90_h1": dist(q_tail / h1["pq"][0.9]),
            "queue_ratio": dist(w_tail / hist["w0"]),
        }
        for k, stats in (("h1_1.5", h1), ("1.3", hist), ("1.5", hist), ("2.0", hist)):
            fires = new_fires(q_bar, n_bar, stats, 0.9, float(k.removeprefix("h1_")))
            on = (fires["ramp"] & tail).sum(1) / tail.sum(1)
            report["miss"][f"{mq}|{mn}"][k] = {**outcome(fires, 30, onset), "hold_on": dist(on)}
    for fi, fd in enumerate(FDS):
        count, occ, cap_min = truths[fd, 0.7]
        q_win, q_bar, n_bar = observe(downstream_view(count), 30, 1.0, 1.0, rng_for(5, fi))
        hist = history_stats(q_bar, n_bar, H2)
        report["downstream"][fd] = {
            str(k): outcome(new_fires(q_bar, n_bar, hist, 0.9, k), 30, onset) for k in (1.3, 1.5)
        }
    for key, rows in report["knee"].items():
        if key.startswith("triangular"):
            for g, row in rows.items():
                assert row["h2_abstain"]["rate"] >= 0.95, f"knee abstains on H2 ({key}, g={g})"
    return report


def pct(r):
    return "-" if r["rate"] is None else f"{100 * r['rate']:.0f}% ({r['k']}/{r['n']})"


def med(d, digits=1):
    if d["n"] == 0:
        return "- (n=0)"
    return f"{d['median']:.{digits}f} [{d['p25']:.{digits}f}, {d['p75']:.{digits}f}] (n={d['n']})"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def gain_table(cells_by_rule, metric, fmt):
    header = ["規則", *(f"g={g}" for g in GAINS)]
    rows = [[name, *(fmt(cells[g][metric]) for g in GAINS)] for name, cells in cells_by_rule]
    return table(header, rows)


def main_rules(report, wkey, p):
    m = report["main"][wkey]
    rules = [
        ("旧 σ≥ρC（窓ごと、実装どおり）", m["old_window"]),
        ("旧 σ≥ρC（3 分平滑）", m["old_smooth"]),
    ]
    rules += [(f"新 q≥p{int(p * 100)} ∧ W/W₀≥{k}", m["new"][f"{p}|{k}"]) for k in KAPPAS]
    return rules


def write_md(report):
    md_lines = []
    add = md_lines.append
    pr = report["params"]
    add("# パンク判定の再定義の検証（自己履歴の流量上位 ∧ W/W₀ ≥ κ）")
    add("")
    add(
        "`experiments/degraded_operation/panic/panic_redefinition.py` の出力から生成した。"
        f"各数値は種 N={pr['seeds']} 本の集計で、率は「率 (件数/N)」、連続量は「中央値 [p25, p75] (n=件数)」で示す。"
        "率の 95% Wilson 区間は JSON の `ci95` にある。"
    )
    add("")
    add("## 設定")
    add("")
    add(
        f"- 通路カメラ 1 台。視野は長さ {pr['view_len_m']:.0f} m、幅 {pr['width_m']:.0f} m で、"
        f"{pr['cells']} セルの CTM（1 秒刻み）で動かす。視野の下流端にボトルネック（容量 C_b = s × 通路容量）があり、"
        "通過ラインはそのボトルネックに置く。"
    )
    add(
        f"- 基本図は三角形（自由流速度 {pr['v_free_mps']} m/s、臨界密度 {pr['k_crit_triangular']} 人/m²、"
        f"ジャム密度 {pr['k_jam']} 人/m²、通路容量 1.21 人/m/s）を主に使い、"
        "Greenshields（同じ v_f と k_j、容量 1.81 人/m/s）を感度分析に使う。"
        f"真の自由流滞在時間は W₀ = L/v_f = {pr['w0_true_min']:.3f} 分で、エンジンの `fallback_eta` 0.25 分と一致する。"
    )
    add("- ボトルネックの厳しさ s ∈ {0.5, 0.7, 0.85, 0.95}。見出しは s = 0.7。")
    add(
        "- 履歴 H2 は平常日 7 日（ピーク 0.45〜0.8 C_b、容量に届かない）。"
        "履歴 H1 は平常日 5 日と、ピークが 1.05〜1.2 C_b に届く日 2 日。"
    )
    add(
        "- 試験日は 4 種類。ランプ日（午後に 0.6 C_b から 1.05〜1.4 C_b へ 15〜60 分で上げ、30 分保持）、"
        "平常日、低流量の滞留日（ピーク 0.3〜0.4 C_b、10〜17 時の 30〜60% が展示前で 2〜6 分立ち止まる）、"
        "ピーク流量の滞留日（ピーク 0.7〜0.8 C_b、同じ立ち止まり）。真の発生時刻はランプ日で需要が C_b を超えた最初の分である。"
    )
    add(
        "- 観測は、ライン通過数 ~ Poisson(g_q × 真の通過数)、視野内検知人数 ~ Poisson(g_n × 真の視野内人数の窓平均)。"
        "窓は 30 秒と 60 秒。両規則とも 3 分の後ろ向き移動平均を使う比較も示す。"
    )
    add(
        f"- 旧規則は σ ≥ ρ·C（ρ = {pr['rho']}、`puncture_ratio_threshold` の既定値）。"
        "C には真の C_b（人/分）を与える。容量ヒントが正確という最良の条件である。"
        "実装ではスカラー型ルートにしか適用されないが、ここではカメラの通過数に当てはめる。"
    )
    add(
        "- 新規則は q̄ ≥ 自己履歴の p 分位 ∧ W/W₀ ≥ κ。W = N̄/q̄。W₀ は履歴のうち q̄ が p25〜p75 の窓の W の中央値。"
    )
    add(
        f"- 検知はランプ日の発生時刻 −{DETECT_BEFORE:.0f} 分〜+{DETECT_AFTER:.0f} 分の発火。"
        f"それより前の発火は「早発」として誤報に数える。「条件を満たす κ」は、全ゲイン（0.5〜2）で誤報率（平常日・低流量滞留日・早発の最大）"
        f"が {100 * FA_BUDGET:.0f}% 以下で、最悪ゲインの検知率が {100 * DETECT_FLOOR:.0f}% 以上の κ。"
    )
    add("")
    add("## 前提の確認")
    add("")
    pm = report["premises"]
    add("スクリプトは次を assert し、すべて通った。")
    add("")
    add(
        f"- すべてのランプ日で需要が C_b を超える。発生時刻は {med(pm['onset_min'], 0)} 分、超過倍率は {med(pm['ramp_overload'], 2)}。"
    )
    add(f"- H2 の需要は全種・全日で C_b の {pm['h2_max_frac']:.2f} 倍以下（0.9 未満）。")
    add(f"- H1 は全種で C_b を超える日を含む（日最大 {med(pm['h1_max_frac'], 2)} × C_b）。")
    add("- 三角形基本図では、H2 から屈曲点推定が 95% 以上の種で棄権する（後述の表）。")
    add("")
    wkey = "triangular|0.7|30"
    add("## 見出し（三角形、s = 0.7、30 秒窓、p90、H2 履歴）")
    add("")
    rules = main_rules(report, wkey, 0.9)
    add("### 検知率")
    add("")
    add(gain_table(rules, "detect", pct))
    add("")
    add("### 検知の遅れ（分、発生時刻から）")
    add("")
    add(gain_table(rules, "lag_min", med))
    add("")
    add("### 誤報率（平常日）")
    add("")
    add(gain_table(rules, "fa_normal", pct))
    add("")
    add("### 早発率（ランプ日、発生 15 分より前の発火）")
    add("")
    add(gain_table(rules, "premature", pct))
    add("")
    add("### 誤報率（低流量の滞留日）")
    add("")
    add(gain_table(rules, "fa_dwell_low", pct))
    add("")
    add("### 誤報率（ピーク流量の滞留日）")
    add("")
    add(gain_table(rules, "fa_dwell_peak", pct))
    add("")
    add("## κ の下限と上限（g = 1、30 秒窓、p90 ゲートを通った窓の W/W₀）")
    add("")
    rows = []
    for fd in FDS:
        for sev in SEVERITIES:
            b = report["bounds"][f"{fd}|{sev}"]
            rows.append(
                [
                    fd,
                    sev,
                    f"{b['free_ratio_at_cap']:.2f}",
                    f"{b['normal_daymax_p95']:.2f}",
                    med(b["normal_daymax"], 2),
                    med(b["dwell_peak_daymax"], 2),
                    f"{b['plateau_theory']:.2f}",
                    med(b["observed_plateau"], 2),
                    med(b["w0_est_over_true"], 2),
                    med(b["eta_over_true"], 2),
                    med(b["p90_over_cap"], 2),
                ]
            )
    add(
        table(
            [
                "基本図",
                "s",
                "C_b 直前の自由流 W/W₀（理論）",
                "平常日の日最大の p95",
                "平常日の日最大",
                "ピーク滞留日の日最大",
                "渋滞の頭打ち W/W₀（理論）",
                "保持末 10 分の W/W₀（観測）",
                "W₀ 推定 / 真値",
                "η / 真の W₀",
                "履歴 p90 / C_b",
            ],
            rows,
        )
    )
    add("")
    add(
        "ゲートが一度も開かない日の日最大は 1.0 とした。κ は「平常日の日最大の p95」より上、「渋滞の頭打ち」より下に置く必要がある。"
    )
    add("")
    add("## 条件を満たす κ（基本図・厳しさ・窓・p ごと）")
    add("")
    rows = []
    for key, rec in report["recommend"].items():
        fd, sev, window_s = key.split("|")
        for p, cand in rec.items():
            ok = [r for r in cand if r["feasible"]]
            rows.append(
                [fd, sev, window_s, p, ", ".join(str(r["kappa"]) for r in ok) or "なし"]
                + (
                    ["-", "-"]
                    if not ok
                    else [f"{ok[0]['lag_g1']:.1f}", f"{100 * max(r['worst_fa'] for r in ok):.0f}%"]
                )
            )
    add(
        table(
            [
                "基本図",
                "s",
                "窓 (秒)",
                "p",
                "条件を満たす κ",
                "最小 κ の遅れ中央値（g=1、分）",
                "条件を満たす κ の最悪誤報率",
            ],
            rows,
        )
    )
    add("")
    add("## p の比較（三角形、s = 0.7、30 秒窓、κ = 1.5）")
    add("")
    rows = []
    for p in PLEVELS:
        c = report["main"][wkey]["new"][f"{p}|1.5"]
        for g in (0.5, 1.0, 2.0):
            rows.append(
                [
                    p,
                    g,
                    pct(c[g]["detect"]),
                    med(c[g]["lag_min"]),
                    pct(c[g]["fa_normal"]),
                    pct(c[g]["fa_dwell_peak"]),
                ]
            )
    add(table(["p", "g", "検知率", "遅れ（分）", "誤報（平常）", "誤報（ピーク滞留）"], rows))
    add("")
    add("## 窓 30 秒と 60 秒（三角形、s = 0.7、p90、κ = 1.5、g = 1）")
    add("")
    rows = []
    for window_s in WINDOWS:
        c = report["main"][f"triangular|0.7|{window_s}"]["new"]["0.9|1.5"][1.0]
        o = report["main"][f"triangular|0.7|{window_s}"]["old_window"][1.0]
        rows.append([window_s, "新", pct(c["detect"]), med(c["lag_min"]), pct(c["fa_normal"])])
        rows.append(
            [window_s, "旧（窓ごと）", pct(o["detect"]), med(o["lag_min"]), pct(o["fa_normal"])]
        )
    add(table(["窓 (秒)", "規則", "検知率", "遅れ（分）", "誤報（平常）"], rows))
    add("")
    add("## 厳しさ別（30 秒窓、p90、g = 1）")
    add("")
    rows = []
    for fd in FDS:
        for sev in SEVERITIES:
            m = report["main"][f"{fd}|{sev}|30"]
            for k in (1.3, 1.5, 2.0):
                c = m["new"][f"0.9|{k}"][1.0]
                rows.append(
                    [
                        fd,
                        sev,
                        k,
                        pct(c["detect"]),
                        med(c["lag_min"]),
                        pct(c["premature"]),
                        pct(c["fa_normal"]),
                        pct(c["fa_dwell_peak"]),
                    ]
                )
    add(
        table(
            [
                "基本図",
                "s",
                "κ",
                "検知率",
                "遅れ（分）",
                "早発",
                "誤報（平常）",
                "誤報（ピーク滞留）",
            ],
            rows,
        )
    )
    add("")
    add("## g_n/g_q の比（三角形、s = 0.7、30 秒窓、p90）")
    add("")
    add(
        "比が履歴と試験日で同じなら W/W₀ で厳密に打ち消し合う。下表はその確認で、頑健性の証拠ではない。"
    )
    add("")
    rows = []
    for r, by_k in report["static_ratio"].items():
        for k, c in by_k.items():
            rows.append([r, k, pct(c["detect"]), med(c["lag_min"]), pct(c["fa_normal"])])
    add(table(["g_n/g_q（不変）", "κ", "検知率", "遅れ（分）", "誤報（平常）"], rows))
    add("")
    add("比が履歴の後に変わる（ドリフト d = 試験日の比 / 履歴の比）と、W/W₀ は d 倍にずれる。")
    add("")
    rows = []
    for d, by_k in report["drift"].items():
        for k in ("1.3", "1.5", "2.0"):
            c = by_k[k]
            rows.append(
                [
                    d,
                    k,
                    pct(c["detect"]),
                    med(c["lag_min"]),
                    pct(c["premature"]),
                    pct(c["fa_normal"]),
                    pct(c["fa_dwell_peak"]),
                ]
            )
    add(
        table(
            ["d", "κ", "検知率", "遅れ（分）", "早発", "誤報（平常）", "誤報（ピーク滞留）"], rows
        )
    )
    add("")
    add("## 密度依存の検出漏れ（三角形、s = 0.7、30 秒窓、p90、g = 1）")
    add("")
    add("検出率を g × (1 − a × k/k_j) とした。a_q はライン、a_n は視野内検知の傾き。")
    add("")
    rows = []
    for key, row in report["miss"].items():
        mq, mn = key.split("|")
        for k, label in (("1.5", "H2"), ("2.0", "H2"), ("h1_1.5", "H1")):
            c = row[k]
            ratio = row["queue_q_over_p90_h1" if label == "H1" else "queue_q_over_p90"]
            kappa = k.removeprefix("h1_")
            rows.append(
                [
                    mq,
                    mn,
                    label,
                    med(ratio, 2),
                    med(row["queue_ratio"], 2),
                    kappa,
                    pct(c["detect"]),
                    med(c["lag_min"]),
                    med(c["hold_on"], 2),
                    pct(c["fa_normal"]),
                ]
            )
    add(
        table(
            [
                "a_q",
                "a_n",
                "履歴",
                "渋滞中の q̄ / 履歴 p90",
                "渋滞中の W/W₀（H2 の W₀）",
                "κ",
                "検知率",
                "遅れ（分）",
                "保持末 10 分の発火窓の割合",
                "誤報（平常）",
            ],
            rows,
        )
    )
    add("")
    add(
        "最初の発火は視野が埋まる途中（密度がまだ低く、ライン側の取りこぼしが小さいとき）に起きる。"
        "渋滞が続いたときに条件が成り立ち続けるかは「保持末 10 分の発火窓の割合」で見る。"
    )
    add("")
    add("## 自己単位の容量 C_self（屈曲点）の推定（30 秒窓）")
    add("")
    add(
        f"推定は、履歴のうち q̄ ≥ 履歴中央値かつ W/W₀ ≥ {KNEE_RATIO} が {KNEE_RUN_MIN:.0f} 分以上続いた窓の q̄ の中央値。"
        f"該当窓が {KNEE_MIN_WINDOWS} 未満なら「観測不能」として値を出さない。誤差は g × C_b に対する相対誤差。"
    )
    add("")
    rows = []
    for fd in FDS:
        for sev in SEVERITIES:
            rows_k = report["knee"][f"{fd}|{sev}|30"]
            for g in (0.5, 1.0, 2.0):
                r = rows_k[g]
                rows.append(
                    [
                        fd,
                        sev,
                        g,
                        pct(r["h2_abstain"]),
                        pct(r["h1_abstain"]),
                        med(r["h1_knee_rel_err"], 3),
                        med(r["h1_p90_over_cap"], 2),
                    ]
                )
    add(
        table(
            ["基本図", "s", "g", "H2 で棄権", "H1 で棄権", "H1 の相対誤差", "H1 の p90 / C_b"], rows
        )
    )
    add("")
    add(
        "H1 履歴では p90 が容量近くに上がる。p90 ゲート（規則 B）と C_self ゲート（規則 C: q̄ ≥ 0.9 C_self）を κ = 1.5 で比べる。"
    )
    add("")
    rows = []
    for fd in FDS:
        rows_k = report["knee"][f"{fd}|0.7|30"]
        for g in (0.5, 1.0, 2.0):
            r = rows_k[g]
            rows.append(
                [
                    fd,
                    g,
                    "B（H1）",
                    pct(r["rule_b_h1"]["detect"]),
                    med(r["rule_b_h1"]["lag_min"]),
                    pct(r["rule_b_h1"]["fa_normal"]),
                    pct(r["rule_b_h1"]["fa_dwell_peak"]),
                ]
            )
            rows.append(
                [
                    fd,
                    g,
                    "C（H1）",
                    pct(r["rule_c_h1"]["detect"]),
                    med(r["rule_c_h1"]["lag_min"]),
                    pct(r["rule_c_h1"]["fa_normal"]),
                    pct(r["rule_c_h1"]["fa_dwell_peak"]),
                ]
            )
            rows.append(
                [
                    fd,
                    g,
                    "C（H2、C_self なし）",
                    pct(r["rule_c_h2"]["detect"]),
                    med(r["rule_c_h2"]["lag_min"]),
                    pct(r["rule_c_h2"]["fa_normal"]),
                    pct(r["rule_c_h2"]["fa_dwell_peak"]),
                ]
            )
    add(
        table(
            [
                "基本図",
                "g",
                "規則（履歴）",
                "検知率",
                "遅れ（分）",
                "誤報（平常）",
                "誤報（ピーク滞留）",
            ],
            rows,
        )
    )
    add("")
    add("## カメラがボトルネックの下流にある場合（s = 0.7、30 秒窓、p90、g = 1）")
    add("")
    rows = []
    for fd, by_k in report["downstream"].items():
        for k, c in by_k.items():
            rows.append([fd, k, pct(c["detect"]), pct(c["fa_normal"])])
    add(table(["基本図", "κ", "検知率", "誤報（平常）"], rows))
    add("")
    add(Path(__file__).with_name("panic_redefinition_notes.md").read_text(encoding="utf-8").strip())
    add("")
    return "\n".join(md_lines)


def to_jsonable(x):
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [to_jsonable(v) for v in x]
    if isinstance(x, np.floating | float):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def main():
    warnings.simplefilter("ignore", RuntimeWarning)
    report = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "panic_redefinition.json").write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (RESULTS / "panic_redefinition.md").write_text(write_md(report), encoding="utf-8")


if __name__ == "__main__":
    main()
