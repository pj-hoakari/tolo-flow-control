from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..domain.graph import EdgeID, NodeID


class QueuedTriggerKind(str, Enum):
    SURGE = "SURGE"  # 急増
    HIGH_STAGNATION = "HIGH_STAGNATION"  # 高停滞
    PUNCTURE = "PUNCTURE"  # パンク（前処理 P 由来）
    DANGER = "DANGER"  # 危険フラグ


@dataclass(frozen=True)
class QueuedTrigger:
    kind: QueuedTriggerKind
    first_fired_at: datetime
    last_fired_at: datetime
    accumulated_score: float = 0.0
    origin_edge_id: EdgeID | None = None
    origin_node_id: NodeID | None = None
    snapshot_ref: str | None = None


@dataclass(frozen=True)
class ArcWatchState:
    edge_id: EdgeID
    # 停滞警戒系統（(a)）
    percentile_breached: bool = False  # (a).1 p90 超過の成立有無
    delta_breached: bool = False  # (a).2 移動平均差分の相対閾値 β 超過の成立有無
    stagnation_watch_since: datetime | None = None  # 停滞警戒（両条件成立）の開始時刻
    # 需要警戒系統（(b)）
    surge_breached: bool = False  # (b).1 急増（傾き閾値超）の成立有無
    demand_excess_breached: bool = False  # (b).2 需要超過 ρ̂ > theta_demand の成立有無
    demand_watch_since: datetime | None = None  # 需要警戒の開始時刻


@dataclass(frozen=True)
class WarmupState:
    target_key: str  # "edge:<id>" / "node:<id>"
    until: datetime


@dataclass(frozen=True)
class RetriggerEntry:
    edge_id: EdgeID
    count: int = 0  # 同一アーク起点の連続発火カウント
    quiet_cycles: int = 0  # 沈静化が続いたサイクル数
    last_fired_at: datetime | None = None


@dataclass(frozen=True)
class ArcDemandDigestEntry:
    edge_id: EdgeID
    demand: float  # 前回リクエストの予測到着需要 λ̂_e


@dataclass(frozen=True)
class DetectionState:
    cooldown_until: datetime | None = None
    trigger_queue: tuple[QueuedTrigger, ...] = ()
    arc_watch_states: tuple[ArcWatchState, ...] = ()
    # 前回リクエストの予測到着需要 λ̂_e（需要超過判定 (b).2 用）。
    # Forecasting 実行時に finalize で更新。None = 未提供
    arc_demand_digest: tuple[ArcDemandDigestEntry, ...] | None = None
    warmup_states: tuple[WarmupState, ...] = ()
    arc_retrigger_counts: tuple[RetriggerEntry, ...] = ()
    consecutive_skip_count: int = 0

    def watch_state_of(self, edge_id: EdgeID) -> ArcWatchState | None:
        for watch in self.arc_watch_states:
            if watch.edge_id == edge_id:
                return watch
        return None

    def demand_digest_of(self, edge_id: EdgeID) -> float | None:
        if self.arc_demand_digest is None:
            return None
        for entry in self.arc_demand_digest:
            if entry.edge_id == edge_id:
                return entry.demand
        return None

    def retrigger_entry_of(self, edge_id: EdgeID) -> RetriggerEntry | None:
        for entry in self.arc_retrigger_counts:
            if entry.edge_id == edge_id:
                return entry
        return None

    def is_in_cooldown(self, server_time: datetime) -> bool:
        return self.cooldown_until is not None and server_time < self.cooldown_until

    def warmup_until_of(self, target_key: str) -> datetime | None:
        for warmup in self.warmup_states:
            if warmup.target_key == target_key:
                return warmup.until
        return None

    def is_in_warmup(self, target_key: str, server_time: datetime) -> bool:
        until = self.warmup_until_of(target_key)
        return until is not None and server_time < until
