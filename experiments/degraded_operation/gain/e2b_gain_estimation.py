from __future__ import annotations

import itertools
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from _common import md_table, write_outputs
from scipy.signal import lfilter

from devtools.graph_builder import grid
from flow_control.domain import (
    Boundary,
    BoundaryDirection,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
)

DTS = (30, 60)
WINDOWS = (10, 30, 60, 240, 1440, 10080, 43200, 86400)
MAX_SPAN_S = 30 * 86400
FLOWS = (5.0, 20.0, 60.0)
SEEDS = 50
MODELS = ("poisson", "thinned")
PATTERNS = ("bidir", "oneway")
ESTIMATORS = ("ols", "corrected", "iv")
GAIN_LO, GAIN_HI = 0.6, 1.5
TAU_C_MIN = 10.0
SIGMA = 0.4
NOMINAL_CAPACITY = 60.0
ONEWAY_ORIGINS = frozenset({"n0_0", "n2_0", "isl_a"})
ONEWAY_DESTS = frozenset({"n0_2", "n2_2", "isl_b"})


@dataclass(frozen=True)
class Network:
    points: tuple[str, ...]
    nodes: tuple[str, ...]
    sign: np.ndarray
    routes: np.ndarray
    status: dict[str, str]
    reference: str


def log_uniform(rng: np.random.Generator, n: int) -> np.ndarray:
    return np.exp(rng.uniform(math.log(GAIN_LO), math.log(GAIN_HI), n))


def windows_for(dt_s: int) -> tuple[int, ...]:
    return tuple(w for w in WINDOWS if w * dt_s <= MAX_SPAN_S)


def demo_graph() -> tuple[Graph, frozenset[str]]:
    base = grid(3, 3).graph
    entry_exit = Boundary(BoundaryDirection.ENTRY_AND_EXIT, active=True)
    extra_nodes = (
        Node(NodeID("kiosk"), NodeKind.GOAL, True),
        Node(NodeID("isl_a"), NodeKind.GOAL, True, boundary=entry_exit),
        Node(NodeID("isl_t"), NodeKind.TRANSIT_ONLY, True),
        Node(NodeID("isl_b"), NodeKind.GOAL, True, boundary=entry_exit),
    )

    def edge(eid: str, a: str, b: str) -> Edge:
        return Edge(
            EdgeID(eid),
            NodeID(a),
            NodeID(b),
            DirectionConstraint.BIDIRECTIONAL_PRIOR,
            CurrentDirection.BIDIRECTIONAL,
            True,
            ObservationType.VECTOR,
        )

    extra_edges = (
        edge("e_kiosk", "n0_0", "kiosk"),
        edge("e_isl1", "isl_a", "isl_t"),
        edge("e_isl2", "isl_t", "isl_b"),
    )
    blind = next(
        e.edge_id.value
        for e in base.edges
        if {e.endpoint_a.value, e.endpoint_b.value} == {"n2_0", "n2_1"}
    )
    graph = Graph(nodes=base.nodes + extra_nodes, edges=base.edges + extra_edges)
    return graph, frozenset(e.edge_id.value for e in graph.edges) - {blind}


def is_terminal(node: Node) -> bool:
    return node.kind != NodeKind.TRANSIT_ONLY or node.has_active_boundary


