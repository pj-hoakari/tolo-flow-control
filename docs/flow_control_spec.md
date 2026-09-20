# Flow Control 入出力仕様

package: `tolo.flow.v1`
実現するコンテキスト: flow_control_context.md（ドメイン定義 flow_control_domain.md）
役割: 危険箇所のリスクを下げる大局的な誘導提案の生成。ステートレス
呼び出し元は観測のみ（観測が ACL として翻訳・オーケストレート）
呼び出しは Service Gateway を経由しない直接の同期 RPC（補足「呼び出し経路と認可」）

## RPC 一覧

| RPC | 説明（ユビキタス言語） | 呼び出し元 | 認可 | 関連ドメインイベント |
|---|---|---|---|---|
| Optimize | 共有カーネルのグラフ・観測スコアと検知状態・手動介入を受け取り、トリガー評価と近似最適化を行い、提案（重要度付きルート・方向属性・境界制御・通行制限）と更新後の検知状態を返す | 観測のみ | ワークロード資格情報の直接検証（Service Gateway 非経由。補足参照） | SurgeTriggered／HighStagnationTriggered／PunctureTriggered／ScheduleTriggered／DangerFlagRaised・Lowered／WatchStateEntered／TriggerEnqueued／QueueMergedFired・QueueDiscarded／Optimized／WeightedRoutesComputed／DirectionProposed／BoundaryControlProposed／RestrictionProposed／OptimizationSkipped／FeedbackEmitted |

ステートレスのため RPC は 1 つ
発生したドメインイベントは応答（`fired_triggers`・`verdict`）として表現し、永続化は観測が行う

## 参考 proto 定義

