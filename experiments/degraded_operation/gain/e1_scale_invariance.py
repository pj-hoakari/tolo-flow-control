from __future__ import annotations

import itertools
from typing import Any

from _common import (
    SCENARIO_KINDS,
    Task,
    diff_kinds,
    has_kind,
    max_rel,
    md_table,
    run_all,
    write_outputs,
)

KS = (0.01, 0.1, 1.0, 10.0, 100.0)
PROBE_EPS = (0.0, 2.0)
VARIANTS = {"history": True, "no_history": False}
ATTRIBUTION_SETS = (
    ("delta_min",),
    ("fallback_baseline",),
    ("delta_min", "fallback_baseline"),
    ("delta_min", "fallback_baseline", "ipf_tolerance"),
    ("delta_min", "fallback_baseline", "epsilon_0"),
    ("delta_min", "fallback_baseline", "ipf_tolerance", "epsilon_0"),
)


def build_tasks() -> list[Task]:
    tasks: list[Task] = []
    for name, (variant, history), k in itertools.product(SCENARIO_KINDS, VARIANTS.items(), KS):
        tasks.append(Task(name, history, common=k, cap_factor=k, out_k=k, tag=f"full:{variant}"))
        if k == 1.0:
            tasks.append(Task(name, history, tag=f"repeat:{variant}"))
            tasks.extend(
                Task(
                    name,
                    history,
                    const_groups=("epsilon_0",),
                    const_k=c,
                    tag=f"probe:{variant}:{c:g}",
                )
                for c in PROBE_EPS
            )
            continue
        tasks.extend(
            Task(
                name,
                history,
                common=k,
                cap_factor=k,
                out_k=k,
                const_groups=groups,
                const_k=k,
                tag=f"attr:{variant}:{'+'.join(groups)}",
            )
            for groups in ATTRIBUTION_SETS
        )
    tasks.extend(
        Task(name, True, common=k, cap_factor=1.0, out_k=k, tag="obs_only:history")
        for name, k in itertools.product(SCENARIO_KINDS, KS)
    )
    return tasks