def build_network(
    graph: Graph,
    cameras: frozenset[str],
    reference: str | None = None,
    pair_filter: tuple[frozenset[str], frozenset[str]] | None = None,
    paths_per_pair: int = 6,
) -> Network:
    edges = {e.edge_id.value: e for e in graph.enabled_edges()}
    points = sorted(
        e for e in cameras if e in edges and edges[e].observation_type == ObservationType.VECTOR
    )
    index = {p: i for i, p in enumerate(points)}
    usable = []
    for node in graph.enabled_nodes():
        incident = [e for e in edges.values() if node.node_id in (e.endpoint_a, e.endpoint_b)]
        if not is_terminal(node) and incident and all(e.edge_id.value in index for e in incident):
            usable.append(node.node_id.value)
    sign = np.zeros((len(usable), len(points), 2))
    for i, v in enumerate(usable):
        for p, j in index.items():
            if edges[p].endpoint_b.value == v:
                sign[i, j] = (1.0, -1.0)
            elif edges[p].endpoint_a.value == v:
                sign[i, j] = (-1.0, 1.0)

    digraph = nx.DiGraph()
    for e in sorted(edges.values(), key=lambda x: x.edge_id.value):
        a, b = e.endpoint_a.value, e.endpoint_b.value
        if e.current_direction != CurrentDirection.B_TO_A:
            digraph.add_edge(a, (e.edge_id.value, 0))
            digraph.add_edge((e.edge_id.value, 0), b)
        if e.current_direction != CurrentDirection.A_TO_B:
            digraph.add_edge(b, (e.edge_id.value, 1))
            digraph.add_edge((e.edge_id.value, 1), a)
    terminals = sorted(n.node_id.value for n in graph.enabled_nodes() if is_terminal(n))
    goals = {n.node_id.value for n in graph.enabled_nodes() if n.kind == NodeKind.GOAL}
    route_rows = []
    for s, t in itertools.permutations(terminals, 2):
        if pair_filter is not None and (s not in pair_filter[0] or t not in pair_filter[1]):
            continue
        sub = digraph.subgraph(set(digraph.nodes) - (goals - {s, t}))
        if s not in sub or t not in sub or not nx.has_path(sub, s, t):
            continue
        for path in itertools.islice(nx.shortest_simple_paths(sub, s, t), paths_per_pair):
            row = np.zeros((len(points), 2))
            for step in path:
                if isinstance(step, tuple) and step[0] in index:
                    row[index[step[0]], step[1]] += 1.0
            route_rows.append(row)
    routes = np.array(route_rows) if route_rows else np.zeros((0, len(points), 2))

    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    touched = np.zeros(len(points), dtype=bool)
    for i in range(len(usable)):
        members = np.flatnonzero(np.abs(sign[i]).sum(axis=1) > 0)
        touched[members] = True
        for m in members[1:]:
            parent[find(int(m))] = find(int(members[0]))
    if reference is None:
        linked = [p for p in points if touched[index[p]]]
        size = {p: sum(find(index[q]) == find(index[p]) for q in linked) for p in linked}
        reference = min(linked, key=lambda p: (-size[p], p)) if linked else ""
    status = {}
    for p, j in index.items():
        if p == reference:
            status[p] = "reference"
        elif not touched[j]:
            status[p] = "no_constraint"
        elif find(j) == find(index[reference]):
            status[p] = "identifiable"
        else:
            status[p] = "not_linked"
    return Network(tuple(points), tuple(usable), sign, routes, status, reference)


def route_rates(
    net: Network,
    rng: np.random.Generator,
    dt_s: float,
    n_windows: int,
    flow_level: float,
    tau_c_min: float = TAU_C_MIN,
    sigma: float = SIGMA,
) -> np.ndarray:
    n_routes = net.routes.shape[0]
    phi = math.exp(-dt_s / 60.0 / tau_c_min)
    shocks = rng.standard_normal((n_windows, n_routes))
    shocks[0] /= math.sqrt(1 - phi * phi) if phi < 1 else 1.0
    z = lfilter([math.sqrt(1 - phi * phi)], [1.0, -phi], shocks, axis=0)
    weights = rng.uniform(0.5, 1.5, n_routes) * np.exp(sigma * z - sigma * sigma / 2)
    per_edge = np.einsum("r,rpd->p", weights.mean(axis=0), net.routes)
    linked = [i for i, p in enumerate(net.points) if net.status[p] in ("reference", "identifiable")]
    mean_edge = per_edge[linked].mean() if linked else per_edge.mean()
    return weights * (flow_level / mean_edge)


def edge_rates(net: Network, rates: np.ndarray) -> np.ndarray:
    return np.einsum("tr,rpd->tpd", rates, net.routes)


