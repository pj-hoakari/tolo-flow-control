from __future__ import annotations

import itertools
import statistics
import sys
from typing import Any

import numpy as np
from _common import (
    OBS_FIELDS,
    SCENARIO_KINDS,
    Task,
    frac_cell,
    last_attr,
    leaves,
    load_scenario,
    md_table,
    run_all,
    wilson,
    write_outputs,
)
from e2b_gain_estimation import (
    NOMINAL_CAPACITY,
    build_network,
    demo_graph,
    fit,
    log_uniform,
    measure,
    route_rates,
    series_errors,
)

SEEDS = 50
DT = 30
FLOW = 20.0
INJECT_WINDOWS = (60, 240, 1440, 10080, 86400)
INJECT_MODELS = ("poisson", "thinned")
LOOP_WINDOWS = (60, 1440, 86400)
DENSITY_B = (0.2, 0.4)
CALIBRATION_DENSITY_RATIO = 0.5
CORE_KINDS = ("verdict", "triggered", "direction", "boundary", "restriction", "detour")
KINDS = (*CORE_KINDS, "emphasis")


def owners_of(name: str) -> list[str]:
    scen = load_scenario(name)
    found = {
        owner
        for part in (scen.observations, scen.history_digest)
        for path, owner, _ in leaves(part)
        if owner and last_attr(path) in OBS_FIELDS
    }
    return sorted(found)


def cameras_of(name: str) -> frozenset[str]:
    obs = load_scenario(name).observations
    return frozenset(
        {f.edge_id.value for f in obs.arc_flows} | {f.edge_id.value for f in obs.arc_scalar_flows}
    )


def snapshot_density(name: str) -> dict[str, float]:
    obs = load_scenario(name).observations
    return {
        f"edge:{f.edge_id.value}": min(1.0, f.observed_count / NOMINAL_CAPACITY)
        for f in obs.arc_scalar_flows
    }


def draw_outcome(rng: np.random.Generator, pool: list[float | None]) -> float | None:
    return pool[int(rng.integers(len(pool)))]


def build_arms(
    name: str, index: int, pools: dict[tuple[str, int], list[float | None]]
) -> tuple[list[Task], dict[str, Any]]:
    owners = owners_of(name)
    edges = [o for o in owners if o.startswith("edge:")]
    nodes = [o for o in owners if o.startswith("node:")]
    assert edges, f"{name}: no edge cameras to perturb"
    reference = edges[0]
    density = snapshot_density(name)
    graph = load_scenario(name).graph
    net = build_network(graph, cameras_of(name))
    identifiable = [p for p, s in net.status.items() if s == "identifiable"]
    loop_ok = bool(identifiable) and net.routes.shape[0] > 0
    info = {
        "edges": len(edges),
        "nodes": len(nodes),
        "usable_transit_nodes": list(net.nodes),
        "loop_reference": net.reference,
        "loop_identifiable": identifiable,
        "loop_status": dict(net.status),
    }
    tasks: list[Task] = [Task(name, tag="g1")]
    for seed in range(SEEDS):
        rng = np.random.default_rng([seed, index])
        g = dict(zip(owners, log_uniform(rng, len(owners)), strict=True))
        g_ref = g[reference]

        def task(factors: dict[str, float], arm: str, seed: int = seed) -> Task:
            return Task(name, per_point=tuple(sorted(factors.items())), tag=f"{arm}|{seed}")

        node_g = {o: g[o] for o in nodes}
        tasks.append(task(g, "none"))
        tasks.append(task(dict.fromkeys(edges, 1.0) | node_g, "oracle_edges_abs"))
        tasks.append(task(dict.fromkeys(edges, g_ref) | node_g, "oracle_edges_rel"))
        tasks.append(task(dict.fromkeys(owners, g_ref), "oracle_all_rel"))
        for model, w in itertools.product(INJECT_MODELS, INJECT_WINDOWS):
            factors = dict(node_g)
            for o in edges:
                eps = 0.0 if o == reference else draw_outcome(rng, pools[(model, w)])
                factors[o] = g[o] if eps is None else 1.0 / (1.0 + eps)
            tasks.append(task(factors, f"inject:{model}:{w}"))
        for b in DENSITY_B:
            factors = {}
            for o in edges:
                rho = density.get(o, 0.0)
                factors[o] = (1.0 - b * rho) / (1.0 - CALIBRATION_DENSITY_RATIO * b * rho)
            tasks.append(task(factors, f"density:{b:g}"))
        if loop_ok:
            gains = np.array([g[f"edge:{p}"] for p in net.points])
            sim = np.random.default_rng([seed, index, 7])
            rates = route_rates(net, sim, DT, max(LOOP_WINDOWS), FLOW)
            y = measure(net, rates, gains, DT, sim, "thinned")
            for w in LOOP_WINDOWS:
                est = fit(net, y[:w], "iv")
                factors = dict(g)
                for p, g_hat in est["gain"].items():
                    if g_hat is not None:
                        factors[f"edge:{p}"] = g[f"edge:{p}"] / g_hat
                tasks.append(task(factors, f"loop:{w}"))
    return tasks, info


