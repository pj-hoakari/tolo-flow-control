# Flow Control 入出力仕様

package: `tolo.flow.v1`
実現するコンテキスト: flow_control_context.md（ドメイン定義 flow_control_domain.md）
役割: 危険箇所のリスクを下げる大局的な誘導提案の生成。ステートレス
呼び出し元は観測のみ（観測が ACL として翻訳・オーケストレート）
呼び出しは Service Gateway を経由しない直接の同期 RPC（補足「呼び出し経路と認可」）

## RPC 一覧

| RPC | 説明（ユビキタス言語） | 呼び出し元 | 認可 | 関連ドメインイベント |
|---|---|---|---|---|
| Optimize | 観測が Flow の型へ変換したグラフ・観測値と、履歴の要約・検知状態・手動介入・参照値・解決済みの設定値を受け取り、トリガー評価と近似最適化を行い、判定・提案（ルートの重要度・方向・通行制限・迂回経路・境界制御）・更新後の検知状態・フィードバック値・診断を返す | 観測のみ | インフラ層の到達制御（Service Gateway 非経由。補足参照） | SurgeTriggered／HighStagnationTriggered／PunctureTriggered／ScheduleTriggered／DangerFlagRaised・Lowered／WatchStateEntered／TriggerEnqueued／QueueMergedFired・QueueDiscarded／Optimized／WeightedRoutesComputed／DirectionProposed／BoundaryControlProposed／RestrictionProposed／OptimizationSkipped／FeedbackEmitted |

ステートレスのため RPC は 1 つ
発生したドメインイベントは応答（`verdict`・`optimization_result`・`updated_detection_state`・`diagnostics`）として表現し、永続化は観測が行う。対応は flow_control_context.md に示す

## proto 定義

proto の原本は tolo-flow-control の `proto/tolo/flow/v1/flow.proto` とし、ORAS の成果物 `ghcr.io/pj-hoakari/tolo-flow-control-proto` で配布する。
Observation はこの成果物を取得して Go のコードを生成する。
本書は最上位のメッセージと判定だけを写し、下位のメッセージ（グラフ、観測値、履歴の要約、検知状態、提案、設定値など）の定義は原本に従う。
原本は共有カーネル（`tolo.kernel.v1`）を import しない。

```proto
syntax = "proto3";
package tolo.flow.v1;

service FlowControlService {
  rpc Optimize(OptimizeRequest) returns (OptimizeResponse);
}

message OptimizeRequest {
  optional string request_id = 1;
  optional string schema_version = 2;
  optional string event_id = 3;
  TenantContext tenant_context = 4;
  Graph graph = 5;
  Observations observations = 6;
  HistoryDigest history_digest = 7;
  DetectionState detection_state = 8;
  Reference references = 9;
  optional OptimizationResult previous_result = 10;
  repeated Event events = 11;
  ResolvedConfig config = 12;
  google.protobuf.Timestamp server_time = 13;
}

message OptimizeResponse {
  optional string request_id = 1;
  optional Verdict verdict = 2;
  DetectionState updated_detection_state = 3;
  FeedbackValues feedback_values = 4;
  Diagnostics diagnostics = 5;
  optional OptimizationResult optimization_result = 6;
  int64 elapsed_ms = 7;
}

enum Verdict {
  VERDICT_UNSPECIFIED = 0;
  VERDICT_OPTIMIZED = 1;
  VERDICT_QUEUED = 2;
  VERDICT_SKIPPED_NO_TRIGGER = 3;
  VERDICT_SKIPPED_COOLDOWN = 4;
  VERDICT_SKIPPED_WARMUP = 5;
  VERDICT_SKIPPED_TIME = 6;
  VERDICT_ERROR_SIZE_EXCEEDED = 7;
  VERDICT_ERROR_INVALID_INPUT = 8;
}
```

### 要求の各フィールド

| フィールド | 内容 | 用意する側 |
|---|---|---|
| `request_id`・`schema_version`・`server_time` | 要求の識別、スキーマの版（`request/1`）、判定に使う現在時刻 | 観測 |
| `event_id`・`tenant_context` | 最適化の単位となるイベントと、テナント（`tenant_id`、テナント区分、使える履歴の時間） | 観測 |
| `graph` | Flow 独自のグラフ（ノードとエッジ）。グラフ編集から取得した現在の版を、観測が変換する | 観測（正本はグラフ編集） |
| `observations` | エッジの流量・停滞量とノードの滞留量。観測スナップショットのスコアを、観測が変換する | 観測 |
| `history_digest` | 同一イベントの過去の観測値から事前に計算した統計と時系列 | 観測 |
| `detection_state` | 前回の応答の `updated_detection_state` | 観測（構造は Flow が所有） |
| `references` | 他テナント由来の参照値（コールドスタート用） | 観測（生成は参照値集約） |
| `previous_result` | 前回の最適化結果 | 観測 |
| `events` | 手動介入と予定（危険フラグの上げ下げ、予定された流入など） | 観測 |
| `config` | 判定と最適化の設定値。外部でマージした最終値を受け取り、Flow はマージしない。求解モード（軽量／厳密）もここで指定する | 観測 |