def measure(
    net: Network,
    rates: np.ndarray,
    gains: np.ndarray,
    dt_s: float,
    rng: np.random.Generator,
    model: str,
    b: float = 0.0,
) -> np.ndarray:
    lam = edge_rates(net, rates)
    density = np.clip(lam.sum(axis=2, keepdims=True) / NOMINAL_CAPACITY, 0.0, 1.0)
    gain = gains[None, :, None] * (1.0 - b * density)
    if model == "poisson":
        return rng.poisson(gain * lam * dt_s / 60.0).astype(float)
    people = np.einsum("tr,rpd->tpd", rng.poisson(rates * dt_s / 60.0), net.routes).astype(np.int64)
    under = rng.binomial(people, np.minimum(gain, 1.0))
    over = rng.binomial(people, np.clip(gain - 1.0, 0.0, 1.0))
    return (under + over).astype(float)


def design(net: Network, y: np.ndarray) -> np.ndarray:
    return np.einsum("vpd,tpd->tvp", net.sign, y).reshape(-1, len(net.points))


def null_loaded(a: np.ndarray) -> np.ndarray:
    if a.shape[1] == 0:
        return np.zeros(0, dtype=bool)
    w, v = np.linalg.eigh(a.T @ a)
    top = w.max()
    if top <= 0:
        return np.ones(a.shape[1], dtype=bool)
    null = v[:, w < top * 1e-11]
    return (np.abs(null) > 1e-6).any(axis=1)


def fit(net: Network, y: np.ndarray, estimator: str) -> dict[str, Any]:
    a3 = np.einsum("vpd,tpd->tvp", net.sign, y)
    a = a3.reshape(-1, len(net.points))
    ref = net.points.index(net.reference)
    cols = [
        i
        for i, p in enumerate(net.points)
        if net.status[p] == "identifiable" and np.abs(a[:, i]).sum() > 0
    ]
    gain: dict[str, float | None] = {}
    flag: dict[str, str] = {}
    for i, p in enumerate(net.points):
        if i == ref:
            gain[p], flag[p] = 1.0, "reference"
        elif i not in cols:
            gain[p] = None
            flag[p] = "no_data" if net.status[p] == "identifiable" else net.status[p]
    if not cols:
        return {"gain": gain, "flag": flag}
    sel = [ref, *cols]
    m = a[:, sel]
    if estimator == "iv":
        gram = a3[:-1][:, :, sel].reshape(-1, len(sel)).T @ a3[1:][:, :, sel].reshape(-1, len(sel))
    else:
        gram = m.T @ m
    if estimator == "corrected":
        variance = np.einsum("vp,tpd->p", np.abs(net.sign).max(axis=2), y)
        gram = gram - np.diag(variance[sel])
    loaded = null_loaded(m[:, 1:])
    h = np.linalg.lstsq(gram[1:, 1:], -gram[1:, 0], rcond=None)[0]
    for col, i in enumerate(cols):
        p = net.points[i]
        if loaded[col]:
            gain[p], flag[p] = None, "rank_deficient"
        elif h[col] <= 0:
            gain[p], flag[p] = None, "invalid_sign"
        else:
            gain[p], flag[p] = 1.0 / h[col], "estimated"
    return {"gain": gain, "flag": flag}


def relative_errors(net: Network, est: dict[str, Any], gains: np.ndarray) -> list[float]:
    ref = net.points.index(net.reference)
    return [
        est["gain"][p] / (gains[i] / gains[ref]) - 1.0
        for i, p in enumerate(net.points)
        if est["flag"].get(p) == "estimated"
    ]


def series_errors(
    net: Network,
    dt_s: int,
    flow_level: float,
    seeds: int,
    model: str,
    windows: tuple[int, ...],
    tau_c_min: float = TAU_C_MIN,
    sigma: float = SIGMA,
    salt: int = 0,
    estimators: tuple[str, ...] = ESTIMATORS,
) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {
        (est, w): {"errors": [], "flags": {}, "outcomes": []} for est in estimators for w in windows
    }
    for seed in range(seeds):
        rng = np.random.default_rng([salt, dt_s, int(flow_level * 10), seed])
        gains = log_uniform(rng, len(net.points))
        rates = route_rates(net, rng, dt_s, max(windows), flow_level, tau_c_min, sigma)
        y = measure(net, rates, gains, dt_s, rng, model)
        ref = net.points.index(net.reference)
        for est, w in itertools.product(estimators, windows):
            result = fit(net, y[:w], est)
            cell = out[(est, w)]
            cell["errors"].extend(relative_errors(net, result, gains))
            for i, p in enumerate(net.points):
                if net.status[p] != "identifiable":
                    continue
                f = result["flag"][p]
                cell["flags"][f] = cell["flags"].get(f, 0) + 1
                g_hat = result["gain"][p]
                cell["outcomes"].append(
                    None if g_hat is None else g_hat / (gains[i] / gains[ref]) - 1.0
                )
    return out


