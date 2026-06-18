"""数値スナップショットの比較（履歴ベースの回帰/改善追跡）

`run-all` が `_devout/history/<label>/index.json` に残す数値スナップショットを 2 つ読み、
シナリオ単位で結果系（決定的＝回帰検出に使える）と性能系（壁時計＝改善量の目安）を数値比較する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 決定的な結果系の一致判定に使う許容（浮動小数の微小差を無視）
_RESULT_TOL = 1e-6


def available_labels(out_dir: Path) -> list[str]:
    hist = out_dir / "history"
    if not hist.is_dir():
        return []
    return sorted(d.name for d in hist.iterdir() if (d / "index.json").exists())


def resolve_index(ref: str, out_dir: Path) -> tuple[dict[str, Any], Path]:
    """ラベル/`latest`/ファイルパス のいずれかから index.json を読み込む"""
    if ref == "latest":
        path = out_dir / "index.json"
    else:
        path = out_dir / "history" / ref / "index.json"
        if not path.exists() and Path(ref).exists():
            path = Path(ref)
    if not path.exists():
        labels = available_labels(out_dir)
        hint = ", ".join(labels) if labels else "(なし)"
        raise FileNotFoundError(
            f"index が見つかりません: {ref!r}。利用可能ラベル: {hint}（'latest' も指定可）"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh), path


def _runs_by_scenario(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["scenario"]: r for r in index.get("runs", [])}


def _opt(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("optimization") or {}


def _phase_ms(run: dict[str, Any]) -> int:
    opt = _opt(run)
    p1 = (opt.get("phase1") or {}).get("ms", 0) or 0
    p2 = (opt.get("phase2") or {}).get("ms", 0) or 0
    return int(p1) + int(p2)


def _changed(vb: Any, va: Any) -> bool:
    if isinstance(vb, (int, float)) and isinstance(va, (int, float)):
        return abs(float(va) - float(vb)) > _RESULT_TOL + _RESULT_TOL * abs(float(vb))
    return vb != va


def compare(base: dict[str, Any], against: dict[str, Any]) -> list[dict[str, Any]]:
    """シナリオ単位の比較行を返す"""
    b = _runs_by_scenario(base)
    a = _runs_by_scenario(against)
    rows: list[dict[str, Any]] = []
    for name in sorted(set(b) | set(a)):
        rb, ra = b.get(name), a.get(name)
        if rb is None or ra is None:
            rows.append(
                {"scenario": name, "presence": "ADDED" if rb is None else "REMOVED"}
            )
            continue
        ob, oa = _opt(rb), _opt(ra)
        fb = rb.get("forecast") or {}
        fa = ra.get("forecast") or {}
        # 決定的な結果系（回帰検出対象）
        result_fields = {
            "verdict": (rb.get("verdict"), ra.get("verdict")),
            "solver": (ob.get("solver_status"), oa.get("solver_status")),
            "tau*": (ob.get("tau_star"), oa.get("tau_star")),
            "thru": (ob.get("throughput"), oa.get("throughput")),
            "od_pairs": (fb.get("od_pairs"), fa.get("od_pairs")),
            "fallback": (ob.get("fallback_to_previous"), oa.get("fallback_to_previous")),
        }
        changed = [k for k, (vb, va) in result_fields.items() if _changed(vb, va)]
        msb, msa = _phase_ms(rb), _phase_ms(ra)
        rows.append(
            {
                "scenario": name,
                "presence": "BOTH",
                "fields": result_fields,
                "ms": (msb, msa),
                "ms_delta_pct": ((msa - msb) / msb * 100.0) if msb else None,
                "result_changed": changed,
            }
        )
    return rows


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _pair(vb: Any, va: Any) -> str:
    return _fmt(vb) if not _changed(vb, va) else f"{_fmt(vb)}→{_fmt(va)}"


def format_report(
    rows: list[dict[str, Any]], base_label: str, against_label: str
) -> str:
    lines: list[str] = [f"compare: {base_label}  →  {against_label}", ""]
    header = (
        f"{'scenario':24} {'verdict':14} {'solver':16} {'tau*':14} "
        f"{'thru':14} {'ms (Δ%)':18} result"
    )
    lines.append(header)
    lines.append("-" * len(header))

    n_changed = 0
    tot_b = tot_a = 0
    for row in rows:
        if row["presence"] != "BOTH":
            lines.append(f"{row['scenario']:24} [{row['presence']}]")
            continue
        f = row["fields"]
        msb, msa = row["ms"]
        tot_b += msb
        tot_a += msa
        pct = row["ms_delta_pct"]
        ms_cell = f"{msb}→{msa}" + (f" {pct:+.0f}%" if pct is not None else "")
        result = "ok" if not row["result_changed"] else "CHANGED:" + ",".join(row["result_changed"])
        if row["result_changed"]:
            n_changed += 1
        lines.append(
            f"{row['scenario']:24} {_pair(*f['verdict']):14} {_pair(*f['solver']):16} "
            f"{_pair(*f['tau*']):14} {_pair(*f['thru']):14} {ms_cell:18} {result}"
        )

    lines.append("-" * len(header))
    tot_pct = ((tot_a - tot_b) / tot_b * 100.0) if tot_b else 0.0
    both = sum(1 for r in rows if r["presence"] == "BOTH")
    lines.append(
        f"summary: {both} scenarios, result-changed={n_changed}, "
        f"total phase ms {tot_b}→{tot_a} ({tot_pct:+.0f}%)"
    )
    return "\n".join(lines)
