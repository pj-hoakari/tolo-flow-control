"""パイプライン実行ハーネス（RequestHandler 相当の開発用オーケストレーション）

Detection → Forecasting → DetourRouting → Optimization を直列に呼び出し、各モジュールの
中間結果と経過時間を保持する。これは本番 RequestHandler の実装ではなく、各モジュール結果を
観察・検証するための開発専用ハーネスである（未実装の RequestHandler / FeedbackExtractor の
本体には踏み込まない）。

挙動は設計の RequestHandler を模倣する:
- Open/Closed モードを ``graph.boundary_nodes()`` から判定し各 Step に伝播
- Detection の verdict に応じた検知状態の二相コミット（TRIGGERED は new_state、
  それ以外は abort_state を採用）
- 下流へは ``detection.effective_snapshot`` を観測入力として渡す
- verdict が TRIGGERED 以外なら下流をスキップ（``force=True`` で強制実行）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from flow_control.detection import DetectionResult, VerdictHint, detect
from flow_control.detection.state import DetectionState
from flow_control.detour_routing import DetourResult, route_detour
from flow_control.domain import Mode
from flow_control.forecasting import ForecastResult, forecast
from flow_control.optimization import OptimizeResult, optimize

from .scenario_base import Scenario


@dataclass(frozen=True)
class PipelineRun:
    """1 回のパイプライン実行で得た全中間結果"""

    scenario_name: str
    mode: Mode
    detection: DetectionResult
    committed_state: DetectionState
    downstream_ran: bool
    forecast: ForecastResult | None = None
    detour: DetourResult | None = None
    optimization: OptimizeResult | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def decide_mode(scenario: Scenario) -> Mode:
    return Mode.OPEN if scenario.graph.boundary_nodes() else Mode.CLOSED


def run_pipeline(
    scenario: Scenario,
    *,
    force: bool = False,
    time_limit: float | None = None,
) -> PipelineRun:
    """シナリオ 1 件を直列実行し ``PipelineRun`` を返す"""
    graph = scenario.graph
    mode = decide_mode(scenario)
    cfg = scenario.configs
    timings: dict[str, float] = {}
    notes: list[str] = []

    # --- Detection ---
    t0 = time.perf_counter()
    detection = detect(
        graph=graph,
        observations=scenario.observations,
        history_digest=scenario.history_digest,
        previous_state=scenario.previous_state,
        events=scenario.events,
        config=cfg.detection,
        server_time=scenario.server_time,
        references=scenario.references,
    )
    timings["detection"] = (time.perf_counter() - t0) * 1000.0

    triggered = detection.verdict_hint == VerdictHint.TRIGGERED
    committed_state = detection.new_state if triggered else detection.abort_state

    run_downstream = triggered or force
    if not triggered:
        # notes はサマリ画像にも描画するため ASCII で記す（matplotlib 既定フォント対策）
        notes.append(
            f"verdict={detection.verdict_hint.value}: "
            + ("downstream forced" if force else "downstream skipped")
        )
    if not run_downstream:
        return PipelineRun(
            scenario_name=scenario.name,
            mode=mode,
            detection=detection,
            committed_state=committed_state,
            downstream_ran=False,
            timings_ms=timings,
            notes=notes,
        )

    effective_obs = detection.effective_snapshot
    triggered_edges = detection.triggered_edges

    # --- Forecasting ---
    t0 = time.perf_counter()
    fc = forecast(
        graph=graph,
        observations=effective_obs,
        history_digest=scenario.history_digest,
        references=scenario.references,
        triggered_edges=triggered_edges,
        config=cfg.forecasting,
        mode=mode,
    )
    timings["forecasting"] = (time.perf_counter() - t0) * 1000.0

    # --- DetourRouting ---
    t0 = time.perf_counter()
    detour = route_detour(
        graph=graph,
        triggered_edges=triggered_edges,
        forecast_result=fc,
        config=cfg.detour,
        mode=mode,
    )
    timings["detour"] = (time.perf_counter() - t0) * 1000.0

    # --- Optimization ---
    limit = time_limit
    if limit is None:
        limit = (
            cfg.optimization.lightweight_opt_budget_sec
            if cfg.optimization.optimization_mode.value == "LIGHTWEIGHT"
            else cfg.optimization.milp_time_limit_sec
        )
    t0 = time.perf_counter()
    opt = optimize(
        graph=graph,
        observations=effective_obs,
        forecast_result=fc,
        detour_result=detour,
        history_digest=scenario.history_digest,
        previous_result=scenario.previous_opt_result,
        config=cfg.optimization,
        seed=cfg.optimization.solver_seed,
        time_limit=limit,
        mode=mode,
        triggered_edges=triggered_edges,
        triggered_nodes=detection.triggered_nodes,
    )
    timings["optimization"] = (time.perf_counter() - t0) * 1000.0

    return PipelineRun(
        scenario_name=scenario.name,
        mode=mode,
        detection=detection,
        committed_state=committed_state,
        downstream_ran=True,
        forecast=fc,
        detour=detour,
        optimization=opt,
        timings_ms=timings,
        notes=notes,
    )