def limit_deviation(base: dict[str, Any], cur: dict[str, Any]) -> list[float]:
    ref = {e: float(v) for e, v in base["restriction_limit"] if v is not None}
    return [
        abs(float(v) / ref[e] - 1.0)
        for e, v in cur["restriction_limit"]
        if v is not None and e in ref and ref[e] != 0.0
    ]


def main() -> None:
    graph, cameras = demo_graph()
    demo = build_network(graph, cameras, reference="e0")
    pools: dict[tuple[str, int], list[float | None]] = {}
    for model in INJECT_MODELS:
        print(f"[e2ac] error pool {model}", file=sys.stderr, flush=True)
        cells = series_errors(demo, DT, FLOW, SEEDS, model, INJECT_WINDOWS, estimators=("iv",))
        for w in INJECT_WINDOWS:
            pools[(model, w)] = cells[("iv", w)]["outcomes"]
    pool_summary = {
        f"{m}:{w}": {
            "n": len(v),
            "missing": sum(x is None for x in v),
            "median_abs": float(np.median([abs(x) for x in v if x is not None])),
            "p90_abs": float(np.quantile([abs(x) for x in v if x is not None], 0.9)),
        }
        for (m, w), v in pools.items()
    }
    tasks: list[Task] = []
    infos: dict[str, Any] = {}
    for index, name in enumerate(SCENARIO_KINDS):
        scenario_tasks, infos[name] = build_arms(name, index, pools)
        tasks.extend(scenario_tasks)
    results = run_all(tasks, "e2ac")
    base = {r["task"].name: r["sig"] for r in results if r["task"].tag == "g1"}
    for name, kind in SCENARIO_KINDS.items():
        assert base[name][kind], f"{name}: claimed decision kind {kind} empty at g=1"
        assert base[name]["verdict"] == "TRIGGERED", f"{name}: g=1 did not trigger"

    records = []
    for r in results:
        if r["task"].tag == "g1":
            continue
        arm, seed = r["task"].tag.split("|")
        b = base[r["task"].name]
        changed = [k for k in KINDS if b[k] != r["sig"][k]]
        records.append(
            {
                "scenario": r["task"].name,
                "arm": arm,
                "seed": int(seed),
                "changed": changed,
                "limit_dev": limit_deviation(b, r["sig"]),
                "solver": r["diag"]["solver"],
            }
        )
    for name in SCENARIO_KINDS:
        rows = [x for x in records if x["scenario"] == name and x["arm"] == "none"]
        assert len(rows) == SEEDS, f"{name}: expected {SEEDS} none-arm runs, got {len(rows)}"
    payload = {
        "settings": {
            "seeds": SEEDS,
            "dt": DT,
            "flow": FLOW,
            "inject_windows": INJECT_WINDOWS,
            "loop_windows": LOOP_WINDOWS,
            "density_b": DENSITY_B,
            "calibration_density_ratio": CALIBRATION_DENSITY_RATIO,
        },
        "baseline_signatures": base,
        "scenario_info": infos,
        "error_pools": pool_summary,
        "records": records,
    }
    write_outputs("e2ac_point_gain", payload, render(payload))


def arm_rows(records: list[dict[str, Any]], arm: str) -> list[dict[str, Any]]:
    return [r for r in records if r["arm"] == arm]


def kind_hits(rows: list[dict[str, Any]], kind: str) -> int:
    if kind == "core":
        return sum(1 for r in rows if set(r["changed"]) & set(CORE_KINDS))
    if kind == "any":
        return sum(1 for r in rows if r["changed"])
    return sum(1 for r in rows if kind in r["changed"])


