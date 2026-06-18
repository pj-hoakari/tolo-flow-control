"""グラフ構築ツール

簡潔な spec から ``flow_control.domain.Graph`` を組むビルダー、代表的な位相の
プリセット、YAML/JSON での load/save、描画用レイアウト座標の解決を提供する。
ドメインの ``Node`` には座標を持たせず、devtools 側で ``positions`` として保持する。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from flow_control.domain import (
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

Position = tuple[float, float]


@dataclass(frozen=True)
class BuiltGraph:
    """グラフと描画用座標の束。座標は省略可（無ければ自動レイアウト）"""

    graph: Graph
    positions: dict[str, Position] = field(default_factory=dict)


class GraphBuilder:
    """ノード・エッジを宣言的に積み上げて ``BuiltGraph`` を組み立てる"""

    def __init__(self) -> None:
        self._nodes: list[Node] = []
        self._edges: list[Edge] = []
        self._positions: dict[str, Position] = {}

    def node(
        self,
        node_id: str,
        *,
        kind: NodeKind = NodeKind.GOAL,
        boundary: bool = False,
        enabled: bool = True,
        tags: tuple[str, ...] = (),
        time_resolution_s: int = 60,
        danger_flag: bool = False,
        danger_capacity: float | None = None,
        pos: Position | None = None,
    ) -> "GraphBuilder":
        self._nodes.append(
            Node(
                node_id=NodeID(node_id),
                kind=kind,
                is_boundary=boundary,
                enabled=enabled,
                attribute_tags=tags,
                time_resolution_s=time_resolution_s,
                danger_flag=danger_flag,
                danger_capacity=danger_capacity,
            )
        )
        if pos is not None:
            self._positions[node_id] = pos
        return self

    def edge(
        self,
        edge_id: str,
        a: str,
        b: str,
        *,
        direction_constraint: DirectionConstraint = DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction: CurrentDirection = CurrentDirection.BIDIRECTIONAL,
        enabled: bool = True,
        observation_type: ObservationType = ObservationType.VECTOR,
        tags: tuple[str, ...] = (),
        time_resolution_s: int = 60,
        danger_flag: bool = False,
        danger_capacity: float | None = None,
        capacity_hint: float | None = None,
    ) -> "GraphBuilder":
        self._edges.append(
            Edge(
                edge_id=EdgeID(edge_id),
                endpoint_a=NodeID(a),
                endpoint_b=NodeID(b),
                direction_constraint=direction_constraint,
                current_direction=current_direction,
                enabled=enabled,
                observation_type=observation_type,
                attribute_tags=tags,
                time_resolution_s=time_resolution_s,
                danger_flag=danger_flag,
                danger_capacity=danger_capacity,
                capacity_hint=capacity_hint,
            )
        )
        return self

    def build(self) -> BuiltGraph:
        return BuiltGraph(
            graph=Graph(nodes=tuple(self._nodes), edges=tuple(self._edges)),
            positions=dict(self._positions),
        )


# --- レイアウト解決 ---------------------------------------------------------


def resolve_positions(built: BuiltGraph, *, seed: int = 42) -> dict[str, Position]:
    """全ノードの座標を返す。欠損があれば networkx の spring_layout で補完する"""
    node_ids = [n.node_id.value for n in built.graph.nodes]
    if all(nid in built.positions for nid in node_ids) and node_ids:
        return {nid: built.positions[nid] for nid in node_ids}

    g: "nx.Graph[str]" = nx.Graph()
    g.add_nodes_from(node_ids)
    for e in built.graph.edges:
        g.add_edge(e.endpoint_a.value, e.endpoint_b.value)
    raw = nx.spring_layout(g, seed=seed) if node_ids else {}
    return {nid: (float(raw[nid][0]), float(raw[nid][1])) for nid in node_ids}


# --- 永続化（YAML / JSON）---------------------------------------------------


def to_dict(built: BuiltGraph) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": n.node_id.value,
                "kind": n.kind.value,
                "boundary": n.is_boundary,
                "enabled": n.enabled,
                "tags": list(n.attribute_tags),
                "time_resolution_s": n.time_resolution_s,
                "danger_flag": n.danger_flag,
                "danger_capacity": n.danger_capacity,
                "pos": list(built.positions[n.node_id.value])
                if n.node_id.value in built.positions
                else None,
            }
            for n in built.graph.nodes
        ],
        "edges": [
            {
                "id": e.edge_id.value,
                "a": e.endpoint_a.value,
                "b": e.endpoint_b.value,
                "direction_constraint": e.direction_constraint.value,
                "current_direction": e.current_direction.value,
                "enabled": e.enabled,
                "observation_type": e.observation_type.value,
                "tags": list(e.attribute_tags),
                "time_resolution_s": e.time_resolution_s,
                "danger_flag": e.danger_flag,
                "danger_capacity": e.danger_capacity,
                "capacity_hint": e.capacity_hint,
            }
            for e in built.graph.edges
        ],
    }


def from_dict(data: dict[str, Any]) -> BuiltGraph:
    builder = GraphBuilder()
    for n in data.get("nodes", []):
        pos = n.get("pos")
        builder.node(
            n["id"],
            kind=NodeKind(n.get("kind", NodeKind.GOAL.value)),
            boundary=bool(n.get("boundary", False)),
            enabled=bool(n.get("enabled", True)),
            tags=tuple(n.get("tags", []) or ()),
            time_resolution_s=int(n.get("time_resolution_s", 60)),
            danger_flag=bool(n.get("danger_flag", False)),
            danger_capacity=n.get("danger_capacity"),
            pos=(float(pos[0]), float(pos[1])) if pos else None,
        )
    for e in data.get("edges", []):
        builder.edge(
            e["id"],
            e["a"],
            e["b"],
            direction_constraint=DirectionConstraint(
                e.get("direction_constraint", DirectionConstraint.BIDIRECTIONAL_PRIOR.value)
            ),
            current_direction=CurrentDirection(
                e.get("current_direction", CurrentDirection.BIDIRECTIONAL.value)
            ),
            enabled=bool(e.get("enabled", True)),
            observation_type=ObservationType(
                e.get("observation_type", ObservationType.VECTOR.value)
            ),
            tags=tuple(e.get("tags", []) or ()),
            time_resolution_s=int(e.get("time_resolution_s", 60)),
            danger_flag=bool(e.get("danger_flag", False)),
            danger_capacity=e.get("danger_capacity"),
            capacity_hint=e.get("capacity_hint"),
        )
    return builder.build()


def save(built: BuiltGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = to_dict(built)
    with path.open("w", encoding="utf-8") as fh:
        if path.suffix.lower() in (".yaml", ".yml"):
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        else:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


def load(path: Path) -> BuiltGraph:
    with path.open("r", encoding="utf-8") as fh:
        if path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(fh)
        else:
            data = json.load(fh)
    return from_dict(data)


# --- プリセット位相 ---------------------------------------------------------


def linear(n: int = 4) -> BuiltGraph:
    """直線パス: 両端が入退出点、中間は結節点。隣接ノードをベクトル双方向エッジで接続"""
    b = GraphBuilder()
    for i in range(n):
        is_end = i == 0 or i == n - 1
        b.node(
            f"n{i}",
            kind=NodeKind.GOAL if is_end else NodeKind.TRANSIT_ONLY,
            boundary=is_end,
            pos=(float(i), 0.0),
        )
    for i in range(n - 1):
        b.edge(f"e{i}", f"n{i}", f"n{i + 1}")
    return b.build()


def y_junction() -> BuiltGraph:
    """Y 型: 中心結節点から 3 本のエッジが入退出点の末端へ伸びる"""
    b = GraphBuilder()
    b.node("nc", kind=NodeKind.TRANSIT_ONLY, pos=(0.0, 0.0))
    leaves = {"n1": (1.0, 1.0), "n2": (1.0, -1.0), "n3": (-1.2, 0.0)}
    for nid, pos in leaves.items():
        b.node(nid, kind=NodeKind.GOAL, boundary=True, pos=pos)
    b.edge("e1", "nc", "n1")
    b.edge("e2", "nc", "n2")
    b.edge("e3", "nc", "n3")
    return b.build()


def grid(rows: int = 3, cols: int = 3) -> BuiltGraph:
    """格子: 四隅が入退出点、内部は結節点。横・縦に隣接ノードを接続"""
    b = GraphBuilder()

    def nid(r: int, c: int) -> str:
        return f"n{r}_{c}"

    corners = {(0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1)}
    for r in range(rows):
        for c in range(cols):
            is_corner = (r, c) in corners
            b.node(
                nid(r, c),
                kind=NodeKind.GOAL if is_corner else NodeKind.TRANSIT_ONLY,
                boundary=is_corner,
                pos=(float(c), float(rows - 1 - r)),
            )
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                b.edge(f"e{idx}", nid(r, c), nid(r, c + 1))
                idx += 1
            if r + 1 < rows:
                b.edge(f"e{idx}", nid(r, c), nid(r + 1, c))
                idx += 1
    return b.build()


def ring(n: int = 6) -> BuiltGraph:
    """環状: 2 つの対向ノードが入退出点、残りは結節点"""
    b = GraphBuilder()
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        is_boundary = i in (0, n // 2)
        b.node(
            f"n{i}",
            kind=NodeKind.GOAL if is_boundary else NodeKind.TRANSIT_ONLY,
            boundary=is_boundary,
            pos=(math.cos(angle), math.sin(angle)),
        )
    for i in range(n):
        b.edge(f"e{i}", f"n{i}", f"n{(i + 1) % n}")
    return b.build()


def venue() -> BuiltGraph:
    """会場想定: 2 つの入退出点、結節点 2、混在ホール 2。in→out の経路が複数あり迂回路が生まれる"""
    b = GraphBuilder()
    b.node("in", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 1.0))
    b.node("j1", kind=NodeKind.TRANSIT_ONLY, pos=(1.0, 1.0))
    b.node("hallA", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(2.0, 2.0))
    b.node("hallB", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(2.0, 0.0))
    b.node("j2", kind=NodeKind.TRANSIT_ONLY, pos=(3.0, 1.0))
    b.node("out", kind=NodeKind.GOAL, boundary=True, pos=(4.0, 1.0))

    b.edge("e_in_j1", "in", "j1", capacity_hint=80.0)
    b.edge("e_j1_hallA", "j1", "hallA")
    b.edge("e_j1_hallB", "j1", "hallB")
    b.edge("e_hallA_j2", "hallA", "j2")
    b.edge("e_hallB_j2", "hallB", "j2")
    # 直結コリドー（スカラー観測・容量ヒント付き＝パンク制約の確認用）
    b.edge(
        "e_j1_j2",
        "j1",
        "j2",
        observation_type=ObservationType.SCALAR,
        capacity_hint=50.0,
    )
    b.edge("e_j2_out", "j2", "out", capacity_hint=80.0)
    return b.build()


def expo() -> BuiltGraph:
    """現実的な展示会場想定: 出入り口 1 箇所・ホール 4 つ・一方通行の周回コリドー

    - ``gate``: 唯一の入退出点（Open モード）
    - ``lobby`` / ``concourse``: 結節点（concourse が中央ハブ）
    - ``hallA``〜``hallD``: 混在ホール（GOAL_TRANSIT_MIXED）。concourse と双方向スポークで接続
    - 周回コリドー ``hallA→hallB→hallD→hallC→hallA``: 時計回りの**一方通行**（LEGAL_FIXED）
      スポークが双方向のため可達性は保たれ、一方通行ループは循環導線として機能する
    - ``e_con_C`` はスカラー観測（パンク制約の確認用）
    """
    b = GraphBuilder()
    b.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, -2.6))
    b.node("lobby", kind=NodeKind.TRANSIT_ONLY, pos=(0.0, -1.3))
    b.node("concourse", kind=NodeKind.TRANSIT_ONLY, pos=(0.0, 0.0))
    b.node("hallA", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(-2.2, 1.6))
    b.node("hallB", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(2.2, 1.6))
    b.node("hallC", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(-2.2, -0.7))
    b.node("hallD", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(2.2, -0.7))

    # 入退出アクセス
    b.edge("e_gate_lobby", "gate", "lobby", capacity_hint=120.0)
    b.edge("e_lobby_con", "lobby", "concourse", capacity_hint=120.0)

    # concourse からの双方向スポーク
    b.edge("e_con_A", "concourse", "hallA")
    b.edge("e_con_B", "concourse", "hallB")
    b.edge(
        "e_con_C",
        "concourse",
        "hallC",
        observation_type=ObservationType.SCALAR,
        capacity_hint=60.0,
    )
    b.edge("e_con_D", "concourse", "hallD")

    # 時計回りの一方通行ループ A→B→D→C→A
    def _oneway(eid: str, a: str, c: str) -> None:
        b.edge(
            eid,
            a,
            c,
            direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
            current_direction=CurrentDirection.A_TO_B,
        )

    _oneway("e_loop_AB", "hallA", "hallB")
    _oneway("e_loop_BD", "hallB", "hallD")
    _oneway("e_loop_DC", "hallD", "hallC")
    _oneway("e_loop_CA", "hallC", "hallA")
    return b.build()


def crossing() -> BuiltGraph:
    """2 ハブ間を結ぶ主通路＋並行バイパス 2 本（迂回提案が映える現実的レイアウト）

    - 入退出点 ``in`` / ``out``、ハブ ``hub_w`` / ``hub_e``（``hub_e`` は目的地＝混在ホール）
    - ``e_main``: hub_w↔hub_e の主通路。容量ヒント小（混雑しやすい想定）
    - 北バイパス ``e_n1a``/``e_n1b``（経由 ``n1``）と南バイパス ``e_s1a``/``e_s1b``（経由 ``s1``）
    主通路 ``e_main`` が急増/制限されると、両端 hub_w–hub_e 間の 2 本のバイパスが迂回路になる。
    """
    b = GraphBuilder()
    b.node("in", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("hub_w", kind=NodeKind.TRANSIT_ONLY, pos=(1.0, 0.0))
    b.node("hub_e", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.0))
    b.node("out", kind=NodeKind.GOAL, boundary=True, pos=(4.0, 0.0))
    b.node("n1", kind=NodeKind.TRANSIT_ONLY, pos=(2.0, 1.0))
    b.node("s1", kind=NodeKind.TRANSIT_ONLY, pos=(2.0, -1.0))

    b.edge("e_in", "in", "hub_w")
    b.edge("e_main", "hub_w", "hub_e", capacity_hint=10.0)
    b.edge("e_n1a", "hub_w", "n1")
    b.edge("e_n1b", "n1", "hub_e")
    b.edge("e_s1a", "hub_w", "s1")
    b.edge("e_s1b", "s1", "hub_e")
    b.edge("e_out", "hub_e", "out")
    return b.build()


PRESETS: dict[str, Any] = {
    "linear": linear,
    "y-junction": y_junction,
    "grid": grid,
    "ring": ring,
    "venue": venue,
    "expo": expo,
    "crossing": crossing,
}


def get_preset(name: str) -> BuiltGraph:
    if name not in PRESETS:
        raise KeyError(f"unknown graph preset: {name!r}. available: {sorted(PRESETS)}")
    return PRESETS[name]()


def resolve_graph_arg(arg: str | None, *, default: str = "venue") -> BuiltGraph:
    """``--graph`` 引数（プリセット名 or ファイルパス）から ``BuiltGraph`` を得る"""
    if arg is None:
        return get_preset(default)
    if arg in PRESETS:
        return get_preset(arg)
    path = Path(arg)
    if path.exists():
        return load(path)
    raise KeyError(
        f"{arg!r} はプリセット名でもファイルでもありません。available presets: {sorted(PRESETS)}"
    )
