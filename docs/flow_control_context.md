# 大域フローコントロールコンテキスト 入出力整理

ドメイン定義: flow_control_domain.md
デプロイ単位: flow_control_spec.md
ステートレスのため RPC は Optimize の 1 つ。ドメインイベントは応答の中で表現され、永続化は観測が行う

## ドメインイベント↔入出力 対応

| ドメインイベント | 応答での表現 |
|---|---|
| SurgeTriggered／HighStagnationTriggered／PunctureTriggered／ScheduleTriggered | `fired_triggers`（TriggerKind） |
| DangerFlagRaised／DangerFlagLowered | `fired_triggers`（TRIGGER_KIND_DANGER_FLAG。要求側の ManualIntervention が契機） |
| WatchStateEntered | `detection_state.watch` への追加 |
| TriggerEnqueued | `detection_state.trigger_queue` への追加（verdict=QUEUED） |
| QueueMergedFired／QueueDiscarded | `fired_triggers.merged`／キューからの除去 |
| Optimized | verdict=OPTIMIZED |
| WeightedRoutesComputed | `proposals.weighted_routes` |
| DirectionProposed | `proposals.directions` |
| BoundaryControlProposed | `proposals.boundary_controls` |
| RestrictionProposed | `proposals.restrictions` |
| OptimizationSkipped | verdict=SKIPPED（エラーはイベント上スキップに内包。verdict=ERROR） |
| FeedbackEmitted | `feedback_values` |

## スタッフ→システム接点（現場誘導）

DangerFlagToggledByOperator／ScheduleEventRegistered／CongestionManuallyReported は観測の ManualInterventionService が受け、`OptimizeRequest.interventions` に同梱される（観測コンテキスト）

## 他コンテキストとの接点

| 接点 | 対応 |
|---|---|
| 入力（グラフ・スコア・検知状態） | 共有カーネル型＋DetectionState（観測が受け渡し。shared_kernel_context.md） |
| 参照値（コールドスタート） | `OptimizeRequest.reference_values`（生成は参照値集約。参照値集約コンテキスト） |
| フィードバック値の蓄積 | 観測経由で Operation.RecordFeedbackValues へ |