def cont_gap(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    tp_a, tp_b = a["throughput"], b["throughput"]
    return {
        "od": max_rel(a["od"], b["od"]),
        "throughput": 0.0 if tp_a == tp_b else max_rel({"t": tp_a or 0.0}, {"t": tp_b or 0.0}),
        "tau": max_rel({"t": a["tau"]}, {"t": b["tau"]}),
        "importance": max(
            (
                abs(a["importance"].get(x, 0.0) - b["importance"].get(x, 0.0))
                for x in a["importance"]
            ),
            default=0.0,
        ),
    }


def main() -> None:
    results = run_all(build_tasks(), "e1")
    by_key = {(r["task"].name, r["task"].tag, r["task"].common): r for r in results}

    premises: list[dict[str, Any]] = []
    for name, kind in SCENARIO_KINDS.items():
        for variant in VARIANTS:
            base = by_key[(name, f"full:{variant}", 1.0)]
            repeat = by_key[(name, f"repeat:{variant}", 1.0)]
            assert base["sig"] == repeat["sig"], f"{name}/{variant}: k=1 not deterministic"
            assert base["sig"]["verdict"] == "TRIGGERED", f"{name}/{variant}: k=1 did not trigger"
            present = has_kind(base["sig"], kind)
            if variant == "history":
                assert present, f"{name}: claimed decision kind {kind} empty at k=1"
            premises.append(
                {"scenario": name, "variant": variant, "kind": kind, "present": present}
            )
        scaled = by_key[(name, "full:history", 10.0)]["census"]["scaled"]
        for field in ("flow_rate", "stagnation", "observed_count", "p90_stagnation"):
            assert scaled.get(field, 0) > 0, f"{name}: scaling did not touch {field}"

    rows: list[dict[str, Any]] = []
    for name in SCENARIO_KINDS:
        for variant, k in itertools.product((*VARIANTS, "obs_only"), KS):
            tag_variant = "history" if variant == "obs_only" else variant
            tag = "obs_only:history" if variant == "obs_only" else f"full:{variant}"
            base = by_key[(name, f"full:{tag_variant}", 1.0)]
            cur = by_key[(name, tag, k)]
            row: dict[str, Any] = {
                "scenario": name,
                "variant": variant,
                "k": k,
                "diff": diff_kinds(base["sig"], cur["sig"]),
                "cont": cont_gap(base["cont"], cur["cont"]),
                "diag": cur["diag"],
                "census": cur["census"],
            }
            if variant != "obs_only" and k != 1.0:
                row["attribution"] = {
                    "+".join(groups): diff_kinds(
                        base["sig"],
                        by_key[(name, f"attr:{variant}:{'+'.join(groups)}", k)]["sig"],
                    )
                    for groups in ATTRIBUTION_SETS
                }
            rows.append(row)

    probes = [
        {
            "scenario": name,
            "variant": variant,
            "eps_factor": c,
            "diff": diff_kinds(
                by_key[(name, f"full:{variant}", 1.0)]["sig"],
                by_key[(name, f"probe:{variant}:{c:g}", 1.0)]["sig"],
            ),
        }
        for name in SCENARIO_KINDS
        for variant in VARIANTS
        for c in PROBE_EPS
    ]
    payload = {"ks": KS, "premises": premises, "rows": rows, "probes": probes}
    write_outputs("e1_scale_invariance", payload, render(payload))


def render(payload: dict[str, Any]) -> str:
    rows = payload["rows"]
    n_scen = len(SCENARIO_KINDS)
    out: list[str] = ["# E1: 共通スケール k に対する決定の不変性", ""]
    out.append(
        f"対象は {n_scen} シナリオ、k ∈ {list(payload['ks'])}、変種は 3 つ（history: 履歴あり、"
        "no_history: p90・baseline・η を None にしてフォールバック定数を使わせる、"
        "obs_only: 観測と履歴だけを k 倍し capacity_hint・danger_capacity は据え置く）。"
        "各実行は決定的で、k=1 を 2 回走らせて署名の一致を確かめた（シード数の概念はない）。"
    )
    out.append("")
    out.append("## 前提の確認")
    out.append("")
    out.append(
        md_table(
            ["scenario", "variant", "主張する決定種別", "k=1 で非空"],
            [
                [p["scenario"], p["variant"], p["kind"], "yes" if p["present"] else "no"]
                for p in payload["premises"]
            ],
        )
    )
    out.append("")
    unchanged = sorted(
        {
            f
            for r in rows
            if r["k"] == 10.0 and r["variant"] == "history"
            for f in r["census"]["unchanged_fields"]
        }
    )
    scaled = sorted(
        {
            f
            for r in rows
            if r["k"] == 10.0 and r["variant"] == "history"
            for f in r["census"]["scaled"]
        }
    )
    out.append(f"k 倍した浮動小数フィールド: {', '.join(scaled)}。")
    out.append(
        f"据え置いた浮動小数フィールド（人数次元でないことを目視で確認する対象）: {', '.join(unchanged)}。"
    )
    out.append("")

    for variant in (*VARIANTS, "obs_only"):
        out.append(f"## 変種 {variant}: k=1 からの決定差分")
        out.append("")
        table = []
        for name in SCENARIO_KINDS:
            cells = []
            for k in payload["ks"]:
                r = next(
                    x
                    for x in rows
                    if x["scenario"] == name and x["variant"] == variant and x["k"] == k
                )
                cells.append(",".join(r["diff"]) if r["diff"] else "一致")
            table.append([name, *cells])
        out.append(md_table(["scenario", *[f"k={k:g}" for k in payload["ks"]]], table))
        out.append("")
        broken = [r for r in rows if r["variant"] == variant and r["k"] != 1.0 and r["diff"]]
        total = sum(1 for r in rows if r["variant"] == variant and r["k"] != 1.0)
        out.append(f"決定が変わった組: {len(broken)}/{total}（{n_scen} シナリオ × 4 つの k）。")
        out.append("")
        gaps = [
            r["cont"] for r in rows if r["variant"] == variant and r["k"] != 1.0 and not r["diff"]
        ]
        if gaps:
            out.append(
                "決定が一致した組での連続量の最大ずれ（OD/k と throughput/k は相対、τ は相対、"
                "重要度は絶対差）: "
                + ", ".join(f"{key}={max(g[key] for g in gaps):.2e}" for key in gaps[0])
                + f"（{len(gaps)} 組）。"
            )
            out.append("")

    out.append("## 帰属: 定数も k 倍したときに不変性が戻るか")
    out.append("")
    attr_rows = []
    for r in rows:
        if "attribution" not in r or not r["diff"]:
            continue
        restored = [g for g, d in r["attribution"].items() if not d]
        attr_rows.append(
            [
                r["scenario"],
                r["variant"],
                f"{r['k']:g}",
                ",".join(r["diff"]),
                f"{r['diag']['commodities']}/{r['diag']['od_pairs_input']}",
                ", ".join(restored) if restored else "どれも戻らない",
            ]
        )
    out.append(
        md_table(
            ["scenario", "variant", "k", "変わった決定", "commodities/OD", "不変性が戻る定数集合"],
            attr_rows,
        )
    )
    out.append("")
    out.append(
        "定数集合の中身は delta_min = forecasting.delta_min と optimization.delta_min、"
        "fallback_baseline = detection と optimization の fallback_baseline_stagnation、"
        "ipf_tolerance = forecasting.ipf_tolerance、epsilon_0 = 3 モジュールの epsilon_0 である。"
        "fallback_eta はどの集合にも入れていない（η は 停滞/流量 で人数次元が打ち消し合う）。"
    )
    out.append("")
    out.append("## 退化の検査: k=1 のまま epsilon_0 だけを 0 倍・2 倍する")
    out.append("")
    out.append(
        "epsilon_0 は 1e-6 の零除算よけで、決定に効くはずがない。k=1 でこれを動かして決定が変わるなら、"
        "そのシナリオの決定は 1e-6 程度の摂動で入れ替わる境目（LP の代替最適解など）に乗っている。"
        "上の帰属で epsilon_0 が要った組は 2 種類ある。station-transfer-peak（history）は k=1 でも ε0 の摂動で"
        "重要度順位が入れ替わるので、LP の代替最適解の揺れであってスケールの効果ではない。"
        "reversible-corridor-flip（no_history）は k=1 の摂動では変わらない。k=0.1 では fallback を k 倍した s̄=0.1 に対して"
        "ε0 の比が 10 倍になり、重要度 5e-4 の e_service が重要度 1e-9 の採用しきい値を割って順位から消える。"
        "流量のごく小さいエッジが表示のしきい値をまたぐ効果である。"
    )
    out.append("")
    out.append(
        md_table(
            ["scenario", "variant", "ε0×0", "ε0×2"],
            [
                [
                    name,
                    variant,
                    *[
                        ",".join(p["diff"]) or "一致"
                        for p in payload["probes"]
                        if p["scenario"] == name and p["variant"] == variant
                    ],
                ]
                for name in SCENARIO_KINDS
                for variant in VARIANTS
            ],
        )
    )
    out.append("")
    out.append(WHAT_ELSE)
    return "\n".join(out) + "\n"


WHAT_ELSE = """## この数字が別のものを測っている可能性

- 時間予算による打ち切り: 全実行で greedy_truncated が偽、solver_status が TIMEOUT でないことを assert した。
- 非決定性: k=1 を 2 回走らせ、署名の一致を assert した。
- スケールが効いていない: 変換前後の浮動小数の葉を全て列挙し、各葉の比が規則どおりの係数であることを assert した。k 倍したフィールドと据え置いたフィールドの一覧は上に載せた。
- 重要度の順位の同着: 重要度を 1e-6 で丸めて同着をまとめてから順位を比べている。LP の退化で同着の並びが揺れる分は差分に数えない。
- シナリオの偏り: devtools のシナリオは compact_configs（optimization.delta_min=8.0）を使う。本番既定の 0.5 では、壊れ始める k が変わる。
- 今回のシナリオは references、arc_demand_digest、SCHEDULED_INFLOW、前回の通行制限を持たないことを assert した。これらを持つ入力では、それらも k 倍しないと不変性の検証にならない。
"""


if __name__ == "__main__":
    main()
