from dataclasses import dataclass, replace
from datetime import datetime

from ..domain.graph import EdgeID, Graph, NodeID
from ..domain.history import HistoryDigest
from ..domain.observations import Observations
from ..domain.references import Reference
from .config import ResolvedConfig
from .diagnostics import DangerEvidence, DetectionWarning, TriggerEvidence
from .state import DetectionState, QueuedTriggerKind
from .triggers import (
    Event,
    FiredTrigger,
    VerdictHint,
    all_targets_in_warmup,
    apply_danger_flag_down,
    apply_scheduled_events,
    apply_warmup_events,
    detect_manual_triggers,
    detect_metric_triggers,
    evaluate_cooldown,
    has_danger_event,
    update_retrigger_counts,
)


@dataclass(frozen=True)
class DetectionResult:
    verdict_hint: VerdictHint
    triggered_edges: tuple[EdgeID, ...]
    triggered_nodes: tuple[NodeID, ...]
    effective_snapshot: Observations
    # 発火確定時の遷移候補
    new_state: DetectionState
    # 発火不成立（skipped_time）時の遷移候補：new_state から
    # 発火副作用（cooldown_until 更新・キュー消化・再発火カウント加算）を除いたもの
    abort_state: DetectionState
    evidences: tuple[TriggerEvidence, ...] = ()
    # 縮退・代替の記録（RequestHandler が Diagnostics.warnings へ集約）
    warnings: tuple[DetectionWarning, ...] = ()


def detect(
    graph: Graph,
    observations: Observations,
    history_digest: HistoryDigest,
    previous_state: DetectionState,
    events: tuple[Event, ...],
    config: ResolvedConfig,
    server_time: datetime,
    references: Reference | None = None,
) -> DetectionResult:
    # イベント適用: ENABLE/ADD_* で対象別ウォームアップを設定
    state = apply_warmup_events(previous_state, events, server_time, config)
    # イベント適用: SCHEDULED_* でクールタイムをリセット（キューは保持）
    state = apply_scheduled_events(state, events)
    # イベント適用: DANGER_FLAG_DOWN で当該アークの既存再発火カウントをリセット
    state = apply_danger_flag_down(state, events)

    # 全対象がウォームアップ中かつ危険フラグなしなら検知をスキップ
    if all_targets_in_warmup(state, graph, server_time) and not has_danger_event(
        events
    ):
        # ウォームアップスキップは発火なし → abort_state は new_state と等価
        return DetectionResult(
            verdict_hint=VerdictHint.SKIPPED_WARMUP,
            triggered_edges=(),
            triggered_nodes=(),
            effective_snapshot=observations,
            new_state=state,
            abort_state=state,
        )

    metric_result = detect_metric_triggers(
        graph=graph,
        observations=observations,
        history_digest=history_digest,
        previous_state=state,
        server_time=server_time,
        config=config,
        references=references,
    )

    manual_result = detect_manual_triggers(events=events)
    danger_triggers = tuple(
        FiredTrigger(
            kind=QueuedTriggerKind.DANGER,
            fired_at=server_time,
            origin_edge_id=edge_id,
            snapshot_ref=observations.snapshot_ref,
        )
        for edge_id in manual_result.triggered_edges
    ) + tuple(
        FiredTrigger(
            kind=QueuedTriggerKind.DANGER,
            fired_at=server_time,
            origin_node_id=node_id,
            snapshot_ref=observations.snapshot_ref,
        )
        for node_id in manual_result.triggered_nodes
    )
    danger_evidences: tuple[TriggerEvidence, ...] = tuple(
        DangerEvidence(occurred_at=server_time, edge_id=edge_id)
        for edge_id in manual_result.triggered_edges
    ) + tuple(
        DangerEvidence(occurred_at=server_time, node_id=node_id)
        for node_id in manual_result.triggered_nodes
    )

    # 鮮度ガード用: 現時点で警戒条件を満たすエッジ集合
    watched_edges = frozenset(
        watch.edge_id
        for watch in metric_result.new_state.arc_watch_states
        if watch.percentile_breached or watch.delta_breached
    )

    decision = evaluate_cooldown(
        previous_state=metric_result.new_state,
        fired_triggers=danger_triggers + metric_result.fired_triggers,
        server_time=server_time,
        config=config,
        watched_edges=watched_edges,
    )

    # 再発火カウントの更新は実際の発火（verdict）でゲート
    # - TRIGGERED: 実発火した通常トリガー起点のみ加算（危険フラグ＝規則4で除外）
    # - QUEUED:    変更なし（キュー追加は発火ではない）
    # - SKIPPED_COOLDOWN / NO_TRIGGER: 発火なし → 沈静化カウント進行（fired=()）
    if decision.verdict == VerdictHint.QUEUED:
        retrigger_counts = metric_result.new_state.arc_retrigger_counts
    else:
        danger_edges = set(manual_result.triggered_edges)
        if decision.verdict == VerdictHint.TRIGGERED:
            fired_normal_edges = tuple(
                e for e in decision.triggered_edges if e not in danger_edges
            )
        else:
            fired_normal_edges = ()
        retrigger_counts = update_retrigger_counts(
            previous_counts=metric_result.new_state.arc_retrigger_counts,
            graph=graph,
            normal_trigger_edges=fired_normal_edges,
            watch_states=metric_result.new_state.arc_watch_states,
            server_time=server_time,
            config=config,
        )

    new_state = replace(decision.new_state, arc_retrigger_counts=retrigger_counts)

    # abort_state: 発火副作用を含まない遷移候補
    # 発火なしの verdict では new_state と等価。TRIGGERED のみ発火副作用（cooldown 更新・
    # キュー消化・再発火カウント加算）を除く。再発火カウントは加算せず沈静化進行のみ
    if decision.verdict == VerdictHint.TRIGGERED:
        abort_retrigger_counts = update_retrigger_counts(
            previous_counts=metric_result.new_state.arc_retrigger_counts,
            graph=graph,
            normal_trigger_edges=(),
            watch_states=metric_result.new_state.arc_watch_states,
            server_time=server_time,
            config=config,
        )
        abort_base = (
            decision.abort_state
            if decision.abort_state is not None
            else decision.new_state
        )
        abort_state = replace(abort_base, arc_retrigger_counts=abort_retrigger_counts)
    else:
        abort_state = new_state

    # 検出した通常トリガー・危険フラグ・キュー発火条件のEvidenceを統合
    evidences = metric_result.evidences + danger_evidences + decision.evidences

    # 発火を起こすトリガーは常に当該リクエストのもの
    # その時点のスナップショットが「キュー最後の発火時点」に一致
    # 各キューエントリのsnapshot_ref には参照識別子を保持，過去スナップショットの参照に使用する
    return DetectionResult(
        verdict_hint=decision.verdict,
        triggered_edges=decision.triggered_edges,
        triggered_nodes=decision.triggered_nodes,
        effective_snapshot=observations,
        new_state=new_state,
        abort_state=abort_state,
        evidences=evidences,
        warnings=metric_result.warnings,
    )