def summarize(errs: list[float]) -> dict[str, float]:
    if not errs:
        return {"n": 0, "median": float("nan"), "p90": float("nan")}
    a = np.abs(np.asarray(errs))
    return {"n": int(a.size), "median": float(np.median(a)), "p90": float(np.quantile(a, 0.9))}


def premises(net: Network) -> dict[str, Any]:
    rng = np.random.default_rng(7)
    rates = route_rates(net, rng, 30, 240, 20.0)
    lam = edge_rates(net, rates)
    residual = float(np.abs(np.einsum("vpd,tpd->tv", net.sign, lam)).max())
    assert residual < 1e-9, f"true rates violate conservation by {residual}"
    people = np.einsum("tr,rpd->tpd", rng.poisson(rates * 0.5), net.routes)
    people_residual = float(np.abs(np.einsum("vpd,tpd->tv", net.sign, people)).max())
    assert people_residual == 0.0, "thinned model: true people counts violate conservation"
    gains = log_uniform(rng, len(net.points))
    exact = gains[None, :, None] * lam * 0.5
    ols_err = max(abs(e) for e in relative_errors(net, fit(net, exact, "ols"), gains))
    assert ols_err < 1e-8, f"noise-free OLS failed to recover gains: {ols_err}"
    big = fit(net, measure(net, rates * 1e5, gains, 30, rng, "poisson"), "corrected")
    big_err = max(abs(e) for e in relative_errors(net, big, gains))
    assert big_err < 0.01, f"corrected estimator not consistent at high counts: {big_err}"
    a_all = design(net, exact)
    ref = net.points.index(net.reference)
    cols = [i for i in range(len(net.points)) if i != ref]
    loaded = null_loaded(a_all[:, cols])
    numeric_bad = {net.points[i] for i, f in zip(cols, loaded, strict=True) if f}
    structural_bad = {p for p, s in net.status.items() if s in ("not_linked", "no_constraint")}
    assert numeric_bad == structural_bad, f"structural {structural_bad} vs numeric {numeric_bad}"
    usable = [i for i in cols if net.status[net.points[i]] == "identifiable"]
    const = edge_rates(net, route_rates(net, np.random.default_rng(8), 30, 240, 20.0, sigma=0.0))
    const_rank = int(np.linalg.matrix_rank(design(net, const)[:, usable]))
    var_rank = int(np.linalg.matrix_rank(design(net, exact)[:, usable]))
    assert var_rank == len(usable), f"varying mix rank {var_rank} < {len(usable)}"
    assert const_rank < len(usable), "constant mix unexpectedly identifies all gains"
    return {
        "conservation_residual": residual,
        "noise_free_ols_max_err": ols_err,
        "high_count_corrected_max_err": big_err,
        "structural_unidentifiable": sorted(structural_bad),
        "numeric_unidentifiable": sorted(numeric_bad),
        "free_identifiable": len(usable),
        "rank_varying_mix": var_rank,
        "rank_constant_mix": const_rank,
    }


def density_job(job: tuple[str, float, int]) -> dict[str, Any]:
    model, b, seeds = job
    graph, cameras = demo_graph()
    net = build_network(graph, cameras, reference="e0")
    vs_g0: list[float] = []
    vs_peak: list[float] = []
    for seed in range(seeds):
        rng = np.random.default_rng([99, seed])
        g0 = log_uniform(rng, len(net.points))
        rates = route_rates(net, rng, 60, 43200, 20.0)
        est = fit(net, measure(net, rates, g0, 60, rng, model, b), "iv")
        density = np.clip(edge_rates(net, rates).sum(axis=2) / NOMINAL_CAPACITY, 0.0, 1.0)
        vs_g0.extend(relative_errors(net, est, g0))
        vs_peak.extend(relative_errors(net, est, g0 * (1.0 - b * density.max(axis=0))))
    return {
        "model": model,
        "estimator": "iv",
        "b": b,
        "vs_g0": summarize(vs_g0),
        "vs_peak": summarize(vs_peak),
    }