### 判定（Verdict）

| 値 | 意味 |
|---|---|
| `VERDICT_OPTIMIZED` | 最適化を実行し、提案を生成した |
| `VERDICT_QUEUED` | トリガーを検出したが、クールタイム中のためキューに積んだ |
| `VERDICT_SKIPPED_NO_TRIGGER` | トリガーを検出せず、クールタイム外だった |
| `VERDICT_SKIPPED_COOLDOWN` | トリガーを検出せず、クールタイム中だった |
| `VERDICT_SKIPPED_WARMUP` | 対象がウォームアップ中で、手動トリガーもなかった |
| `VERDICT_SKIPPED_TIME` | 計算時間の上限を超えたため打ち切った |
| `VERDICT_ERROR_SIZE_EXCEEDED` | グラフの規模が上限を超えた |
| `VERDICT_ERROR_INVALID_INPUT` | 入力が不整合だった（テナント ID の不一致など） |

## 補足

- 呼び出し経路と認可: 本サービスへの呼び出しは Service Gateway を経由しない（service_gateway.md の例外。Auth・Edge Bridge Service に並ぶ）
  リクエストとレスポンスがグラフと履歴を同梱する最重量のペイロードであり、Service Gateway は認証・認可以外の処理をこのペイロードに加えないため、型付き委譲によるデコードと再シリアライズを毎サイクル行わない
  Observation 以外から到達できないことはインフラ層で保証する（Compose 環境はネットワーク構成、Cloud Run 環境は ingress 制限と Observation の実行 SA への Invoker IAM。service_transport.md）。本サービスはワークロード資格情報と内部JWTを要求しない
  テナント境界は `tenant_id`／`event_id` の必須受領（下記の検証点）と、強制点を観測に集約する現行の分担で維持する
  監査相関のため、呼び出し元は W3C Trace Context（`traceparent`）をリクエストメタデータで伝搬する
- 不変条件の検証点: `event_id` と `tenant_context.tenant_id` の両方必須（欠落は `invalid_argument`）、グラフ・検知状態・履歴の要約は毎回受領（保持しない）
- 履歴の同梱方式の採用理由: 本サービスを純関数に保ち、リクエスト完結（再現性・テスト容易性）とテナント保護境界の強制点を観測1箇所に維持するため
  観測の永続化層（PostgreSQL の時系列テーブル。Observation）は観測コンテキスト内部の実装詳細であり、本サービスは直接参照しない
- 履歴の要約（`history_digest`）の統計と時系列は観測が事前に計算する。時系列窓の期間はイベントの観測設定値（Tenant Management が保持する `ObservationSettings.history_window_days`。既定 30 日）に従い観測が決める。短期イベントの縮退は参照値（`references`）で補完
- 設定値（`config`）の取得元は未確定であり実装フェーズで確定する。それまで観測は既定値を渡す
- 悉皆でないスコア（共有カーネルの `exhaustive = false`）は、容量ヒントとの比較（パンク判定）とポイント間の大小比較に使わない。履歴パーセンタイルによる高停滞判定にのみ用いる。観測が Flow の型へ変換する際の扱いは実装フェーズで確定する
- 目的の優先順（1. 最大停滞量の近似最小化、2. 優劣つかない範囲でのスループット最大化）と安全要件の非緩和は実装制約である。応答の `optimization_result.objective_values` は両目的の値を返す
- 改善データは同一テナント内または匿名化済み参照値のみ（`references` にテナント識別子は含まれない）
- 提案の宛先はスタッフのみ（Operation の配送で開＝Realtime／閉＝Notification）。ゲストへ直接配信されない
- 本サービスの型は観測の外へ出ない。提案とフィードバック値は観測が Operation の型へ、参照値は観測が Reference Aggregation の型から本サービスの型へ変換する（Observation）
- 危険度（Risk Level）は内部概念のため応答に含めない
- 入出力の型は原本の proto が定め、本仕様は最上位の構造と判定の意味を定める。数理定式化は実装フェーズで確定する