def spread(rows: list[dict[str, Any]], kind: str) -> str:
    fracs = []
    for name in SCENARIO_KINDS:
        sub = [r for r in rows if r["scenario"] == name]
        if sub:
            fracs.append(kind_hits(sub, kind) / len(sub))
    if not fracs:
        return "-"
    return (
        f"{100 * min(fracs):.0f}% / {100 * statistics.median(fracs):.0f}% / {100 * max(fracs):.0f}%"
    )


def limit_text(rows: list[dict[str, Any]]) -> str:
    devs = [d for r in rows for d in r["limit_dev"]]
    if not devs:
        return "-"
    a = np.asarray(devs)
    return f"{100 * np.median(a):.1f}% / {100 * np.quantile(a, 0.9):.1f}% (n={a.size})"


def render(p: dict[str, Any]) -> str:
    s, recs, info = p["settings"], p["records"], p["scenario_info"]
    n_scen = len(SCENARIO_KINDS)
    out = ["# E2(a)(c): 観測点ごとのゲインが決定に与える影響と、推定ゲインによる補正", ""]
    out.append("## 設定")
    out.append("")
    out.append(
        f"対象は E1 と同じ {n_scen} シナリオ（履歴あり）。シードは各シナリオ {s['seeds']}。"
        "観測点はエッジのカメラで、そのエッジの flow_rate・flow_samples・directional_flow_samples・"
        "observed_count・stagnation・stagnation_samples・p90_stagnation・baseline_stagnation を同じ g_e 倍する。"
        "混在ノードの占有センサは独自の g_v で occupancy と occupancy_delta を倍する。"
        "g は [0.6, 1.5] の対数一様。capacity_hint・danger_capacity・danger_flow_capacity は運用者が真の単位で設定する値なので動かさない。"
        "比較の基準は g=1 の実行の署名である。"
    )
    out.append("")
    out.append(
        "決定種別は verdict、triggered（発火エッジ・ノードの集合）、direction（KEEP 以外の方向提案）、"
        "boundary（境界制御）、restriction（通行制限の有無・種類・理由）、detour（採用迂回パス）、"
        "emphasis（重要度の順位。1e-6 で同着をまとめる）。core は emphasis を除く 6 種のどれかが変わった割合。"
        "制限値 limit_value は連続量なので一致判定に入れず、g=1 との相対差の中央値 / p90 を別に示す。"
    )
    out.append("")
    out.append("## E2(a): 補正なしの感度")
    out.append("")
    none_rows = arm_rows(recs, "none")
    header = ["scenario", *KINDS, "core", "制限値の相対差"]
    table = []
    for name in SCENARIO_KINDS:
        sub = [r for r in none_rows if r["scenario"] == name]
        table.append(
            [
                name,
                *[f"{kind_hits(sub, k)}/{len(sub)}" for k in (*KINDS, "core")],
                limit_text(sub),
            ]
        )
    table.append(
        [
            f"全体（{n_scen}×{s['seeds']}）",
            *[frac_cell(kind_hits(none_rows, k), len(none_rows)) for k in (*KINDS, "core")],
            limit_text(none_rows),
        ]
    )
    table.append(
        [
            "シナリオ間の 最小 / 中央 / 最大",
            *[spread(none_rows, k) for k in (*KINDS, "core")],
            "",
        ]
    )
    out.append(md_table(header, table))
    out.append("")
    out.append(
        "verdict と triggered が一度も変わらないのは構造による。Detection の比較はどれも同じカメラの中で閉じている"
        "（急増の傾きは自身の平均で正規化、s と p90、(s − 移動平均)/baseline は同じエッジの値）。"
        "そのため点ごとのゲインは打ち消し合う。これは履歴とスナップショットが同じゲインのカメラから来ることを前提にしている。"
        "カメラの交換（SENSOR_SET_CHANGED）で履歴だけ古いゲインのまま残る場合は試していない。"
    )
    out.append("")
    out.append("## E2(c): 補正の各条件と決定の食い違い")
    out.append("")
    out.append(
        "- none: 補正なし（E2(a) と同じ）。\n"
        "- oracle_edges_abs: エッジのゲインを完全に補正する。占有センサの g_v は残る。相対推定でどこまで下がるかの床。\n"
        "- oracle_edges_rel: エッジを参照点に対する比で完全に補正する。参照点自身のゲイン g_ref が全エッジに共通の倍率として残る。\n"
        "- oracle_all_rel: 占有センサも含めて全点に共通の倍率 g_ref だけが残る。E1 の obs_only を g_ref ∈ [0.6, 1.5] で試すのと同じ。\n"
        f"- inject:<モデル>:<窓数>: 参照点のゲインは既知とし、他のエッジの相対ゲインに E2(b) の推定誤差を載せる。誤差は"
        f" E2(b) の grid(3,3)・bidir・Δt={s['dt']} 秒・流量 {s['flow']:g}・iv 推定の結果から点ごとに再標本化する。"
        "推定が出なかった点（h ≤ 0 など）は補正しない。\n"
        f"- density:<b>: g0 は完全に補正するが、ゲインが密度で g0·(1 − b·ρ) に下がる。ρ はスナップショットの観測流量/{NOMINAL_CAPACITY:g}。"
        f"一定の ĝ は較正期間の平均密度（スナップショットの {s['calibration_density_ratio']:g} 倍と仮定）で当てはまったものとする。\n"
        "- loop:<窓数>: シナリオ自身のグラフとカメラ配置で多窓の系列を合成し（thinned モデル、流量 20、iv）、"
        "推定できた点だけを 1/ĝ で補正する。参照点は未知のままなので g_ref が残る。"
    )
    out.append("")
    arms = [
        "none",
        "oracle_edges_abs",
        "oracle_edges_rel",
        "oracle_all_rel",
        *[f"inject:{m}:{w}" for m in INJECT_MODELS for w in s["inject_windows"]],
        *[f"density:{b:g}" for b in s["density_b"]],
        *[f"loop:{w}" for w in s["loop_windows"]],
    ]
    table = []
    for arm in arms:
        rows = arm_rows(recs, arm)
        if not rows:
            continue
        scen_count = len({r["scenario"] for r in rows})
        table.append(
            [
                arm,
                f"{scen_count}×{s['seeds']}",
                frac_cell(kind_hits(rows, "core"), len(rows)),
                spread(rows, "core"),
                frac_cell(kind_hits(rows, "emphasis"), len(rows)),
                *[f"{100 * kind_hits(rows, k) / len(rows):.1f}%" for k in CORE_KINDS],
                limit_text(rows),
            ]
        )
    out.append(
        md_table(
            [
                "条件",
                "シナリオ×シード",
                "core",
                "core のシナリオ間 最小/中央/最大",
                "emphasis",
                *CORE_KINDS,
                "制限値の相対差",
            ],
            table,
        )
    )
    out.append("")
    loop_scenarios = {r["scenario"] for r in recs if r["arm"].startswith("loop:")}
    out.append(
        f"loop は {len(loop_scenarios)} シナリオだけで走るので、同じシナリオに絞った比較を並べる: "
        + "、".join(
            f"{arm} {frac_cell(kind_hits(sub, 'core'), len(sub))}"
            for arm in ("none", "oracle_edges_abs", "oracle_edges_rel")
            for sub in [[r for r in arm_rows(recs, arm) if r["scenario"] in loop_scenarios]]
        )
        + "。"
    )
    out.append("")
    out.append("core が変わった実行のシナリオ別内訳（none と oracle_edges_abs）:")
    out.append("")
    out.append(
        md_table(
            ["scenario", "none", "oracle_edges_abs"],
            [
                [
                    name,
                    *[
                        f"{kind_hits([r for r in arm_rows(recs, arm) if r['scenario'] == name], 'core')}"
                        f"/{s['seeds']}"
                        for arm in ("none", "oracle_edges_abs")
                    ],
                ]
                for name in SCENARIO_KINDS
            ],
        )
    )
    out.append("")
    out.append(
        "oracle_edges_abs でも残る食い違いは、補正していない占有センサの g_v から来る。"
        "保存則による較正はエッジのカメラにしか届かない。"
    )
    out.append("")
    floor = arm_rows(recs, "oracle_edges_abs")
    floor_hi = wilson(kind_hits(floor, "core"), len(floor))[1]
    out.append("## 必要な窓数")
    out.append("")
    out.append(
        f"床（oracle_edges_abs）の core 食い違いは {frac_cell(kind_hits(floor, 'core'), len(floor))}。"
        "inject の core 食い違いがこの 95% 区間の上限以下に入る最小の窓数を、観測モデルごとに示す。"
        f"エンジンが 1 リクエストで見るのは 30 分 = {1800 // s['dt']} 窓（Δt={s['dt']} 秒）である。"
    )
    out.append("")
    needed_rows = []
    for model in INJECT_MODELS:
        needed = None
        for w in s["inject_windows"]:
            rows = arm_rows(recs, f"inject:{model}:{w}")
            if rows and kind_hits(rows, "core") / len(rows) <= floor_hi:
                needed = w
                break
        needed_rows.append(
            [
                model,
                "inject の範囲では届かない"
                if needed is None
                else f"{needed} 窓（{needed * s['dt'] / 3600:g} 時間）",
            ]
        )
    out.append(md_table(["観測モデル", "床に届く最小の窓数"], needed_rows))
    out.append("")
    out.append("## 注入した推定誤差（E2(b) 由来）")
    out.append("")
    out.append(
        md_table(
            ["モデル:窓数", "期間", "標本数", "推定が出なかった点", "|誤差| 中央値", "|誤差| p90"],
            [
                [
                    key,
                    f"{int(key.split(':')[1]) * s['dt'] / 3600:g} 時間",
                    v["n"],
                    f"{v['missing']} ({100 * v['missing'] / v['n']:.0f}%)",
                    f"{100 * v['median_abs']:.1f}%",
                    f"{100 * v['p90_abs']:.1f}%",
                ]
                for key, v in p["error_pools"].items()
            ],
        )
    )
    out.append("")
    out.append("## シナリオのグラフで保存則が使える範囲（loop の前提）")
    out.append("")
    out.append(
        md_table(
            [
                "scenario",
                "エッジのカメラ",
                "占有センサ",
                "使える通過ノード",
                "参照点",
                "推定できる点",
            ],
            [
                [
                    name,
                    v["edges"],
                    v["nodes"],
                    ", ".join(v["usable_transit_nodes"]) or "なし",
                    v["loop_reference"] or "-",
                    ", ".join(v["loop_identifiable"]) or "なし",
                ]
                for name, v in info.items()
            ],
        )
    )
    out.append("")
    out.append(
        "使える通過ノードは、通過専用で入退出点でなく、接する有効エッジ全てに方向別ラインカメラがあるノードである。"
        "loop の行は、推定できる点を持つシナリオだけを数えている。"
    )
    out.append("")
    out.append(WHAT_ELSE)
    return "\n".join(out) + "\n"