def sweep_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    graph, cameras = demo_graph()
    pair_filter = (ONEWAY_ORIGINS, ONEWAY_DESTS) if job["pattern"] == "oneway" else None
    net = build_network(graph, cameras, reference="e0", pair_filter=pair_filter)
    cells = series_errors(
        net,
        job["dt"],
        job["flow"],
        SEEDS,
        job["model"],
        windows_for(job["dt"]),
        tau_c_min=job["tau_c"],
    )
    print(f"[e2b] done {job}", file=sys.stderr, flush=True)
    return [
        job | {"estimator": est, "windows": w, "flags": cell["flags"]} | summarize(cell["errors"])
        for (est, w), cell in cells.items()
    ]


def main() -> None:
    graph, cameras = demo_graph()
    nets = {
        "bidir": build_network(graph, cameras, reference="e0"),
        "oneway": build_network(
            graph, cameras, reference="e0", pair_filter=(ONEWAY_ORIGINS, ONEWAY_DESTS)
        ),
    }
    net = nets["bidir"]
    prem = premises(net)
    jobs = [
        {"model": m, "pattern": pt, "dt": dt, "flow": f, "tau_c": TAU_C_MIN}
        for m, pt, dt, f in itertools.product(MODELS, PATTERNS, DTS, FLOWS)
        if (m, pt) == ("poisson", "bidir") or f == 20.0
    ]
    jobs += [
        {"model": m, "pattern": "bidir", "dt": 30, "flow": 20.0, "tau_c": tau}
        for m, tau in itertools.product(MODELS, (2.0, 60.0))
    ]
    density_jobs = [(m, b, 30) for m, b in itertools.product(MODELS, (0.0, 0.2, 0.4))]
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        rows = [r for chunk in pool.map(sweep_job, jobs) for r in chunk]
        density = list(pool.map(density_job, density_jobs))
    sweep = [r for r in rows if r["tau_c"] == TAU_C_MIN]
    tau_sweep = [r for r in rows if r["pattern"] == "bidir" and r["dt"] == 30 and r["flow"] == 20.0]
    payload = {
        "graph": {
            "points": net.points,
            "usable_transit_nodes": net.nodes,
            "status": net.status,
            "reference": net.reference,
            "routes": {k: int(v.routes.shape[0]) for k, v in nets.items()},
            "unobserved_edge": sorted({e.edge_id.value for e in graph.edges} - cameras),
        },
        "settings": {
            "seeds": SEEDS,
            "gain_range": [GAIN_LO, GAIN_HI],
            "tau_c_min": TAU_C_MIN,
            "sigma": SIGMA,
            "nominal_capacity": NOMINAL_CAPACITY,
            "max_span_days": MAX_SPAN_S / 86400,
        },
        "premises": prem,
        "sweep": sweep,
        "tau_sweep": tau_sweep,
        "density": density,
    }
    write_outputs("e2b_gain_estimation", payload, render(payload))


def fmt(x: float) -> str:
    return "-" if math.isnan(x) else f"{100 * x:.1f}%"


def span(w: int, dt: int) -> str:
    minutes = w * dt / 60
    if minutes < 120:
        return f"{minutes:g} 分"
    if minutes < 2880:
        return f"{minutes / 60:g} 時間"
    return f"{minutes / 1440:g} 日"


def cell_text(r: dict[str, Any]) -> str:
    bad = r["flags"].get("invalid_sign", 0) + r["flags"].get("rank_deficient", 0)
    total = sum(r["flags"].values())
    return f"{fmt(r['median'])} / {fmt(r['p90'])}" + (f" (欠測 {bad}/{total})" if bad else "")


def pick(p: dict[str, Any], **key: Any) -> dict[str, Any]:
    return next(r for r in p["sweep"] if all(r[k] == v for k, v in key.items()))


