from dataclasses import dataclass, field
from datetime import datetime

from .enums import FlowDirection
from .graph import EdgeID


@dataclass(frozen=True)
class ArcHistoryStat:
    edge_id: EdgeID
    p90_stagnation: float | None = None
    baseline_stagnation: float | None = None
    flow_sensitivity_eta: float | None = None
    # 履歴の利用可能スパン（時間）。縮退モード要否判定に使用（None = 未提供）
    available_span_hours: float | None = None


@dataclass(frozen=True)
class ArcWindowSeries:
    edge_id: EdgeID
    # 直近ウィンドウの流量系列（エッジ合算・正準単位。急増判定用）
    flow_samples: tuple[tuple[datetime, float], ...] = field(default_factory=tuple)
    # 直近ウィンドウの停滞量系列（高停滞 (b).2 の直近移動平均用）
    stagnation_samples: tuple[tuple[datetime, float], ...] = field(
        default_factory=tuple
    )
    # 方向別ライン通過系列（排出実績 μ̂_e の算出用。ラインなしは None）
    directional_flow_samples: (
        tuple[tuple[FlowDirection, tuple[tuple[datetime, float], ...]], ...] | None
    ) = None


@dataclass(frozen=True)
class HistoryDigest:
    arc_stats: tuple[ArcHistoryStat, ...] = field(default_factory=tuple)
    window_series: tuple[ArcWindowSeries, ...] = field(default_factory=tuple)
    completeness: float = 0.0

    def stat_of(self, edge_id: EdgeID) -> ArcHistoryStat | None:
        for stat in self.arc_stats:
            if stat.edge_id == edge_id:
                return stat
        return None

    def window_series_of(self, edge_id: EdgeID) -> ArcWindowSeries | None:
        for series in self.window_series:
            if series.edge_id == edge_id:
                return series
        return None
