# 大域フローコントロールコンテキスト

## 責務

- 共有カーネルのグラフ・観測スコアを入力に危険箇所リスク低減の提案を返す
- 提案の宛先はスタッフのみ（ゲストへの伝達はスタッフの現場誘導・手動のメッセージ配信）
- ステートレス（状態永続化は観測）
- 近似最適化
- 目的の優先順：1. 最大停滞量の近似最小化／2. 優劣つかない範囲でのスループット最大化

## ドメインモデル

| 語 | 英語 | 内容 |
|---|---|---|
| 危険度 | Risk Level | 危険箇所のリスクの大きさ（正規化停滞量）<br>本コンテキスト専用 |
| 需要予測 | Demand Forecast | 点需要とルート需要を分離推定 |
| 迂回ルート | Detour Route | 急増ルートの負担を逃がす代替経路 |
| 求解モード | Solver Mode | 基本（軽量・既定）／厳密<br>安全は両モード非緩和 |
| 参照値 | Reference Value | 他テナント由来のコールドスタート典型値<br>生成は参照値集約 |
| トリガー | Trigger | 急増／高停滞／パンク／危険フラグ／スケジュール |
| 検知状態 | Detection State | クールタイム・ウォームアップ・キュー・警戒<br>外部が永続化 |
| 重要度付きルート | Weighted Route | 0–1の重要度提案 |
| 方向属性提案 | Direction Proposal | 一方／両通行（化・解除・反転・据置） |
| 境界制御提案 | Boundary Control Proposal | 入退出の一時停止・再開 |
| 通行制限提案 | Restriction Proposal | 閉鎖・流量上限・解除 |
| フィードバック値 | Feedback Value | 効果測定と他テナント初期値参考（匿名化前提） |
| 判定結果 | Verdict | 最適化／キュー／スキップ／エラー（エラーはイベント上スキップ内包） |

## ドメインイベント

| イベント | 英語 |
|---|---|
| 急増トリガー発火した | SurgeTriggered |
| 高停滞トリガー発火した | HighStagnationTriggered |
| パンクトリガー発火した | PunctureTriggered |
| スケジュールトリガー発火した | ScheduleTriggered |
| 危険フラグ立てられた／立ち下げられた | DangerFlagRaised/Lowered |
| 警戒状態に入った | WatchStateEntered |
| トリガーキューに蓄積された | TriggerEnqueued |
| 統合発火した／キュー破棄された | QueueMergedFired/QueueDiscarded |
| 最適化実行された | Optimized |
| 重要度付きルート算出された | WeightedRoutesComputed |
| 方向属性提案生成された | DirectionProposed |
| 境界制御提案生成された | BoundaryControlProposed |
| 通行制限提案生成された | RestrictionProposed |
| 最適化スキップされた | OptimizationSkipped |
| フィードバック値出力された | FeedbackEmitted |

スタッフ→システム接点（現場誘導）：DangerFlagToggledByOperator／ScheduleEventRegistered／CongestionManuallyReported

## 不変条件

- ステートレスでグラフ・検知状態は外部が累積適用して毎回渡す（正本＝グラフ編集／受け渡し＝観測）
- 入力は保護境界のテナントIDと最適化対象のイベントIDの両方
- 最適化は1イベント（1グラフ）ごと
- 改善データ利用は同一テナント内または匿名化済み他テナント一般情報のみ
- 安全要件は基本・厳密の両モードで非緩和
