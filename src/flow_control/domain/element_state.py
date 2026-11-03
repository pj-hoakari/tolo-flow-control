from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .graph import Edge, EdgeID, Graph
from .history import ArcHistoryStat, HistoryDigest
from .observations import ConfidenceFlag, Observations

SHORT_HISTORY_HOURS = 4.0
MIN_SERIES_POINTS = 2
DEFAULT_SURGE_WINDOW_MINUTE = 30.0
DEFAULT_STALE_AFTER_RESOLUTIONS = 2.0
DEFAULT_STALE_FLOOR_S = 60.0

Series = tuple[tuple[datetime, float], ...]


class ObservationState(str, Enum):
    UNOBSERVED = "UNOBSERVED"
    INVALID = "INVALID"
    HOLD = "HOLD"
    STALE = "STALE"
    OK = "OK"


class HistoryTier(str, Enum):
    NONE = "NONE"
    WINDOW_ONLY = "WINDOW_ONLY"
    SHORT = "SHORT"
    ESTABLISHED = "ESTABLISHED"


class BaselineSource(str, Enum):
    HISTORY = "HISTORY"
    WINDOW = "WINDOW"
    NONE = "NONE"


class Judgement(str, Enum):
    SURGE = "SURGE"
    HIGH_STAGNATION = "HIGH_STAGNATION"
    COMBINED = "COMBINED"
    PUNCTURE = "PUNCTURE"


@dataclass(frozen=True)
class StagnationBasis:
    current: float
    recent: float
    baseline: float
    baseline_source: BaselineSource
    p90: float | None


@dataclass(frozen=True)
class ElementState:
    edge_id: EdgeID
    observation: ObservationState
    history: HistoryTier
    line: Series
    stagnation: StagnationBasis | None

    @property
    def line_points(self) -> int:
        return len(self.line)

    @property
    def baseline_source(self) -> BaselineSource:
        if self.stagnation is None:
            return BaselineSource.NONE
        return self.stagnation.baseline_source

    @property
    def nominal(self) -> bool:
        return (
            self.observation is ObservationState.OK
            and self.history is HistoryTier.ESTABLISHED
            and self.line_points >= MIN_SERIES_POINTS
        )

    @property
    def judgeable(self) -> bool:
        return self.observation is ObservationState.OK

    def surge_line(self) -> Series | None:
        if not self.judgeable or self.line_points < MIN_SERIES_POINTS:
            return None
        return self.line

    def stagnation_basis(self) -> StagnationBasis | None:
        return self.stagnation if self.judgeable else None


ElementStates = Mapping[EdgeID, ElementState]


def assess_elements(
    graph: Graph,
    observations: Observations,
    history: HistoryDigest,
    server_time: datetime,
    *,
    surge_window_minute: float = DEFAULT_SURGE_WINDOW_MINUTE,
    stale_after_resolutions: float = DEFAULT_STALE_AFTER_RESOLUTIONS,
    stale_floor_s: float = DEFAULT_STALE_FLOOR_S,
) -> dict[EdgeID, ElementState]:
    lag_s = (server_time - observations.observed_at).total_seconds()
    states: dict[EdgeID, ElementState] = {}
    for edge in graph.enabled_edges():
        window = history.window_series_of(edge.edge_id)
        stat = history.stat_of(edge.edge_id)
        stagnation_window = (
            tuple(v for _, v in window.stagnation_samples) if window is not None else ()
        )
        tier = _history_tier(stat, stagnation_window)
        stale_after_s = max(stale_after_resolutions * edge.time_resolution_s, stale_floor_s)
        states[edge.edge_id] = ElementState(
            edge_id=edge.edge_id,
            observation=_observation_state(edge.edge_id, observations, lag_s >= stale_after_s),
            history=tier,
            line=_line(
                edge,
                observations,
                window.flow_samples if window is not None else (),
                server_time,
                surge_window_minute,
            ),
            stagnation=_stagnation_basis(edge.edge_id, observations, stat, stagnation_window, tier),
        )
    return states


def _observation_state(
    edge_id: EdgeID, observations: Observations, stale: bool
) -> ObservationState:
    flags = {f.confidence_flag for f in observations.arc_flows if f.edge_id == edge_id}
    flags |= {s.confidence_flag for s in observations.arc_stagnations if s.edge_id == edge_id}
    flags |= {s.confidence_flag for s in observations.arc_scalar_flows if s.edge_id == edge_id}
    if not flags:
        return ObservationState.UNOBSERVED
    if ConfidenceFlag.INVALID in flags:
        return ObservationState.INVALID
    if stale:
        return ObservationState.STALE
    if ConfidenceFlag.HOLD in flags:
        return ObservationState.HOLD
    return ObservationState.OK


def _history_tier(stat: ArcHistoryStat | None, stagnation_window: tuple[float, ...]) -> HistoryTier:
    if stat is None:
        if len(stagnation_window) >= MIN_SERIES_POINTS:
            return HistoryTier.WINDOW_ONLY
        return HistoryTier.NONE
    span = stat.available_span_hours
    if stat.p90_stagnation is None or (span is not None and span < SHORT_HISTORY_HOURS):
        return HistoryTier.SHORT
    return HistoryTier.ESTABLISHED


def _line(
    edge: Edge,
    observations: Observations,
    flow_samples: Series,
    server_time: datetime,
    surge_window_minute: float,
) -> Series:
    start = server_time - timedelta(minutes=surge_window_minute + edge.time_resolution_s / 60.0)
    line = [(t, v) for (t, v) in flow_samples if t >= start]
    current = [
        f.flow_rate
        for f in observations.arc_flows
        if f.edge_id == edge.edge_id and f.confidence_flag is not ConfidenceFlag.INVALID
    ]
    if current and observations.observed_at >= start:
        line.append((observations.observed_at, sum(current)))
    return tuple(line)


def _stagnation_basis(
    edge_id: EdgeID,
    observations: Observations,
    stat: ArcHistoryStat | None,
    stagnation_window: tuple[float, ...],
    tier: HistoryTier,
) -> StagnationBasis | None:
    observed = observations.stagnation_of(edge_id)
    if observed is None or tier is HistoryTier.NONE:
        return None
    window_mean = statistics.mean(stagnation_window) if stagnation_window else None
    history_baseline = None if stat is None else stat.baseline_stagnation
    if history_baseline is not None:
        baseline, source = history_baseline, BaselineSource.HISTORY
    elif window_mean is not None:
        baseline, source = window_mean, BaselineSource.WINDOW
    else:
        return None
    return StagnationBasis(
        current=observed.stagnation,
        recent=baseline if window_mean is None else window_mean,
        baseline=baseline,
        baseline_source=source,
        p90=stat.p90_stagnation if stat is not None and tier is HistoryTier.ESTABLISHED else None,
    )