```proto
syntax = "proto3";
package tolo.flow.v1;
import "google/protobuf/timestamp.proto";
import "tolo/kernel/v1/kernel.proto";

service FlowControlService {
  rpc Optimize(OptimizeRequest) returns (OptimizeResponse);
}

message OptimizeRequest {
  string tenant_id = 1;  // 保護境界（必須）
  string event_id = 2;   // 最適化単位（必須。1イベント＝1グラフごと）
  tolo.kernel.v1.Graph graph = 3;                       // 正本＝グラフ編集、受け渡し＝観測
  tolo.kernel.v1.ObservationSnapshot snapshot = 4;
  History history = 5;                                  // 履歴一式（観測が永続化層から同一イベント分のみ切り出して同梱）
  DetectionState detection_state = 6;                   // 前回応答を観測がそのまま返送
  repeated ManualIntervention interventions = 7;        // 手動介入イベントの同梱
  repeated ReferenceValue reference_values = 8;         // コールドスタート用参照値（参照値集約由来）
  SolverMode solver_mode = 9;
}

message OptimizeResponse {
  Verdict verdict = 1;
  repeated FiredTrigger fired_triggers = 2;  // 発火したトリガー（イベントとして観測が記録）
  ProposalSet proposals = 3;
  DetectionState detection_state = 4;        // 更新後（観測が永続化）
  repeated FeedbackValue feedback_values = 5; // 効果測定用（観測経由で Operation が蓄積）
}

// 判定結果: 最適化／キュー／スキップ／エラー（エラーはイベント上スキップに内包）
enum Verdict {
  VERDICT_UNSPECIFIED = 0;
  VERDICT_OPTIMIZED = 1;
  VERDICT_QUEUED = 2;
  VERDICT_SKIPPED = 3;
  VERDICT_ERROR = 4;
}

// 求解モード: 基本（軽量・既定）／厳密。安全は両モード非緩和
enum SolverMode {
  SOLVER_MODE_UNSPECIFIED = 0;
  SOLVER_MODE_BASIC = 1;
  SOLVER_MODE_EXACT = 2;
}

// トリガー: 急増／高停滞／パンク／危険フラグ／スケジュール
enum TriggerKind {
  TRIGGER_KIND_UNSPECIFIED = 0;
  TRIGGER_KIND_SURGE = 1;
  TRIGGER_KIND_HIGH_STAGNATION = 2;
  TRIGGER_KIND_PUNCTURE = 3;
  TRIGGER_KIND_DANGER_FLAG = 4;
  TRIGGER_KIND_SCHEDULE = 5;
}

message FiredTrigger {
  TriggerKind kind = 1;
  tolo.kernel.v1.LocationRef location = 2;  // 発火位置（種類は kind が持つ。RiskLocation は危険箇所専用のため使わない）
  bool merged = 3;  // 統合発火（トリガーキューからの統合）
}

// 検知状態: クールタイム・ウォームアップ・キュー・警戒
// 構造は本サービスが所有し、観測は解釈せず保存・返送する
message DetectionState {
  repeated Cooldown cooldowns = 1;
  google.protobuf.Timestamp warmup_until = 2;
  repeated QueuedTrigger trigger_queue = 3;
  repeated WatchEntry watch = 4;
}
message Cooldown {
  TriggerKind kind = 1;
  tolo.kernel.v1.LocationRef location = 2;
  google.protobuf.Timestamp until = 3;
}
message QueuedTrigger {
  FiredTrigger trigger = 1;
  google.protobuf.Timestamp enqueued_at = 2;
}
message WatchEntry {
  tolo.kernel.v1.LocationRef location = 1;
  google.protobuf.Timestamp since = 2;
}

// 履歴一式: 過去の観測値・最適化履歴・フィードバックをもとに最適化する
// 永続化と切り出しは観測（永続化層）の責務。スコア比較は同一イベント内の過去スコアに対してのみ
message History {
  repeated tolo.kernel.v1.ObservationSnapshot snapshots = 1;  // 直近の時系列窓（需要予測: 点需要・ルート需要の分離推定に使用）
  repeated RouteStats route_stats = 2;                        // パーセンタイル統計（高停滞判定に使用）
  repeated PastOptimization optimizations = 3;                // 最適化履歴（効果測定・再発判定に使用）
  repeated FeedbackValue feedback_values = 4;                 // 過去のフィードバック値
}
message RouteStats {
  string route_id = 1;
  double stagnation_p50 = 2;
  double stagnation_p90 = 3;  // 高停滞判定の履歴パーセンタイル
}
// 最適化履歴の1件（OptimizationResultPersisted として観測が保存したもの）
message PastOptimization {
  google.protobuf.Timestamp optimized_at = 1;
  Verdict verdict = 2;
  repeated FiredTrigger fired_triggers = 3;
  ProposalSet proposals = 4;
}

// 手動介入（現場誘導のシステム接点。観測が受領して同梱）
message ManualIntervention {
  oneof kind {
    tolo.kernel.v1.DangerFlag danger_flag = 1;   // 危険フラグ操作（即時トリガー）
    ScheduleEntry schedule = 2;                  // スケジュール登録
    CongestionReport congestion = 3;             // 混雑の手動報告
  }
}
message ScheduleEntry {
  google.protobuf.Timestamp scheduled_at = 1;
  repeated string related_point_ids = 2;
}
message CongestionReport {
  tolo.kernel.v1.LocationRef location = 1;
  CongestionLevel level = 2;
}
// 混雑の手動報告レベル: 観測の入力用 enum から観測が ACL として変換して渡す（tolo.observation.v1 とは独立に定義）
enum CongestionLevel {
  CONGESTION_LEVEL_UNSPECIFIED = 0;
  CONGESTION_LEVEL_LOW = 1;
  CONGESTION_LEVEL_MID = 2;
  CONGESTION_LEVEL_HIGH = 3;
}

// 提案一式
message ProposalSet {
  repeated WeightedRoute weighted_routes = 1;
  repeated DirectionProposal directions = 2;
  repeated BoundaryControlProposal boundary_controls = 3;
  repeated RestrictionProposal restrictions = 4;
}

// 重要度付きルート: 0–1 の重要度提案
message WeightedRoute {
  string route_id = 1;
  double weight = 2;  // 0.0–1.0
}

// 方向属性提案: 一方／両通行（化・解除・反転・据置）
message DirectionProposal {
  string route_id = 1;
  DirectionAction action = 2;
}
enum DirectionAction {
  DIRECTION_ACTION_UNSPECIFIED = 0;
  DIRECTION_ACTION_MAKE_ONE_WAY = 1;
  DIRECTION_ACTION_MAKE_BOTH_WAYS = 2;
  DIRECTION_ACTION_REVERSE = 3;
  DIRECTION_ACTION_KEEP = 4;
}

// 境界制御提案: 入退出の一時停止・再開
message BoundaryControlProposal {
  string point_id = 1;  // 入退出点
  BoundaryAction action = 2;
}
enum BoundaryAction {
  BOUNDARY_ACTION_UNSPECIFIED = 0;
  BOUNDARY_ACTION_SUSPEND = 1;
  BOUNDARY_ACTION_RESUME = 2;
}

// 通行制限提案: 閉鎖・流量上限・解除
message RestrictionProposal {
  string route_id = 1;
  RestrictionAction action = 2;
  optional double flow_cap = 3;  // 流量上限（人/分）
}
enum RestrictionAction {
  RESTRICTION_ACTION_UNSPECIFIED = 0;
  RESTRICTION_ACTION_CLOSE = 1;
  RESTRICTION_ACTION_CAP_FLOW = 2;
  RESTRICTION_ACTION_LIFT = 3;
}

// フィードバック値: 効果測定と他テナント初期値参考（匿名化は Operation が境界前に実施）
message FeedbackValue {
  string kind = 1;
  double value = 2;
  map<string, string> attributes = 3;  // 属性タグの素材（幅・種別等）
  google.protobuf.Timestamp emitted_at = 4;  // 出力時刻（History での効果測定の照合に使用）
}

// 参照値: 他テナント由来のコールドスタート典型値（定義・消費は本サービス。生成は参照値集約）
message ReferenceValue {
  map<string, string> attribute_tags = 1;
  string kind = 2;
  double value = 3;
}
```

