# 大域フローコントロールコンテキスト 入出力整理

ドメイン定義: flow_control_domain.md
デプロイ単位: flow_control_spec.md
ステートレスのため、RPC は Optimize の1つだけである。ドメインイベントは応答の中で表現し、永続化は観測が行う

## ドメインイベント↔入出力 対応

| ドメインイベント | 応答での表現 |
|---|---|
| SurgeTriggered／HighStagnationTriggered／PunctureTriggered | `diagnostics.trigger_evidences`（`source` が種類を示す） |
| ScheduleTriggered | 要求側の `events`（予定された流入・属性変更）が契機。応答で一対一に対応するフィールドはない |
| DangerFlagRaised／DangerFlagLowered | 要求側の `events`（`EVENT_KIND_DANGER_FLAG_UP`／`DOWN`）が契機。発火は `diagnostics.trigger_evidences`（`TRIGGER_EVIDENCE_SOURCE_DANGER`） |
| WatchStateEntered | `updated_detection_state.arc_watch_states` |
| TriggerEnqueued | `updated_detection_state.trigger_queue` への追加（`VERDICT_QUEUED`） |
| QueueMergedFired／QueueDiscarded | `updated_detection_state.trigger_queue` からの除去。統合の根拠は `diagnostics.trigger_evidences`（`QUEUE_SCORE`／`QUEUE_DIVERSITY`） |
| Optimized | `VERDICT_OPTIMIZED` |
| WeightedRoutesComputed | `optimization_result.route_importance` |
| DirectionProposed | `optimization_result.direction_proposal` |
| BoundaryControlProposed | `optimization_result.boundary_control` |
| RestrictionProposed | `optimization_result.restriction_proposal` |
| OptimizationSkipped | `VERDICT_SKIPPED_*`。エラー（`VERDICT_ERROR_*`）もイベントとしてはスキップに含める |
| FeedbackEmitted | `feedback_values` |

迂回経路の提案（`optimization_result.detour_paths`）に対応するドメインイベントはない

## スタッフ→システム接点（現場誘導）

DangerFlagToggledByOperator／ScheduleEventRegistered／CongestionManuallyReported は観測の ManualInterventionService が受け付け、`OptimizeRequest.events` に変換して同梱される。混雑の手動報告に対応する `events` の種類は未確定であり実装フェーズで確定する（観測コンテキスト）

## 他コンテキストとの接点

| 接点 | 対応 |
|---|---|
| 入力（グラフ・スコア・検知状態） | Flow 独自の型（`Graph`・`Observations`）と DetectionState。観測が共有カーネルの型（shared_kernel_context.md）から変換して受け渡す |
| 参照値（コールドスタート） | `OptimizeRequest.references`（生成は参照値集約。観測が参照値集約の型から変換する。参照値集約コンテキスト） |
| 提案の配信 | 観測が Operation の型へ変換し、Operation.RequestProposalDelivery へ（スタッフ間コミュニケーションコンテキスト） |
| フィードバック値の蓄積 | 観測が Operation の型へ変換し、Operation.RecordFeedbackValues へ |
