"""グラフ構築ツール

簡潔な spec から ``flow_control.domain.Graph`` を組むビルダー、代表的な位相の
プリセット、YAML/JSON での load/save、描画用レイアウト座標の解決を提供する。
ドメインの ``Node`` には座標を持たせず、devtools 側で ``positions`` として保持する。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from itertools import combinations
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
    ) -> GraphBuilder:
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
    ) -> GraphBuilder:
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

    g: nx.Graph[str] = nx.Graph()
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


def crossing_oneway() -> BuiltGraph:
    """crossing と同位相でバイパス 2 本を一方通行循環にした変種

    北バイパス（``e_n1a``/``e_n1b``）は hub_w→hub_e（A_TO_B）、南バイパス
    （``e_s1a``/``e_s1b``）は hub_e→hub_w（B_TO_A）の LEGAL_FIXED。主通路とアクセスは
    双方向。方向属性提案（有向/双方向の提示）の確認用。
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
    b.edge(
        "e_n1a",
        "hub_w",
        "n1",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    b.edge(
        "e_n1b",
        "n1",
        "hub_e",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    b.edge(
        "e_s1a",
        "hub_w",
        "s1",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_B_TO_A,
        current_direction=CurrentDirection.B_TO_A,
    )
    b.edge(
        "e_s1b",
        "s1",
        "hub_e",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_B_TO_A,
        current_direction=CurrentDirection.B_TO_A,
    )
    b.edge("e_out", "hub_e", "out")
    return b.build()


def plaza_line() -> BuiltGraph:
    """両端が入退出点の直線＋中央に混在広場（Open モードの最小位相）

    素の直線（内部目的地なし）では Open モードの OD が構造的に 0 になるため、
    中央に混在ノード ``plaza`` を置く。
    """
    b = GraphBuilder()
    names_kinds = (
        ("n0", NodeKind.GOAL, True),
        ("n1", NodeKind.TRANSIT_ONLY, False),
        ("plaza", NodeKind.GOAL_TRANSIT_MIXED, False),
        ("n3", NodeKind.TRANSIT_ONLY, False),
        ("n4", NodeKind.GOAL, True),
    )
    for i, (name, kind, boundary) in enumerate(names_kinds):
        b.node(name, kind=kind, boundary=boundary, pos=(float(i), 0.0))
    order = [name for name, _, _ in names_kinds]
    for i in range(len(order) - 1):
        b.edge(f"e{i}", order[i], order[i + 1])
    return b.build()


def closed_ring(n: int = 6) -> BuiltGraph:
    """入退出点なしの環状（Closed モードの最小位相）

    対向する 2 つの広場（混在ノード）を持ち、放出側（ΔOcc<0）が生成源、
    蓄積側（ΔOcc>0）が吸収となる Closed の需要導出を通せる。
    """
    b = GraphBuilder()
    mixed = {0, n // 2}
    for i in range(n):
        angle = 2.0 * math.pi * i / n
        b.node(
            f"n{i}",
            kind=NodeKind.GOAL_TRANSIT_MIXED if i in mixed else NodeKind.TRANSIT_ONLY,
            boundary=False,
            pos=(math.cos(angle), math.sin(angle)),
        )
    for i in range(n):
        b.edge(f"e{i}", f"n{i}", f"n{(i + 1) % n}")
    return b.build()


def oneway_leaf() -> BuiltGraph:
    """葉ノードの唯一のエッジが法規制固定で内向きの構成異常位相

    出方向可達性が破れ Phase1 INFEASIBLE→フォールバックを再現する。
    """
    b = GraphBuilder()
    b.node("in", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("mid", kind=NodeKind.TRANSIT_ONLY, pos=(1.0, 0.0))
    b.node("dead", kind=NodeKind.GOAL, boundary=True, pos=(2.0, 0.0))
    b.edge("e1", "in", "mid")
    b.edge(
        "e2",
        "mid",
        "dead",
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    return b.build()


def deadend_lobby() -> BuiltGraph:
    """ゲート→ロビーの先に袋小路ホールと側室ホールが分かれる位相

    袋小路側は迂回路が存在しない（機能2 の通行制限提案の最小位相）。
    """
    b = GraphBuilder()
    b.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("lobby", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("deadend_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.8))
    b.node("side_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -0.8))
    b.edge("e_gate_lobby", "gate", "lobby", capacity_hint=120.0)
    b.edge("e_lobby_dead", "lobby", "deadend_hall")
    b.edge("e_lobby_side", "lobby", "side_hall")
    return b.build()


def festival() -> BuiltGraph:
    """フェス会場: 入場ゲートの一本道から二系統（フード・ステージ）へ分かれる導線

    ``e_gate_plaza`` は容量ヒント小（過需要になり得る狭い動線）。二系統は
    相互接続され、それぞれ出口へ抜けられる。
    """
    b = GraphBuilder()
    b.node("gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("food", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 1.0))
    b.node("main_stage", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -1.0))
    b.node("exit", kind=NodeKind.GOAL, boundary=True, pos=(4.5, 0.0))
    b.edge("e_gate_plaza", "gate", "plaza", capacity_hint=18.0)
    b.edge("e_food", "plaza", "food")
    b.edge("e_stage", "plaza", "main_stage")
    b.edge("e_food_stage", "food", "main_stage")
    b.edge("e_food_exit", "food", "exit")
    b.edge("e_stage_exit", "main_stage", "exit")
    return b.build()


def station_stairs() -> BuiltGraph:
    """駅コンコース: 改札からホームへ 2 本の階段が並行する位相

    片方の階段を低容量化（危険フラグ）すると代替階段への誘導が確認できる。
    """
    b = GraphBuilder()
    b.node("ticket_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("concourse", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("stairs_a", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, 1.0))
    b.node("stairs_b", kind=NodeKind.TRANSIT_ONLY, pos=(2.5, -1.0))
    b.node("platform", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(4.0, 0.0))
    b.edge("e_gate_concourse", "ticket_gate", "concourse")
    b.edge("e_stairs_a", "concourse", "stairs_a")
    b.edge("e_stairs_a_platform", "stairs_a", "platform")
    b.edge("e_stairs_b", "concourse", "stairs_b")
    b.edge("e_stairs_b_platform", "stairs_b", "platform")
    return b.build()


def transfer_station() -> BuiltGraph:
    """乗換駅: 2 つの改札・2 つのホームをコンコース間の並行 2 通路が結ぶ位相

    主連絡通路 ``e_passage`` は容量ヒント小。並行する ``e_underpass``（地下通路）を
    センサ未設置（unobserved）として使うと疎観測下の迂回が確認できる。
    """
    b = GraphBuilder()
    b.node("gate_w", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("conc_w", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("conc_e", kind=NodeKind.TRANSIT_ONLY, pos=(3.5, 0.0))
    b.node("gate_e", kind=NodeKind.GOAL, boundary=True, pos=(5.0, 0.0))
    b.node("plat1", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(1.5, 1.6))
    b.node("plat2", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.5, 1.6))

    b.edge("e_gate_w", "gate_w", "conc_w", capacity_hint=100.0)
    b.edge("e_gate_e", "gate_e", "conc_e", capacity_hint=100.0)
    b.edge("e_passage", "conc_w", "conc_e", capacity_hint=18.0)
    b.edge("e_underpass", "conc_w", "conc_e", capacity_hint=40.0)
    b.edge("e_cw_p1", "conc_w", "plat1")
    b.edge("e_ce_p2", "conc_e", "plat2")
    return b.build()


def school() -> BuiltGraph:
    """6 階建て校舎: 北・南階段と各階停止エレベーターを持つ導線。

    1 階の ``entrance`` が唯一の出入口で、6 階の ``floor6_goal`` が目的地である。
    各階のエレベーターホールはポイント観測、北・南の各階間階段はルート観測を
    想定する。各階の北・南踊り場はホールから分離した通過点で、ホール―踊り場の
    廊下とエレベーター区間は観測のない通過区間として、シナリオ側で
    ``unobserved_edges`` に指定する。
    """
    b = GraphBuilder()
    # 1〜6 階のホールはポイント観測。北・南の踊り場は、ホールとは別の
    # 通過専用ノードとして配置する。
    for floor in range(1, 7):
        b.node(
            f"elevator_hall_f{floor}",
            kind=NodeKind.GOAL_TRANSIT_MIXED,
            pos=(0.0, float(floor - 1)),
        )
        b.node(
            f"north_landing_f{floor}",
            kind=NodeKind.TRANSIT_ONLY,
            pos=(-2.0, float(floor - 1)),
        )
        b.node(
            f"south_landing_f{floor}",
            kind=NodeKind.TRANSIT_ONLY,
            pos=(2.0, float(floor - 1)),
        )
        b.edge(
            f"e_hall_north_landing_f{floor}",
            f"elevator_hall_f{floor}",
            f"north_landing_f{floor}",
        )
        b.edge(
            f"e_hall_south_landing_f{floor}",
            f"elevator_hall_f{floor}",
            f"south_landing_f{floor}",
        )

    b.node("entrance", kind=NodeKind.GOAL, boundary=True, pos=(0.0, -0.8))
    b.node("floor6_goal", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(0.0, 5.8))
    b.edge("e_entrance_hall_f1", "entrance", "elevator_hall_f1")
    b.edge("e_hall_f6_goal", "elevator_hall_f6", "floor6_goal")

    for floor in range(1, 6):
        # 各階停止エレベーターはホールのポイント観測のみで、区間自体は未観測。
        b.edge(
            f"e_vertical_elevator_f{floor}_{floor + 1}",
            f"elevator_hall_f{floor}",
            f"elevator_hall_f{floor + 1}",
            capacity_hint=36.0,
        )
        # 北・南階段は踊り場同士を結ぶ、各階間の個別ライン観測アーク。
        b.edge(
            f"e_north_stairs_f{floor}_{floor + 1}",
            f"north_landing_f{floor}",
            f"north_landing_f{floor + 1}",
            capacity_hint=22.0,
        )
        b.edge(
            f"e_south_stairs_f{floor}_{floor + 1}",
            f"south_landing_f{floor}",
            f"south_landing_f{floor + 1}",
            capacity_hint=22.0,
        )
    return b.build()


def stadium() -> BuiltGraph:
    """スタジアム: ボウルから東主出口・北南ゲートへ抜ける退場導線の位相

    ボウルは観客が滞留する混在ノード。東側は幅広の可変コンコース
    ``e_concourse``（BIDIRECTIONAL_PRIOR、現在は入場向き east_exit→bowl）と
    細い常設退場階段 ``e_egress_stair`` が並行する。北・南ゲートへの支線は
    スカラー観測（疎観測の現実性）。
    """
    b = GraphBuilder()
    b.node("north_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 2.0))
    b.node("south_gate", kind=NodeKind.GOAL, boundary=True, pos=(0.0, -2.0))
    b.node("west_plaza", kind=NodeKind.TRANSIT_ONLY, pos=(1.4, 0.0))
    b.node("north_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, 1.8))
    b.node("bowl", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 0.0))
    b.node("south_foyer", kind=NodeKind.TRANSIT_ONLY, pos=(2.8, -1.8))
    b.node("east_exit", kind=NodeKind.GOAL, boundary=True, pos=(6.0, 0.0))

    b.edge("e_north_gate", "north_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    b.edge("e_south_gate", "south_gate", "west_plaza", observation_type=ObservationType.SCALAR)
    b.edge("e_west_north", "west_plaza", "north_foyer", observation_type=ObservationType.SCALAR)
    b.edge("e_west_south", "west_plaza", "south_foyer", observation_type=ObservationType.SCALAR)
    b.edge("e_north_bowl", "north_foyer", "bowl", observation_type=ObservationType.SCALAR)
    b.edge("e_south_bowl", "south_foyer", "bowl", observation_type=ObservationType.SCALAR)
    b.edge("e_foyer_cross", "north_foyer", "south_foyer", observation_type=ObservationType.SCALAR)
    b.edge(
        "e_concourse",
        "bowl",
        "east_exit",
        capacity_hint=60.0,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.B_TO_A,
    )
    b.edge(
        "e_egress_stair",
        "bowl",
        "east_exit",
        capacity_hint=8.0,
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    return b.build()


def flex_corridor() -> BuiltGraph:
    """可変通路の最小位相: 場内ホールと退場先ロビーを 2 本の通路が結ぶ

    ``e_flex`` は BIDIRECTIONAL_PRIOR（現在は入場向き lobby→hall）、``e_service`` は
    hall→lobby の法規制固定・容量小。需要反転時の向き解除（RELEASE_ONEWAY）の確認用。
    """
    b = GraphBuilder()
    b.node("hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(0.0, 0.0))
    b.node("lobby", kind=NodeKind.GOAL, boundary=True, pos=(3.0, 0.0))
    b.edge(
        "e_flex",
        "lobby",
        "hall",
        capacity_hint=30.0,
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.A_TO_B,
    )
    b.edge(
        "e_service",
        "hall",
        "lobby",
        capacity_hint=10.0,
        direction_constraint=DirectionConstraint.LEGAL_FIXED_A_TO_B,
        current_direction=CurrentDirection.A_TO_B,
    )
    return b.build()


def museum() -> BuiltGraph:
    """美術館: エントランス→ホワイエから特別展（袋小路）と常設展へ分かれる位相

    特別展示室へのアクセスは迂回路が存在しない（機能2 の現実ケース用）。
    """
    b = GraphBuilder()
    b.node("entrance", kind=NodeKind.GOAL, boundary=True, pos=(0.0, 0.0))
    b.node("foyer", kind=NodeKind.TRANSIT_ONLY, pos=(1.5, 0.0))
    b.node("special_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, 1.0))
    b.node("main_hall", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(3.0, -1.0))
    b.node("cafe", kind=NodeKind.GOAL_TRANSIT_MIXED, pos=(4.5, -1.0))
    b.edge("e_entrance_foyer", "entrance", "foyer", capacity_hint=120.0)
    b.edge("e_foyer_special", "foyer", "special_hall")
    b.edge("e_foyer_main", "foyer", "main_hall")
    b.edge("e_main_cafe", "main_hall", "cafe")
    return b.build()


_DESIGN_LIMIT_NODE_SPECS: tuple[tuple[str, NodeKind, bool], ...] = (
    ("gate", NodeKind.GOAL, True),
    ("j_ne", NodeKind.TRANSIT_ONLY, False),
    ("hallA", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_e", NodeKind.TRANSIT_ONLY, False),
    ("hallB", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("exit", NodeKind.GOAL, True),
    ("hallC", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_s", NodeKind.TRANSIT_ONLY, False),
    ("hallD", NodeKind.GOAL_TRANSIT_MIXED, False),
    ("j_w", NodeKind.TRANSIT_ONLY, False),
)


def design_limit() -> BuiltGraph:
    """設計想定上限規模の密グラフ（10 ノード完全グラフ 45 本＋並行 5 本＝50 エッジ）

    性能ストレス計測用。隣接ホール-ジャンクション間に並行通路を足して
    エッジ数を要件上限の 50 に揃える。
    """
    b = GraphBuilder()
    n = len(_DESIGN_LIMIT_NODE_SPECS)
    for i, (name, kind, boundary) in enumerate(_DESIGN_LIMIT_NODE_SPECS):
        angle = 2.0 * math.pi * i / n
        b.node(
            name,
            kind=kind,
            boundary=boundary,
            pos=(3.0 * math.cos(angle), 3.0 * math.sin(angle)),
        )
    names = [name for (name, _, _) in _DESIGN_LIMIT_NODE_SPECS]
    for a, c in combinations(names, 2):
        b.edge(f"e_{a}_{c}", a, c)
    for a, c in (
        ("j_ne", "hallA"),
        ("hallA", "j_e"),
        ("j_e", "hallB"),
        ("hallC", "j_s"),
        ("j_s", "hallD"),
    ):
        b.edge(f"e_{a}_{c}_2", a, c)
    return b.build()


PRESETS: dict[str, Any] = {
    "linear": linear,
    "y-junction": y_junction,
    "grid": grid,
    "ring": ring,
    "venue": venue,
    "expo": expo,
    "crossing": crossing,
    "crossing-oneway": crossing_oneway,
    "plaza-line": plaza_line,
    "closed-ring": closed_ring,
    "oneway-leaf": oneway_leaf,
    "deadend-lobby": deadend_lobby,
    "festival": festival,
    "station-stairs": station_stairs,
    "transfer-station": transfer_station,
    "school": school,
    "stadium": stadium,
    "flex-corridor": flex_corridor,
    "museum": museum,
    "design-limit": design_limit,
}

# ファジングのランダムローテーション対象となる汎用位相。シナリオ固有プリセット
# （構成異常の oneway-leaf・上限規模の design-limit 等）と重い expo は除外する。
# `fuzz --graph <preset>` で明示指定すればどのプリセットも対象にできる
FUZZ_ROTATION_PRESETS: tuple[str, ...] = (
    "crossing",
    "grid",
    "linear",
    "ring",
    "venue",
    "y-junction",
)


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