WHAT_ELSE = """## この数字が別のものを測っている可能性

- 時間予算による打ち切り: 全実行で greedy_truncated が偽、solver_status が TIMEOUT でないことを assert した（_common.evaluate）。
- 変換が効いていない: 全実行で、変換前後の浮動小数の葉の比が点ごとの係数に一致することを assert した。
- emphasis の揺れ: E1 の退化検査で、station-transfer-peak の重要度順位は epsilon_0 を 0 倍・2 倍しただけで入れ替わる。emphasis の食い違いには、ゲインの効果ではなく LP の代替最適解の揺れが混ざる。core と分けて示したのはこのためである。
- 基準の選び方: g=1 を「正しい決定」とみなしている。g=1 のシナリオの決定そのものが境目に乗っていれば、小さなゲインでも食い違いが出る。シナリオ間の最小/中央/最大を並べたのは、少数のシナリオが全体の割合を決めていないかを見るためである。
- 短い窓の inject が none より悪い理由: 中央値 300% を超える誤差の推定値を、もっともらしさの検査なしにそのまま当てている。ĝ が一定の範囲を外れたら捨てる検査を入れれば、短い窓の条件は none に近づくはずで、none を下回る（良くなる）ことは期待できない。「補正しないより悪い」はこの素通しの条件での結果である。
- 注入誤差の出どころ: inject の誤差は grid(3,3) という好条件のグラフで推定したものを、別のグラフのシナリオへ再標本化している。誤差の点間相関や、流量水準の違いは持ち込んでいない。
- 密度の仮定: density の ρ はスナップショットの流量を公称容量 60 人/分で割った値で、較正期間の平均密度をその半分と置いた。どちらも実測していない。
- capacity を据え置く選択: 共通倍率が残る条件（oracle_edges_rel、oracle_all_rel、loop）の食い違いは、delta_min と capacity_hint・danger_capacity・danger_flow_capacity が真の単位の絶対値であることから来る（E1 の obs_only と同じ機構）。
"""


if __name__ == "__main__":
    main()