## 補足

- 呼び出し経路と認可: 本サービスへの呼び出しは Service Gateway を経由しない（service_gateway.md の例外。Auth・Edge Bridge Service に並ぶ）
  リクエストとレスポンスがグラフと履歴を同梱する最重量のペイロードであり、Service Gateway は認証・認可以外の処理をこのペイロードに加えないため、型付き委譲によるデコードと再シリアライズを毎サイクル往復させない
  呼び出し元の真正性は workload_auth.md の環境別方式で本サービスが直接検証し、論理Observationのみを許可する。SPIREは期待するSPIFFE ID、Cloud Runは本サービス宛のGoogle tokenとObservation SAを検証する。内部JWTは要求しない
  Observation 以外から到達できないことはインフラ層で保証する（Compose 環境はネットワーク構成、Cloud Run 環境は ingress 制限と IAM。環境の選択は workload_auth.md に従う）
  テナント境界は `tenant_id`／`event_id` の必須受領（下記の検証点）と、強制点を観測に集約する現行の分担で維持する
  監査相関のため、呼び出し元は W3C Trace Context（`traceparent`）をリクエストメタデータで伝搬する
- 不変条件の検証点: tenant_id と event_id の両方必須（欠落は `invalid_argument`）、グラフ・検知状態・履歴は毎回受領（保持しない）
- 履歴の同梱方式の採用理由: 本サービスを純関数に保ち、リクエスト完結（再現性・テスト容易性）とテナント保護境界の強制点を観測1箇所に維持するため
  観測の永続化層（PostgreSQL の時系列テーブル。Observation）は観測コンテキスト内部の実装詳細であり、本サービスは直接参照しない
- 時系列窓の本数・期間はイベントの観測設定値（Tenant Management が保持する `ObservationSettings.history_window_days`。既定 30 日）に従い観測が決める。短期イベントの縮退は参照値（`reference_values`）で補完
- `exhaustive = false` のスコアは容量ヒントとの比較（`RISK_KIND_PUNCTURE`）とポイント間の大小比較に使わない。履歴パーセンタイルによる高停滞判定（`RISK_KIND_HIGH_STAGNATION`）にのみ用いる
- 目的の優先順（1. 最大停滞量の近似最小化、2. 優劣つかない範囲でのスループット最大化）と安全要件の非緩和は実装制約であり、入出力には現れない
- 改善データは同一テナント内または匿名化済み参照値のみ（`reference_values` にテナント識別子は含まれない）
- 提案の宛先はスタッフのみ（Operation の配送で開＝Realtime／閉＝Notification）。ゲストへ直接配信されない
- 危険度（Risk Level）は内部概念のため応答に含めない
- 数理定式化は残課題（本仕様は入出力の型のみ確定させる）