def render(p: dict[str, Any]) -> str:
    g, s, prem = p["graph"], p["settings"], p["premises"]
    ident = sum(1 for v in g["status"].values() if v == "identifiable")
    out = ["# E2(b): 保存則による相対ゲインの推定", ""]
    out.append("## 要点")
    out.append("")
    out.append(
        "エンジンが 1 リクエストで見る 30 分（Δt=30 秒で 60 窓）と、上流の観測サービスが持つ 30 日"
        "（86400 窓）での、iv 推定の相対誤差 中央値 / p90（流量 20 人/分、自由点 9 × 50 シード）。"
    )
    out.append("")
    out.append(
        md_table(
            ["観測モデル/流れ", "60 窓（30 分）", "86400 窓（30 日）"],
            [
                [
                    f"{m}/{pt}",
                    *[
                        cell_text(
                            pick(
                                p, model=m, pattern=pt, estimator="iv", dt=30, flow=20.0, windows=w
                            )
                        )
                        for w in (60, 86400)
                    ],
                ]
                for m, pt in itertools.product(MODELS, PATTERNS)
            ],
        )
    )
    out.append("")
    out.append("## グラフと設定")
    out.append("")
    out.append(
        "devtools の grid(3,3) を土台にした。四隅が入退出点、内部 5 ノードが通過専用ノードで、"
        "全 12 エッジに方向別のラインカメラを置く。全エッジが少なくとも 1 つの通過ノードに接するので、"
        "保存則だけで全点を参照点とつなげられる。これを「通過ノードが全観測」の基準形とした。"
        "識別不能の検出を確かめるため、次の 3 つを意図的に加えた。"
    )
    out.append("")
    out.append(
        f"- 未観測エッジ {g['unobserved_edge'][0]}（n2_0–n2_1）。n2_1 の保存則が使えなくなり、"
        "n2_1 と隅の n2_2 を結ぶ e11 は制約を持たない。"
    )
    out.append("- e_kiosk。入退出点 n0_0 と目的地 kiosk を結ぶ。通過ノードに接しない。")
    out.append("- 孤立部分 isl_a–isl_t–isl_b。内部では保存則が成り立つが、参照点とはつながらない。")
    out.append("")
    out.append(
        f"参照点は {g['reference']}、使える通過ノードは {list(g['usable_transit_nodes'])}、"
        f"参照点とつながる自由点は {ident} 個。経路数は bidir（全端点対、両向き）が "
        f"{g['routes']['bidir']}、oneway（西の端点から東の端点へだけ）が {g['routes']['oneway']}。"
    )
    out.append("")
    out.append(md_table(["点", "構造上の判定"], [[k, v] for k, v in sorted(g["status"].items())]))
    out.append("")
    out.append(
        f"真の流量は経路単位で与える。各経路の率は AR(1) の対数正規過程で、相関時間 {s['tau_c_min']:g} 分、"
        f"対数標準偏差 {s['sigma']}。経路の流量を足すので、通過ノードの保存則は真の流量で厳密に成り立つ。"
        f"g_e は [{s['gain_range'][0]}, {s['gain_range'][1]}] の対数一様。シードは各設定 {s['seeds']}。"
        f"窓数は最長 {s['max_span_days']:g} 日分までとした。流量水準は参照点とつながる点の平均エッジ流量"
        "（両方向の和、人/分）で表す。観測モデルは 2 つ用意した。"
    )
    out.append("")
    out.append(
        "- poisson: 観測カウント ~ Poisson(g_e·λ_e·Δt) をエッジ・方向ごとに独立に引く。"
        "依頼文の「保存則に従う真の流量に Poisson のカウント雑音」をそのまま読んだもの。"
        "到着のゆらぎもすべて観測雑音として扱うので、窓ごとの保存則は期待値でしか成り立たない。悲観側。"
    )
    out.append(
        "- thinned: 経路ごとの人数を Poisson で引き、真の人数は窓ごとに保存則を厳密に満たす。"
        "カメラは一人ずつ g≤1 なら確率 g で数え、g>1 なら確率 g−1 で二重に数える。"
        "雑音は検知の取りこぼし・二重計数だけになる。楽観側。"
    )
    out.append("")
    out.append("## 推定式")
    out.append("")
    out.append(
        "未知数は逆ゲイン h_e = 1/g_e。通過ノード v と窓 t ごとに Σ_e h_e·(流入カウント − 流出カウント) = 0 "
        "が成り立ち、h について線形・斉次になる。斉次なので全体の倍率は決まらない。参照点の h を 1 に固定して"
        "右辺へ移し、最小二乗で解く（ols）。説明変数のカウント自体が雑音を含むので、ols は h を 0 側へ縮める"
        "（errors-in-variables の減衰）。そこで正規方程式 AᵀA から雑音分散の期待値 D を引く補正版（corrected）も"
        "用意した。D は対角で、D_ee = Σ_(行) Σ_方向 y_e。poisson モデルの分散 = 平均を観測カウントで推定している。"
        "thinned モデルでは分散が g(1−g) 倍に小さく、この D は過補正になる。"
        "3 つ目の iv は、1 窓前の同じノードの行を操作変数にする。観測雑音は窓ごとに独立で、経路配分は"
        "相関時間をもって続くので、Σ_t a_(t−1)ᵀ a_t h = 0 は雑音分散を知らなくても偏らない。"
        "代わりに、配分が窓をまたいで続く成分しか使えない。"
        "解く前に、参照点と保存則でつながらない点（構造判定）と、設計行列の零空間に重みを持つ点（数値判定）を"
        "除外し、値を出さずに理由を返す。h ≤ 0 になった点も値を出さない（表の「欠測」）。"
    )
    out.append("")
    out.append("## 前提の確認")
    out.append("")
    out.append(
        md_table(
            ["確認", "結果"],
            [
                ["真の流量の保存則残差（最大）", f"{prem['conservation_residual']:.1e}"],
                ["thinned の真の人数の保存則残差", "0（assert）"],
                ["雑音なし・ols の最大相対誤差", f"{prem['noise_free_ols_max_err']:.1e}"],
                [
                    "流量 10 万倍・poisson・corrected の最大相対誤差",
                    fmt(prem["high_count_corrected_max_err"]),
                ],
                ["構造判定の識別不能点", ", ".join(prem["structural_unidentifiable"])],
                [
                    "数値判定（雑音なしの設計行列の零空間）の識別不能点",
                    ", ".join(prem["numeric_unidentifiable"]),
                ],
                [
                    "参照点とつながる自由点の列の階数（経路配分が変動、雑音なし）",
                    f"{prem['rank_varying_mix']}/{prem['free_identifiable']}",
                ],
                [
                    "同（経路配分が一定、σ=0、雑音なし）",
                    f"{prem['rank_constant_mix']}/{prem['free_identifiable']}",
                ],
            ],
        )
    )
    out.append("")
    out.append(
        "構造判定と数値判定は一致した。数値判定は雑音なしのデータで行った。雑音があると孤立部分の斉次な式は"
        "数値上は正則に見え、最小二乗は h=0（ĝ=∞）を返すだけになるので、構造判定のほうを推定の前段に置いている。"
        "経路配分が一定だと階数が落ち、窓をいくら増やしても推定できない。"
        "効くのは窓の数そのものではなく、経路配分が独立に変わった回数である。"
    )
    out.append("")
    out.append("## 窓数・流量水準と推定誤差（poisson、bidir）")
    out.append("")
    out.append(
        f"相対誤差は |ĝ_e/(g_e/g_ref) − 1|。参照点とつながる自由点 {ident} 個 × {s['seeds']} シードを"
        "プールした中央値 / p90。「欠測 a/b」は h ≤ 0 か零空間で値を出さなかった点の数。"
    )
    out.append("")
    for dt in DTS:
        out.append(f"### Δt = {dt} 秒")
        out.append("")
        rows = []
        for flow, w in itertools.product(FLOWS, windows_for(dt)):
            key = {"model": "poisson", "pattern": "bidir", "dt": dt, "flow": flow, "windows": w}
            rows.append(
                [
                    f"{flow:g}",
                    str(w),
                    span(w, dt),
                    *[cell_text(pick(p, estimator=e, **key)) for e in ESTIMATORS],
                ]
            )
        out.append(md_table(["流量 人/分", "窓数", "期間", *ESTIMATORS], rows))
        out.append("")
    out.append("## 観測モデルと流れの向きの影響（流量 20 人/分、iv）")
    out.append("")
    for dt in DTS:
        out.append(f"### Δt = {dt} 秒")
        out.append("")
        combos = list(itertools.product(MODELS, PATTERNS))
        rows = [
            [
                str(w),
                span(w, dt),
                *[
                    cell_text(
                        pick(p, model=m, pattern=pt, estimator="iv", dt=dt, flow=20.0, windows=w)
                    )
                    for m, pt in combos
                ],
            ]
            for w in windows_for(dt)
        ]
        out.append(md_table(["窓数", "期間", *[f"{m}/{pt}" for m, pt in combos]], rows))
        out.append("")
    out.append(
        "bidir では同じ通路を両向きに人が通る。保存則の情報は流入と流出の差（正味の流れ）にしかないが、"
        "カウント雑音は両向きの総数に比例する。oneway はこの比が良い場合の比較である。"
    )
    out.append("")
    out.append("## 経路配分の相関時間への依存（bidir、Δt=30 秒、流量 20、iv）")
    out.append("")
    out.append(
        md_table(
            ["モデル", "相関時間 分", *[f"{w} 窓" for w in windows_for(30)]],
            [
                [
                    model,
                    f"{tau:g}",
                    *[
                        f"{fmt(r['median'])} / {fmt(r['p90'])}"
                        for w in windows_for(30)
                        for r in p["tau_sweep"]
                        if r["tau_c"] == tau
                        and r["windows"] == w
                        and r["model"] == model
                        and r["estimator"] == "iv"
                    ],
                ]
                for model, tau in itertools.product(MODELS, (2.0, 10.0, 60.0))
            ],
        )
    )
    out.append("")
    out.append("## 密度依存ゲイン（bidir、Δt=60 秒、43200 窓 = 30 日、流量 20、30 シード）")
    out.append("")
    out.append(
        f"g_e(t) = g0_e·(1 − b·ρ_e(t))、ρ_e(t) = min(1, エッジ流量/{s['nominal_capacity']:g} 人/分)。"
        "一定値 ĝ を当てはめ、g0 の比と、各点の系列中で最も混んだ窓のゲインの比（サージ時に相当）の両方と比べた。"
    )
    out.append("")
    out.append(
        md_table(
            [
                "モデル",
                "推定式",
                "b",
                "g0 比との誤差 中央値 / p90",
                "ピーク時ゲイン比との誤差 中央値 / p90",
            ],
            [
                [
                    d["model"],
                    d["estimator"],
                    f"{d['b']:g}",
                    f"{fmt(d['vs_g0']['median'])} / {fmt(d['vs_g0']['p90'])}",
                    f"{fmt(d['vs_peak']['median'])} / {fmt(d['vs_peak']['p90'])}",
                ]
                for d in p["density"]
            ],
        )
    )
    out.append("")
    out.append(WHAT_ELSE)
    return "\n".join(out) + "\n"


