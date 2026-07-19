from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .enums import FlowDirection
from .graph import EdgeID, NodeID


class ConfidenceFlag(str, Enum):
    OK = "OK"
    HOLD = "HOLD"  # 直近有効値HOLD状態 低信頼度
    INVALID = "INVALID"  # 観測不能


class StagnationDerivation(str, Enum):
    # 停滞プロキシの導出方法
    BASIC = "BASIC"  # 視野内検知人数そのまま
    REFINED = "REFINED"  # 同一観測点のライン流量を差し引いた精緻化値


@dataclass(frozen=True)
class ArcFlow:
    edge_id: EdgeID
    direction: FlowDirection
    flow_rate: float
    confidence_flag: ConfidenceFlag = ConfidenceFlag.OK


@dataclass(frozen=True)
class ArcStagnation:
    edge_id: EdgeID
    stagnation: float
    # BASIC=検知人数そのまま／REFINED=同一観測点のライン流量差し引き
    derivation: StagnationDerivation = StagnationDerivation.BASIC
    # 同一観測点にライン通過があるか（η 回帰・精緻化のゲイン共有可否）
    same_sensor_flow: bool = False
    confidence_flag: ConfidenceFlag = ConfidenceFlag.OK


@dataclass(frozen=True)
class ArcScalarFlow:
    edge_id: EdgeID
    observed_count: float
    confidence_flag: ConfidenceFlag = ConfidenceFlag.OK


@dataclass(frozen=True)
class NodeOccupancy:
    node_id: NodeID
    occupancy: float  # 占有プロキシ N_v（リトル型復元は同一観測点由来の到着率とのみ組合せ可）
    occupancy_delta: float = 0.0  # 観測ウィンドウ内の占有量変化 ΔOcc（蓄積フェーズの滞在識別）
    # 入口ライン到着率が同一観測点由来か（リトル型復元 (c) の適用条件）
    same_sensor_arrival: bool = False
    confidence_flag: ConfidenceFlag = ConfidenceFlag.OK


@dataclass(frozen=True)
class TurningObservation:
    # 任意。方向転換率（滞在割合を含む）。内部導出が不定な合流＋分岐ノードにのみ与える補助入力
    node_id: NodeID
    from_edge_id: EdgeID
    # None = 当該ノードで終端（滞在）した割合。同一 from_edge_id で Σratio = 1.0
    to_edge_id: EdgeID | None = None
    ratio: float = 0.0
    confidence_flag: ConfidenceFlag = ConfidenceFlag.OK


@dataclass(frozen=True)
class Observations:
    observed_at: datetime
    snapshot_ref: str | None = None
    arc_flows: tuple[ArcFlow, ...] = field(default_factory=tuple)
    arc_stagnations: tuple[ArcStagnation, ...] = field(default_factory=tuple)
    arc_scalar_flows: tuple[ArcScalarFlow, ...] = field(default_factory=tuple)
    node_occupancies: tuple[NodeOccupancy, ...] = field(default_factory=tuple)
    # ノード別方向転換率（需要入力、Forecasting Step B）
    node_turning: tuple[TurningObservation, ...] = field(default_factory=tuple)

    def stagnation_of(self, edge_id: EdgeID) -> ArcStagnation | None:
        for arc_stagnation in self.arc_stagnations:
            if arc_stagnation.edge_id == edge_id:
                return arc_stagnation
        return None

    def scalar_flow_of(self, edge_id: EdgeID) -> ArcScalarFlow | None:
        for arc_scalar_flow in self.arc_scalar_flows:
            if arc_scalar_flow.edge_id == edge_id:
                return arc_scalar_flow
        return None
