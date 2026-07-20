"""各モジュール結果の可視化（matplotlib + networkx レイアウト、静的 PNG）

ベースとなるグラフ骨格（ノード種別・境界・危険フラグ・エッジ方向・スカラー破線）を描き、
その上に各モジュール（Detection / Forecasting / DetourRouting / Optimization）の結果を
オーバーレイして PNG として保存する。Agg バックエンドで headless かつ決定的。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.patches import FancyArrowPatch  # noqa: E402

from flow_control.domain import (  # noqa: E402
    CurrentDirection,
    Edge,
    Graph,
    NodeKind,
    ObservationType,
)

from .graph_builder import BuiltGraph, Position, resolve_positions  # noqa: E402
from .pipeline import PipelineRun  # noqa: E402

_KIND_COLOR = {
    NodeKind.GOAL: "#7bc96f",
    NodeKind.GOAL_TRANSIT_MIXED: "#f2a154",
    NodeKind.TRANSIT_ONLY: "#9ecbe8",
}
_TRIGGER_COLOR = "#d62728"
_NODE_SIZE = 700.0


# --- 低水準ヘルパー ---------------------------------------------------------


def _limits(
    pos: dict[str, Position],
) -> tuple[tuple[float, float], tuple[float, float]]:
    xs = [p[0] for p in pos.values()] or [0.0]
    ys = [p[1] for p in pos.values()] or [0.0]
    mx = max(0.6, (max(xs) - min(xs)) * 0.18 + 0.4)
    my = max(0.6, (max(ys) - min(ys)) * 0.18 + 0.4)
    return (min(xs) - mx, max(xs) + mx), (min(ys) - my, max(ys) + my)


def _setup_ax(ax: Any, pos: dict[str, Position], title: str) -> None:
    (xlo, xhi), (ylo, yhi) = _limits(pos)
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=12)


def _arrow(
    ax: Any,
    pa: Position,
    pb: Position,
    *,
    color: Any,
    width: float = 2.0,
    rad: float = 0.0,
    alpha: float = 1.0,
    zorder: int = 3,
) -> None:
    ax.annotate(
        "",
        xy=pb,
        xytext=pa,
        zorder=zorder,
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=width,
            alpha=alpha,
            shrinkA=16,
            shrinkB=16,
            connectionstyle=f"arc3,rad={rad}",
        ),
    )


def _edge_endpoints(pos: dict[str, Position], edge: Edge) -> tuple[Position, Position]:
    return pos[edge.endpoint_a.value], pos[edge.endpoint_b.value]


def _parallel_edge_radii(graph: Graph) -> dict[str, float]:
    """並行エッジを決定的な曲線レーンへ割り当てる。

    曲率は無向のノード対と edge_id で決める。端点の記述順が逆のエッジでも、
    同一の物理レーンをたどるよう符号を補正する。
    """
    groups: dict[tuple[str, str], list[Edge]] = {}
    for edge in graph.edges:
        endpoint_a, endpoint_b = edge.endpoint_a.value, edge.endpoint_b.value
        key = (min(endpoint_a, endpoint_b), max(endpoint_a, endpoint_b))
        groups.setdefault(key, []).append(edge)

    radii: dict[str, float] = {}
    for endpoints, edges in groups.items():
        ordered = sorted(edges, key=lambda edge: edge.edge_id.value)
        count = len(ordered)
        for index, edge in enumerate(ordered):
            lane = 0.0 if count == 1 else (index - (count - 1) / 2.0) * 0.28
            is_canonical = (edge.endpoint_a.value, edge.endpoint_b.value) == endpoints
            radii[edge.edge_id.value] = lane if is_canonical else -lane
    return radii


def _edge_line(
    ax: Any,
    pa: Position,
    pb: Position,
    *,
    color: Any,
    width: float,
    rad: float,
    linestyle: Any = "-",
    alpha: float = 1.0,
    zorder: int = 1,
) -> None:
    """直線または曲線レーンとしてエッジ本体を描く。"""
    if abs(rad) < 1e-9:
        ax.plot(
            [pa[0], pb[0]],
            [pa[1], pb[1]],
            color=color,
            lw=width,
            ls=linestyle,
            alpha=alpha,
            zorder=zorder,
            solid_capstyle="round",
        )
        return
    ax.add_patch(
        FancyArrowPatch(
            pa,
            pb,
            arrowstyle="-",
            connectionstyle=f"arc3,rad={rad}",
            color=color,
            linewidth=width,
            linestyle=linestyle,
            alpha=alpha,
            zorder=zorder,
        )
    )


def draw_base(
    ax: Any,
    graph: Graph,
    pos: dict[str, Position],
    *,
    title: str = "",
    edge_alpha: float = 1.0,
    show_edge_labels: bool = True,
    show_direction: bool = True,
) -> None:
    """グラフ骨格を描く（ノード種別・境界・危険フラグ、エッジ方向・スカラー破線）"""
    _setup_ax(ax, pos, title)

    lane_radii = _parallel_edge_radii(graph)
    for edge in graph.edges:
        pa, pb = _edge_endpoints(pos, edge)
        enabled = edge.enabled
        color = "#888888" if enabled else "#dddddd"
        ls = ":" if edge.observation_type == ObservationType.SCALAR else "-"
        rad = lane_radii[edge.edge_id.value]
        _edge_line(
            ax, pa, pb, color=color, width=2.0, rad=rad, linestyle=ls,
            alpha=edge_alpha, zorder=1,
        )
        if show_direction and enabled:
            cd = edge.current_direction
            if cd == CurrentDirection.A_TO_B:
                _arrow(ax, pa, pb, color=color, width=1.4, rad=rad, alpha=0.7, zorder=2)
            elif cd == CurrentDirection.B_TO_A:
                _arrow(ax, pb, pa, color=color, width=1.4, rad=-rad, alpha=0.7, zorder=2)
        if show_edge_labels:
            mid = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0)
            ax.annotate(
                edge.edge_id.value,
                mid,
                fontsize=7,
                color="#444444",
                ha="center",
                va="center",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.6),
                zorder=10,  # ハイライト（zorder 3）より上に置きラベルの隠れを防ぐ
            )

    for node in graph.nodes:
        p = pos[node.node_id.value]
        face = _KIND_COLOR.get(node.kind, "#cccccc") if node.enabled else "#dddddd"
        if node.danger_flag:
            edgecolor, lw = _TRIGGER_COLOR, 3.0
        elif node.is_boundary:
            edgecolor, lw = "#111111", 2.6
        else:
            edgecolor, lw = "#555555", 1.0
        ax.scatter(
            [p[0]],
            [p[1]],
            s=_NODE_SIZE,
            c=[face],
            edgecolors=edgecolor,
            linewidths=lw,
            zorder=5,
        )
        ax.annotate(
            node.node_id.value,
            p,
            fontsize=8,
            ha="center",
            va="center",
            bbox=dict(
                boxstyle="round,pad=0.14",
                fc="white",
                ec="none",
                alpha=0.9,
            ),
            # 方向矢印・重要度・危険ハイライトより常に前面に置く。
            zorder=30,
        )


def _highlight_edges(
    ax: Any,
    graph: Graph,
    pos: dict[str, Position],
    edge_ids: set[str],
    *,
    color: str,
    width: float = 5.0,
    alpha: float = 0.9,
) -> None:
    lane_radii = _parallel_edge_radii(graph)
    for edge in graph.edges:
        if edge.edge_id.value not in edge_ids:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        _edge_line(
            ax, pa, pb, color=color, width=width,
            rad=lane_radii[edge.edge_id.value], alpha=alpha, zorder=3,
        )


def _highlight_nodes(
    ax: Any,
    pos: dict[str, Position],
    node_ids: set[str],
    *,
    color: str,
) -> None:
    for nid in node_ids:
        if nid not in pos:
            continue
        p = pos[nid]
        ax.scatter(
            [p[0]],
            [p[1]],
            s=_NODE_SIZE + 600.0,
            facecolors="none",
            edgecolors=color,
            linewidths=3.0,
            zorder=7,
        )


def _save(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_legend(
    path: Path,
    *,
    title: str,
    lines: list[str],
    handles: list[Any] | None = None,
    colorbar: tuple[Any, Normalize, str] | None = None,
) -> None:
    """旧グラフ内の視覚キーだけを、独立した白背景 PNG として出力する。"""
    # 呼出し側 API との互換性のため受け取るが、凡例には文章を表示しない。
    del title, lines
    handle_rows = (len(handles) + 1) // 2 if handles else 0
    height = max(0.7, 0.2 + 0.32 * handle_rows)
    if colorbar is not None:
        height += 0.75
    fig, ax = plt.subplots(figsize=(7, height))
    ax.axis("off")
    if handles:
        fig.legend(
            handles=handles,
            loc="lower left",
            bbox_to_anchor=(0.12, 0.05 + (0.14 if colorbar else 0.0)),
            fontsize=8,
            frameon=False,
            ncol=2,
        )
    if colorbar is not None:
        cmap, norm, label = colorbar
        cax = fig.add_axes((0.13, 0.04, 0.74, 0.08))
        bar = fig.colorbar(
            ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal"
        )
        bar.set_label(label, fontsize=8)
        bar.ax.tick_params(labelsize=7)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _kind_legend_handles() -> list[Any]:
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=c,
            markersize=10,
            markeredgecolor="#555555",
            label=k.value,
        )
        for k, c in _KIND_COLOR.items()
    ]
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="white",
            markersize=10,
            markeredgecolor="#111111",
            markeredgewidth=2.4,
            label="boundary",
        )
    )
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="white",
            markersize=10,
            markeredgecolor=_TRIGGER_COLOR,
            markeredgewidth=2.4,
            label="danger_flag",
        )
    )
    return handles


def _line_legend_handle(
    label: str,
    *,
    color: str,
    width: float = 3.0,
    linestyle: Any = "-",
) -> Any:
    from matplotlib.lines import Line2D

    return Line2D([0], [0], color=color, lw=width, ls=linestyle, label=label)


def _legend_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}_legend.png")


# --- グラフのみ -------------------------------------------------------------


def render_graph(built: BuiltGraph, path: Path, *, title: str = "graph") -> None:
    pos = resolve_positions(built)
    fig, ax = plt.subplots(figsize=(9, 7))
    draw_base(ax, built.graph, pos, title=title)
    _save(fig, path)
    render_legend(
        path.with_name(f"{path.stem}_legend.png"),
        title=f"{title} — legend",
        lines=["Node and edge conventions"],
        handles=_kind_legend_handles(),
    )


# --- Detection --------------------------------------------------------------


def _evidence_line(ev: Any) -> str:
    """トリガー根拠を 1 行に整形する（種別ごとに観測値・閾値を明示）"""
    name = type(ev).__name__
    if name == "SurgeEvidence":
        return (
            f"surge {ev.edge_id.value}: "
            f"{ev.rate_percent_per_min:.1f}%/min > {ev.threshold_percent_per_min:.0f}"
        )
    if name == "HighStagnationEvidence":
        return (
            f"stagnation {ev.edge_id.value}: s={ev.stagnation:.1f} "
            f">= p90 {ev.percentile_threshold:.1f} ({ev.duration_min:.0f}min)"
        )
    if name == "DangerEvidence":
        edge_id = getattr(ev, "edge_id", None)
        node_id = getattr(ev, "node_id", None)
        target = edge_id.value if edge_id else (node_id.value if node_id else "?")
        return f"danger {target}"
    if name == "QueueScoreEvidence":
        return f"queue score {ev.accumulated_score:.1f} > {ev.score_threshold:.1f}"
    if name == "QueueDiversityEvidence":
        return (
            f"queue diversity {ev.distinct_origin_count} > {ev.diversity_threshold}"
        )
    if name == "QueueExpiredEvidence":
        return f"queue expired (dropped {ev.dropped_count})"
    return name


def render_detection(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    pos = resolve_positions(built)
    det = run.detection
    fig, ax = plt.subplots(figsize=(9, 7))
    draw_base(
        ax, built.graph, pos, title=f"Detection — verdict={det.verdict_hint.value}"
    )
    _highlight_edges(
        ax,
        built.graph,
        pos,
        {e.value for e in det.triggered_edges},
        color=_TRIGGER_COLOR,
    )
    _highlight_nodes(
        ax, pos, {n.value for n in det.triggered_nodes}, color=_TRIGGER_COLOR
    )

    lines = [f"mode = {run.mode.value}", f"verdict = {det.verdict_hint.value}"]
    if det.triggered_edges:
        lines.append(
            "triggered edges: " + ", ".join(e.value for e in det.triggered_edges)
        )
    if det.triggered_nodes:
        lines.append(
            "triggered nodes: " + ", ".join(n.value for n in det.triggered_nodes)
        )
    if det.evidences:
        lines.append("evidence:")
        for ev in det.evidences[:8]:
            lines.append(f"  · {_evidence_line(ev)}")
    from matplotlib.lines import Line2D

    handles = _kind_legend_handles()
    handles.append(
        Line2D([0], [0], color=_TRIGGER_COLOR, lw=4, label="triggered")
    )
    _save(fig, path)
    render_legend(
        path.with_name(f"{path.stem}_legend.png"),
        title="Detection — legend",
        lines=lines,
        handles=handles,
    )


# --- Forecasting ------------------------------------------------------------


def render_forecasting(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    if run.forecast is None:
        return
    pos = resolve_positions(built)
    fc = run.forecast
    graph = built.graph
    fig, axes = plt.subplots(2, 2, figsize=(16, 13))

    # (1) 点需要: マーカーサイズ ∝ gross_in+gross_out、色 ∝ 滞在量
    ax = axes[0][0]
    draw_base(
        ax,
        graph,
        pos,
        title="Forecasting — node demand (size∝gross, color∝staying)",
        show_edge_labels=False,
        edge_alpha=0.5,
    )
    demand_by = {d.node_id.value: d for d in fc.node_demand}
    stays = [d.staying for d in fc.node_demand] or [0.0]
    norm = Normalize(vmin=min(stays), vmax=max(max(stays), 1e-6))
    cmap = plt.get_cmap("YlOrRd")
    for node in graph.nodes:
        d = demand_by.get(node.node_id.value)
        if d is None:
            continue
        p = pos[node.node_id.value]
        size = 300.0 + (d.gross_in + d.gross_out) * 12.0
        ax.scatter(
            [p[0]],
            [p[1]],
            s=size,
            c=[cmap(norm(d.staying))],
            edgecolors="#333333",
            linewidths=1.2,
            zorder=8,
        )
        ax.annotate(
            f"in {d.gross_in:.0f}/out {d.gross_out:.0f}\nstay {d.staying:.0f}",
            (p[0], p[1]),
            fontsize=6,
            ha="center",
            va="center",
            zorder=9,
        )
    fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap), ax=ax, fraction=0.046, label="staying"
    )

    # (2) OD フロー: origin→destination の曲線矢印、太さ ∝ demand
    ax = axes[0][1]
    draw_base(
        ax,
        graph,
        pos,
        title="Forecasting — OD demand (arrow width∝demand)",
        show_edge_labels=False,
        edge_alpha=0.4,
        show_direction=False,
    )
    od = fc.od_matrix
    dmax = max((o.demand for o in od), default=1.0)
    for o in od:
        if o.origin.value not in pos or o.destination.value not in pos:
            continue
        _arrow(
            ax,
            pos[o.origin.value],
            pos[o.destination.value],
            color="#1f77b4",
            width=1.0 + 5.0 * o.demand / dmax,
            rad=0.2,
            alpha=0.8,
            zorder=4,
        )
        mid = (
            (pos[o.origin.value][0] + pos[o.destination.value][0]) / 2.0,
            (pos[o.origin.value][1] + pos[o.destination.value][1]) / 2.0,
        )
        ax.annotate(f"{o.demand:.0f}", mid, fontsize=7, color="#1f77b4", zorder=5)
    if not od:
        ax.text(
            0.5,
            0.5,
            "OD matrix empty",
            transform=ax.transAxes,
            ha="center",
            fontsize=11,
            color="#888",
        )

    # (3) フロー感度 η: エッジ色
    ax = axes[1][0]
    draw_base(
        ax,
        graph,
        pos,
        title="Forecasting — arc flow sensitivity η",
        show_edge_labels=False,
        edge_alpha=0.25,
        show_direction=False,
    )
    eta_by = {a.edge_id.value: a.eta for a in fc.arc_flow_sensitivity}
    etas = list(eta_by.values()) or [0.0]
    enorm = Normalize(vmin=min(etas), vmax=max(max(etas), 1e-6))
    ecmap = plt.get_cmap("viridis")
    # 観測が無くフォールバック eta を使ったエッジ（センサ無し区間）を破線で明示
    fallback_edges = {e.value for e in fc.fallback_usage.used_default_edges} | {
        e.value for e in fc.fallback_usage.used_reference_edges
    }
    for edge in graph.edges:
        if edge.edge_id.value not in eta_by:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        ax.plot(
            [pa[0], pb[0]],
            [pa[1], pb[1]],
            color=ecmap(enorm(eta_by[edge.edge_id.value])),
            lw=5.0,
            zorder=3,
            solid_capstyle="round",
        )
        if edge.edge_id.value in fallback_edges:
            ax.plot(
                [pa[0], pb[0]],
                [pa[1], pb[1]],
                color="#111111",
                lw=1.6,
                ls=(0, (2, 2)),
                zorder=4,
            )
    if fallback_edges:
        ax.plot([], [], color="#111111", ls=(0, (2, 2)), lw=1.6, label="fallback η (no obs)")
        ax.legend(loc="lower right", fontsize=7, framealpha=0.9)
    fig.colorbar(
        ScalarMappable(norm=enorm, cmap=ecmap), ax=ax, fraction=0.046, label="η"
    )

    # (4) ノード信頼度
    ax = axes[1][1]
    draw_base(
        ax,
        graph,
        pos,
        title="Forecasting — node confidence",
        show_edge_labels=False,
        edge_alpha=0.3,
        show_direction=False,
    )
    conf_by = {c.node_id.value: c.confidence for c in fc.node_confidence}
    cnorm = Normalize(vmin=0.0, vmax=1.0)
    ccmap = plt.get_cmap("RdYlGn")
    for node in graph.nodes:
        if node.node_id.value not in conf_by:
            continue
        p = pos[node.node_id.value]
        ax.scatter(
            [p[0]],
            [p[1]],
            s=_NODE_SIZE,
            c=[ccmap(cnorm(conf_by[node.node_id.value]))],
            edgecolors="#333",
            linewidths=1.2,
            zorder=8,
        )
        ax.annotate(
            f"{conf_by[node.node_id.value]:.2f}",
            p,
            fontsize=7,
            ha="center",
            va="center",
            zorder=9,
        )
    fig.colorbar(
        ScalarMappable(norm=cnorm, cmap=ccmap),
        ax=ax,
        fraction=0.046,
        label="confidence",
    )

    fig.suptitle(
        f"Forecasting (reproduction_error={fc.reproduction_error:.4g})", fontsize=13
    )
    _save(fig, path)


def _forecast_ax(run: PipelineRun, built: BuiltGraph) -> tuple[Any, Any, Any, Any]:
    """Forecasting の個別図用に共通の描画コンテキストを作る。"""
    fig, ax = plt.subplots(figsize=(9, 7))
    return fig, ax, resolve_positions(built), run.forecast


def render_forecasting_node_demand(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    fig, ax, pos, fc = _forecast_ax(run, built)
    if fc is None:
        plt.close(fig)
        return
    graph = built.graph
    draw_base(ax, graph, pos, title="Forecasting — node demand", show_edge_labels=False, edge_alpha=0.5)
    demand_by = {d.node_id.value: d for d in fc.node_demand}
    stays = [d.staying for d in fc.node_demand] or [0.0]
    norm, cmap = Normalize(vmin=min(stays), vmax=max(max(stays), 1e-6)), plt.get_cmap("YlOrRd")
    for node in graph.nodes:
        d = demand_by.get(node.node_id.value)
        if d is None:
            continue
        p = pos[node.node_id.value]
        ax.scatter([p[0]], [p[1]], s=300.0 + (d.gross_in + d.gross_out) * 12.0, c=[cmap(norm(d.staying))], edgecolors="#333333", linewidths=1.2, zorder=8)
    _save(fig, path)


def render_forecasting_od_demand(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    fig, ax, pos, fc = _forecast_ax(run, built)
    if fc is None:
        plt.close(fig)
        return
    graph, od = built.graph, fc.od_matrix
    draw_base(ax, graph, pos, title="Forecasting — OD demand", show_edge_labels=False, edge_alpha=0.4, show_direction=False)
    dmax = max((o.demand for o in od), default=1.0)
    for o in od:
        if o.origin.value not in pos or o.destination.value not in pos:
            continue
        _arrow(ax, pos[o.origin.value], pos[o.destination.value], color="#1f77b4", width=1.0 + 5.0 * o.demand / dmax, rad=0.2, alpha=0.8, zorder=4)
    if not od:
        ax.text(0.5, 0.5, "OD matrix empty", transform=ax.transAxes, ha="center", fontsize=11, color="#888")
    _save(fig, path)


def render_forecasting_arc_flow_sensitivity(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    fig, ax, pos, fc = _forecast_ax(run, built)
    if fc is None:
        plt.close(fig)
        return
    graph = built.graph
    lane_radii = _parallel_edge_radii(graph)
    draw_base(ax, graph, pos, title="Forecasting — arc flow sensitivity", show_edge_labels=False, edge_alpha=0.25, show_direction=False)
    eta_by = {a.edge_id.value: a.eta for a in fc.arc_flow_sensitivity}
    etas, ecmap = list(eta_by.values()) or [0.0], plt.get_cmap("viridis")
    enorm = Normalize(vmin=min(etas), vmax=max(max(etas), 1e-6))
    fallback_edges = {e.value for e in fc.fallback_usage.used_default_edges} | {e.value for e in fc.fallback_usage.used_reference_edges}
    for edge in graph.edges:
        if edge.edge_id.value not in eta_by:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        _edge_line(
            ax, pa, pb, color=ecmap(enorm(eta_by[edge.edge_id.value])), width=5.0,
            rad=lane_radii[edge.edge_id.value], zorder=3,
        )
        if edge.edge_id.value in fallback_edges:
            _edge_line(
                ax, pa, pb, color="#111111", width=1.6,
                rad=lane_radii[edge.edge_id.value], linestyle=(0, (2, 2)), zorder=4,
            )
    _save(fig, path)


def render_forecasting_node_confidence(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    fig, ax, pos, fc = _forecast_ax(run, built)
    if fc is None:
        plt.close(fig)
        return
    graph = built.graph
    draw_base(ax, graph, pos, title="Forecasting — node confidence", show_edge_labels=False, edge_alpha=0.3, show_direction=False)
    conf_by, ccmap, cnorm = {c.node_id.value: c.confidence for c in fc.node_confidence}, plt.get_cmap("RdYlGn"), Normalize(vmin=0.0, vmax=1.0)
    for node in graph.nodes:
        if node.node_id.value not in conf_by:
            continue
        p = pos[node.node_id.value]
        ax.scatter([p[0]], [p[1]], s=_NODE_SIZE, c=[ccmap(cnorm(conf_by[node.node_id.value]))], edgecolors="#333", linewidths=1.2, zorder=8)
    _save(fig, path)


# --- DetourRouting ----------------------------------------------------------


def render_detour(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    if run.detour is None:
        return
    pos = resolve_positions(built)
    graph = built.graph
    sets = run.detour.detour_sets
    if not sets:
        fig, ax = plt.subplots(figsize=(9, 7))
        draw_base(ax, graph, pos, title="DetourRouting — no detour sets")
        _save(fig, path)
        return

    n = len(sets)
    cols = min(2, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(8 * cols, 6 * rows), squeeze=False)
    palette = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#e377c2"]
    for idx, ds in enumerate(sets):
        ax = axes[idx // cols][idx % cols]
        draw_base(
            ax,
            graph,
            pos,
            title=f"Detour origin={ds.origin_edge.value} (k_eff={ds.k_effective})",
            edge_alpha=0.3,
            show_edge_labels=False,
            show_direction=False,
        )
        _highlight_edges(
            ax, graph, pos, {ds.origin_edge.value}, color=_TRIGGER_COLOR, width=6.0
        )
        for pi, p in enumerate(ds.paths):
            color = palette[pi % len(palette)]
            label = (
                "direct"
                if p.contains_trigger
                else f"detour{pi} (len {p.total_length:.1f})"
            )
            _highlight_edges(
                ax,
                graph,
                pos,
                {e.value for e in p.edge_ids},
                color=color,
                width=3.0 - 0.0 * pi,
                alpha=0.7,
            )
            ax.plot([], [], color=color, lw=3.0, label=label)
        ax.legend(loc="upper right", fontsize=7, framealpha=0.9)
    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")
    _save(fig, path)


def render_detour_set(built: BuiltGraph, detour_set: Any, path: Path) -> None:
    """1 つの起点エッジの迂回候補だけを 1 枚に描く。"""
    pos, graph = resolve_positions(built), built.graph
    fig, ax = plt.subplots(figsize=(9, 7))
    draw_base(ax, graph, pos, title="DetourRouting — candidate paths", edge_alpha=0.3, show_edge_labels=False, show_direction=False)
    _highlight_edges(ax, graph, pos, {detour_set.origin_edge.value}, color=_TRIGGER_COLOR, width=6.0)
    palette = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#e377c2"]
    for index, route in enumerate(detour_set.paths):
        color = palette[index % len(palette)]
        _highlight_edges(ax, graph, pos, {edge.value for edge in route.edge_ids}, color=color, width=3.0, alpha=0.7)
    _save(fig, path)


# --- Optimization -----------------------------------------------------------

_IMP_DIR_ARROW = {"A_TO_B": 1, "B_TO_A": -1, "NONE": 0}


def render_optimization_route_importance(
    run: PipelineRun, built: BuiltGraph, path: Path
) -> None:
    """重要度と実フロー方向を 1 枚に描く。"""
    if run.optimization is None:
        return
    pos, graph = resolve_positions(built), built.graph
    lane_radii = _parallel_edge_radii(graph)
    res = run.optimization.optimization_result
    fig, ax = plt.subplots(figsize=(10, 8))
    draw_base(ax, graph, pos, title="Optimization — route importance", edge_alpha=0.2, show_edge_labels=False, show_direction=False)
    imp_by, cmap, norm = {r.edge_id.value: r for r in res.route_importance}, plt.get_cmap("plasma"), Normalize(vmin=0.0, vmax=1.0)
    for edge in graph.edges:
        route = imp_by.get(edge.edge_id.value)
        if route is None:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        color = cmap(norm(route.importance))
        rad = lane_radii[edge.edge_id.value]
        _edge_line(
            ax, pa, pb, color=color, width=1.5 + 6.0 * route.importance,
            rad=rad, zorder=3, alpha=0.9,
        )
        direction = _IMP_DIR_ARROW.get(route.direction.value, 0)
        if direction == 1:
            _arrow(ax, pa, pb, color=color, width=1.6, rad=rad, alpha=0.9, zorder=4)
        elif direction == -1:
            _arrow(ax, pb, pa, color=color, width=1.6, rad=-rad, alpha=0.9, zorder=4)
    triggered_edges = {edge.value for edge in run.detection.triggered_edges}
    for edge in graph.edges:
        if edge.edge_id.value in triggered_edges:
            pa, pb = _edge_endpoints(pos, edge)
            _edge_line(
                ax, pa, pb, color=_TRIGGER_COLOR, width=1.6,
                rad=lane_radii[edge.edge_id.value], linestyle=(0, (2, 2)), zorder=6,
            )
    _highlight_nodes(ax, pos, {node.value for node in run.detection.triggered_nodes}, color=_TRIGGER_COLOR)
    _save(fig, path)


def render_optimization_direction_proposal(
    run: PipelineRun, built: BuiltGraph, path: Path
) -> None:
    """方向属性・境界制御の提案とソルバー結果を 1 枚に描く。"""
    if run.optimization is None:
        return
    pos, graph, opt = resolve_positions(built), built.graph, run.optimization
    lane_radii = _parallel_edge_radii(graph)
    res = opt.optimization_result
    fig, ax = plt.subplots(figsize=(10, 8))
    draw_base(ax, graph, pos, title="Optimization — direction proposal", edge_alpha=0.25, show_edge_labels=False, show_direction=False)
    edge_by = {edge.edge_id.value: edge for edge in graph.edges}
    for proposal in res.direction_proposal:
        edge = edge_by.get(proposal.edge_id.value)
        if edge is None:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        rad = lane_radii[edge.edge_id.value]
        direction = proposal.proposed_direction.value
        if direction == "A_TO_B":
            _arrow(ax, pa, pb, color="#2ca02c", width=2.4, rad=rad, zorder=4)
        elif direction == "B_TO_A":
            _arrow(ax, pb, pa, color="#2ca02c", width=2.4, rad=-rad, zorder=4)
        else:
            forward_rad = rad if abs(rad) >= 1e-9 else 0.12
            _arrow(ax, pa, pb, color="#1f77b4", width=1.8, rad=forward_rad, zorder=4)
            _arrow(ax, pb, pa, color="#1f77b4", width=1.8, rad=-forward_rad, zorder=4)
    for control in res.boundary_control:
        if control.node_id.value not in pos:
            continue
        _highlight_nodes(ax, pos, {control.node_id.value}, color=_TRIGGER_COLOR)
    _save(fig, path)


def render_optimization(run: PipelineRun, built: BuiltGraph, path: Path) -> None:
    if run.optimization is None:
        return
    pos = resolve_positions(built)
    graph = built.graph
    opt = run.optimization
    res = opt.optimization_result
    stats = opt.solver_stats
    fig, axes = plt.subplots(1, 2, figsize=(18, 8))

    # (1) ルート重要度: エッジ色・太さ ∝ importance、方向矢印
    ax = axes[0]
    draw_base(
        ax,
        graph,
        pos,
        title="Optimization — route importance + direction",
        edge_alpha=0.2,
        show_edge_labels=True,
        show_direction=False,
    )
    imp_by = {(r.edge_id.value): r for r in res.route_importance}
    norm = Normalize(vmin=0.0, vmax=1.0)
    cmap = plt.get_cmap("plasma")
    for edge in graph.edges:
        r = imp_by.get(edge.edge_id.value)
        if r is None:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        col = cmap(norm(r.importance))
        ax.plot(
            [pa[0], pb[0]],
            [pa[1], pb[1]],
            color=col,
            lw=1.5 + 6.0 * r.importance,
            zorder=3,
            solid_capstyle="round",
            alpha=0.9,
        )
        d = _IMP_DIR_ARROW.get(r.direction.value, 0)
        if d == 1:
            _arrow(ax, pa, pb, color=col, width=1.6, alpha=0.9, zorder=4)
        elif d == -1:
            _arrow(ax, pb, pa, color=col, width=1.6, alpha=0.9, zorder=4)
    # 文脈として「トリガー起点」を破線で重畳（重要度は実フロー経路に付くため別物）
    trig_edges = {e.value for e in run.detection.triggered_edges}
    for edge in graph.edges:
        if edge.edge_id.value in trig_edges:
            pa, pb = _edge_endpoints(pos, edge)
            ax.plot(
                [pa[0], pb[0]],
                [pa[1], pb[1]],
                color=_TRIGGER_COLOR,
                lw=1.6,
                ls=(0, (2, 2)),
                zorder=6,
            )
    _highlight_nodes(
        ax, pos, {n.value for n in run.detection.triggered_nodes}, color=_TRIGGER_COLOR
    )
    if trig_edges or run.detection.triggered_nodes:
        ax.plot([], [], color=_TRIGGER_COLOR, ls=(0, (2, 2)), lw=1.6, label="triggered")
        ax.legend(loc="lower right", fontsize=7, framealpha=0.9)
    fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap), ax=ax, fraction=0.046, label="importance"
    )

    # (2) 方向属性提案 + 境界制御
    ax = axes[1]
    draw_base(
        ax,
        graph,
        pos,
        title="Optimization — direction proposal + boundary control",
        edge_alpha=0.25,
        show_edge_labels=True,
        show_direction=False,
    )
    edge_by = {e.edge_id.value: e for e in graph.edges}
    for dp in res.direction_proposal:
        edge = edge_by.get(dp.edge_id.value)
        if edge is None:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        pd = dp.proposed_direction.value
        if pd == "A_TO_B":
            _arrow(ax, pa, pb, color="#2ca02c", width=2.4, zorder=4)
        elif pd == "B_TO_A":
            _arrow(ax, pb, pa, color="#2ca02c", width=2.4, zorder=4)
        else:  # BIDIRECTIONAL
            _arrow(ax, pa, pb, color="#1f77b4", width=1.8, rad=0.12, zorder=4)
            _arrow(ax, pb, pa, color="#1f77b4", width=1.8, rad=0.12, zorder=4)
        ax.annotate(
            dp.change_type.value,
            ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2),
            fontsize=6,
            color="#2ca02c",
        )
    for restriction in res.restriction_proposal:
        edge = edge_by.get(restriction.edge_id.value)
        if edge is None:
            continue
        pa, pb = _edge_endpoints(pos, edge)
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color="#d62728", lw=5.0, alpha=0.5, zorder=5)
    _BND_LABEL = {
        "PAUSE_INGRESS": "PAUSE-IN",
        "PAUSE_EGRESS": "PAUSE-OUT",
        "RESUME": "RESUME",
    }
    for bc in res.boundary_control:
        if bc.node_id.value not in pos:
            continue
        p = pos[bc.node_id.value]
        _highlight_nodes(ax, pos, {bc.node_id.value}, color="#d62728")
        ax.annotate(
            _BND_LABEL.get(bc.action.value, bc.action.value),
            (p[0], p[1] + 0.25),
            fontsize=8,
            color="#d62728",
            ha="center",
            zorder=10,
        )

    info = [
        f"solver_status = {res.solver_status.value}",
        f"phase1 = {stats.phase1_status.value} ({stats.phase1_ms} ms)",
        f"phase2 = {stats.phase2_status.value} ({stats.phase2_ms} ms)",
        f"tau* = {res.objective_values.tau_star:.4g}",
        f"throughput = {res.objective_values.throughput:.4g}",
        f"restrictions = {len(res.restriction_proposal)}",
        f"fallback_to_previous = {opt.constraint_report.fallback_to_previous}",
        f"local_reachability = {opt.constraint_report.local_reachability_satisfied}",
        f"boundary_reachability = {opt.constraint_report.boundary_reachability_satisfied}",
    ]
    if res.solver_status.value == "LIGHTWEIGHT":
        info.append(f"zones = {stats.zones_processed}, greedy = {stats.greedy_iterations}")
    ax.text(
        0.01,
        0.99,
        "\n".join(info),
        transform=ax.transAxes,
        fontsize=8,
        va="top",
        ha="left",
        family="monospace",
        bbox=dict(boxstyle="round", fc="#f3f0ff", ec="#6a3d9a", alpha=0.9),
    )
    _save(fig, path)


# --- サマリ -----------------------------------------------------------------


def render_summary(
    run: PipelineRun, path: Path, *, invariants: list[str] | None = None
) -> None:
    """実行サマリをテキストで描く（各モジュールの所要時間は数値で列挙）"""
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.axis("off")
    det = run.detection

    lines = [
        f"scenario       : {run.scenario_name}",
        f"mode           : {run.mode.value}",
        f"verdict        : {det.verdict_hint.value}",
        f"downstream ran : {run.downstream_ran}",
    ]
    if det.triggered_edges:
        lines.append(
            "triggered edges: " + ", ".join(e.value for e in det.triggered_edges)
        )
    if det.triggered_nodes:
        lines.append(
            "triggered nodes: " + ", ".join(n.value for n in det.triggered_nodes)
        )

    # 各モジュールの所要時間（数値表示）と合計
    lines.append("")
    lines.append("elapsed (ms):")
    total = 0.0
    for step in ("detection", "forecasting", "detour", "optimization"):
        if step in run.timings_ms:
            ms = run.timings_ms[step]
            total += ms
            lines.append(f"  {step:<13}: {ms:10.1f}")
    lines.append(f"  {'total':<13}: {total:10.1f}")

    if run.optimization is not None:
        res = run.optimization.optimization_result
        st = run.optimization.solver_stats
        cr = run.optimization.constraint_report
        lines += [
            "",
            f"solver         : {res.solver_status.value}",
            f"  phase1       : {st.phase1_status.value} ({st.phase1_ms} ms)",
            f"  phase2       : {st.phase2_status.value} ({st.phase2_ms} ms)",
            f"tau*           : {res.objective_values.tau_star:.4g}",
            f"throughput     : {res.objective_values.throughput:.4g}  (sum flow over P arcs)",
            f"fallback       : {cr.fallback_to_previous}",
        ]
        if res.solver_status.value == "LIGHTWEIGHT":
            lines.append(
                f"  lightweight : zones={st.zones_processed}, greedy={st.greedy_iterations},"
                f" assign={st.assign_lp_ms} ms, build={st.build_ms} ms, greedy={st.greedy_ms} ms"
                + (" [TRUNCATED]" if st.greedy_truncated else "")
            )
        if res.restriction_proposal:
            lines.append(f"restrictions  : {len(res.restriction_proposal)}")
    if run.forecast is not None:
        lines.append(f"OD pairs       : {len(run.forecast.od_matrix)}")
        lines.append(f"reproduction_e : {run.forecast.reproduction_error:.4g}")
    for note in run.notes:
        lines.append(f"note: {note}")
    if invariants:
        lines.append("")
        lines.append("invariants:")
        lines += [f"  {iv}" for iv in invariants]

    ax.text(
        0.02,
        0.98,
        "\n".join(lines),
        transform=ax.transAxes,
        fontsize=11,
        va="top",
        ha="left",
        family="monospace",
    )
    ax.set_title(f"summary — {run.scenario_name}", fontsize=13)
    _save(fig, path)


# --- まとめて出力 -----------------------------------------------------------


def render_all(
    run: PipelineRun,
    built: BuiltGraph,
    out_dir: Path,
    *,
    invariants: list[str] | None = None,
) -> list[Path]:
    """1 回の実行について、モジュール別ディレクトリに個別の図を出力する。

    複数の観点を持つモジュールは、比較・共有しやすいようサブプロットを合成せず、
    それぞれ独立した PNG として保存する。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    p = out_dir / "01_detection" / "trigger.png"
    render_detection(run, built, p)
    written.append(p)
    written.append(_legend_path(p))

    if run.forecast is not None:
        forecast_dir = out_dir / "02_forecasting"
        p = forecast_dir / "node_demand.png"
        render_forecasting_node_demand(run, built, p)
        written.append(p)
        demands = run.forecast.node_demand
        render_legend(
            _legend_path(p),
            title="Forecasting — node demand legend",
            lines=[
                "Circle size: gross incoming + outgoing demand",
                "Circle color: staying demand",
            ],
            handles=_kind_legend_handles(),
            colorbar=(
                plt.get_cmap("YlOrRd"),
                Normalize(
                    vmin=min((d.staying for d in demands), default=0.0),
                    vmax=max(max((d.staying for d in demands), default=0.0), 1e-6),
                ),
                "staying",
            ),
        )
        written.append(_legend_path(p))
        p = forecast_dir / "od_demand.png"
        render_forecasting_od_demand(run, built, p)
        written.append(p)
        od = run.forecast.od_matrix
        render_legend(
            _legend_path(p),
            title="Forecasting — OD demand legend",
            lines=[
                "Blue arrow: origin → destination",
                "Arrow width: relative OD demand",
                f"OD pairs: {len(od)}",
            ],
            handles=[_line_legend_handle("OD demand", color="#1f77b4")],
        )
        written.append(_legend_path(p))
        p = forecast_dir / "arc_flow_sensitivity.png"
        render_forecasting_arc_flow_sensitivity(run, built, p)
        written.append(p)
        sensitivities = run.forecast.arc_flow_sensitivity
        render_legend(
            _legend_path(p),
            title="Forecasting — arc flow sensitivity legend",
            lines=[
                "Edge color: flow sensitivity η",
                "Dotted overlay: fallback η (no observation)",
            ],
            handles=[
                _line_legend_handle("fallback η", color="#111111", linestyle=(0, (2, 2))),
            ],
            colorbar=(
                plt.get_cmap("viridis"),
                Normalize(
                    vmin=min((item.eta for item in sensitivities), default=0.0),
                    vmax=max(max((item.eta for item in sensitivities), default=0.0), 1e-6),
                ),
                "η",
            ),
        )
        written.append(_legend_path(p))
        p = forecast_dir / "node_confidence.png"
        render_forecasting_node_confidence(run, built, p)
        written.append(p)
        render_legend(
            _legend_path(p),
            title="Forecasting — node confidence legend",
            lines=[
                "Node color: confidence (red = low, green = high)",
            ],
            colorbar=(plt.get_cmap("RdYlGn"), Normalize(vmin=0.0, vmax=1.0), "confidence"),
        )
        written.append(_legend_path(p))
    if run.detour is not None:
        detour_dir = out_dir / "03_detour"
        if run.detour.detour_sets:
            for idx, detour_set in enumerate(run.detour.detour_sets, start=1):
                p = detour_dir / f"{idx:02d}_{detour_set.origin_edge.value}.png"
                render_detour_set(built, detour_set, p)
                written.append(p)
                palette = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#e377c2"]
                render_legend(
                    _legend_path(p),
                    title="DetourRouting — candidate paths legend",
                    lines=[
                        f"trigger edge: {detour_set.origin_edge.value}",
                        f"k effective: {detour_set.k_effective}",
                        *[
                            ("direct" if route.contains_trigger else f"detour {index}")
                            + f": length {route.total_length:.3g}; "
                            + ", ".join(edge.value for edge in route.edge_ids)
                            for index, route in enumerate(detour_set.paths)
                        ],
                    ],
                    handles=[
                        _line_legend_handle(
                            "trigger edge", color=_TRIGGER_COLOR, width=6.0
                        ),
                        *[
                            _line_legend_handle(
                                "direct" if route.contains_trigger else f"detour {index}",
                                color=palette[index % len(palette)],
                            )
                            for index, route in enumerate(detour_set.paths)
                        ],
                    ],
                )
                written.append(_legend_path(p))
        else:
            p = detour_dir / "no_detour_sets.png"
            render_detour(run, built, p)
            written.append(p)
            render_legend(
                _legend_path(p),
                title="DetourRouting — legend",
                lines=["No detour sets were generated."],
                handles=_kind_legend_handles(),
            )
            written.append(_legend_path(p))
    if run.optimization is not None:
        optimization_dir = out_dir / "04_optimization"
        p = optimization_dir / "route_importance.png"
        render_optimization_route_importance(run, built, p)
        written.append(p)
        result = run.optimization.optimization_result
        render_legend(
            _legend_path(p),
            title="Optimization — route importance legend",
            lines=[
                "Edge color and width: route importance",
                "Arrow: observed flow direction",
                "Red dotted edge/ring: detection trigger",
            ],
            handles=[
                _line_legend_handle("triggered", color=_TRIGGER_COLOR, linestyle=(0, (2, 2))),
            ],
            colorbar=(plt.get_cmap("plasma"), Normalize(vmin=0.0, vmax=1.0), "importance"),
        )
        written.append(_legend_path(p))
        p = optimization_dir / "direction_proposal.png"
        render_optimization_direction_proposal(run, built, p)
        written.append(p)
        stats = run.optimization.solver_stats
        report = run.optimization.constraint_report
        render_legend(
            _legend_path(p),
            title="Optimization — direction proposal legend",
            lines=[
                f"solver: {result.solver_status.value}",
                f"phase 1 / phase 2: {stats.phase1_status.value} ({stats.phase1_ms} ms) / "
                f"{stats.phase2_status.value} ({stats.phase2_ms} ms)",
                f"tau*: {result.objective_values.tau_star:.4g}",
                f"throughput: {result.objective_values.throughput:.4g}",
                f"fallback: {report.fallback_to_previous}",
                f"local / boundary reachability: {report.local_reachability_satisfied} / "
                f"{report.boundary_reachability_satisfied}",
                *[
                    f"{item.edge_id.value}: {item.proposed_direction.value} "
                    f"({item.change_type.value})"
                    for item in result.direction_proposal
                ],
                *[
                    f"boundary {item.node_id.value}: {item.action.value}"
                    for item in result.boundary_control
                ],
            ],
            handles=[
                _line_legend_handle("one-way proposal", color="#2ca02c"),
                _line_legend_handle("bidirectional proposal", color="#1f77b4"),
                _line_legend_handle("boundary control", color=_TRIGGER_COLOR, width=4.0),
            ],
        )
        written.append(_legend_path(p))

    p = out_dir / "00_summary" / "summary.png"
    render_summary(run, p, invariants=invariants)
    written.append(p)
    return written