WHAT_ELSE = """## この数字が別のものを測っている可能性

- 推定式の偏り: ols は errors-in-variables で縮む。窓を増やしても ols の誤差が下げ止まるなら、それはデータ量の不足ではなく推定式の偏りである。corrected・iv との差がその大きさを示す。thinned では corrected の D が過補正になるので、モデル比較の表は iv に絞った（corrected の値も JSON にある）。
- 観測モデル: poisson と thinned は両端の想定で、実際のカメラはその間にある。窓をまたぐ滞留（通過ノード内の移動時間で、ある窓の流入が次の窓の流出になる）はどちらにも入れていない。30 秒窓ではこれが残差を増やし、必要な窓数を増やす方向に効く。
- 経路配分の変動量: 必要な窓数は σ と相関時間に強く依存する。相関時間の表のとおり、効くのは窓の数より独立な配分変化の回数である。実際の会場の配分変動はまだ測っていない。
- 流れの向き: bidir と oneway の差は、正味の流れと総数の比で決まる。実際の通路でこの比を測る必要がある。
- グラフの偏り: grid(3,3) は全エッジが通過ノードに接する好条件の形である。E2(c) の表のとおり、devtools の 11 シナリオのグラフで使える通過ノードは、5 つが 0 個、5 つが 1 個、crossing-detour だけが 3 個である。
"""


if __name__ == "__main__":
    main()
