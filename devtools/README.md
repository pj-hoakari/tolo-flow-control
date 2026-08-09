# devtools — 開発用パイプライン可視化ツール

`flow_control` の各モジュール（Detection → Forecasting → DetourRouting → Optimization）を
直列に実行し、シナリオごとに**各モジュールの中間結果を JSON と PNG 画像で出力・検証する**
開発専用 CLI。

> ⚠️ これは本番 `RequestHandler` の実装ではなく、各モジュール結果を観察・検証するための
> 開発専用ハーネスです（未実装の RequestHandler / FeedbackExtractor 本体には踏み込みません）。
> FeedbackExtractor も実装せず、ハーネスが既存結果から診断サマリを組み立てます。

## 実行方法

```sh
uv sync                                   # 依存（matplotlib, pyyaml）を導入
uv run python -m devtools <command> ...
```

## コマンド

### `list` — シナリオ／グラフプリセット一覧
```sh
uv run python -m devtools list
```

### `run` — シナリオを実行し各モジュール結果を出力
```sh
uv run python -m devtools run multi-route-surge --out ./_devout
```
`_devout/<scenario>/` に以下を出力:
- `graph.json` / `detection.json` / `forecasting.json` / `detour.json` / `optimization.json` / `run.json`（検証ログ兼リプレイ素材）
- 実行順プレフィックス付きモジュール別ディレクトリ配下の個別 PNG（例: `01_detection/trigger.png`）
  - 各グラフ本体に対し、同じ名前の `*_legend.png` を必ず出力する。旧来グラフ内にあった凡例・カラーバーを切り出した白背景 PNG で、色・線種ラベルとカラーバーだけを載せる。連続値（重要度・η・信頼度・滞在需要）は従来どおりグラデーションバーで表示し、グラフ本体からは除外する。
  - `02_forecasting/node_demand.png` / `od_demand.png` / `arc_flow_sensitivity.png` / `node_confidence.png`（各 `*_legend.png` 付き）
  - `03_detour/<起点エッジ>.png`（`*_legend.png` 付き）
  - `04_optimization/route_importance.png` / `direction_proposal.png`（各 `*_legend.png` 付き）
  - `00_summary/summary.png`

`00_summary/summary.png` は各モジュールの所要時間を**数値**で列挙する（Phase1/Phase2 内訳・合計付き）。
主なオプション: `--time-limit <秒>`（MILP。未指定ならシナリオ設定値）, `--seed <int>`
（ソルバーseed上書き）, `--no-images`（PNG出力なし）, `--force`（未発火でも下流を実行）。

### `run-all` — 全シナリオを実行し横断インデックス＋履歴を出力
```sh
uv run python -m devtools run-all --out ./_devout --label before-change
```
全シナリオを `run` と同様に出力したうえで、各 run の数値要約を
- 最新版: `_devout/index.json`
- **履歴スナップショット**: `_devout/history/<label>/index.json`（`--label` 省略時はタイムスタンプ）

にまとめる。要約は **`index.json` 1 ファイルで解析が完結する**よう派生指標まで畳み込む:
verdict・triggered・evidence_kinds／forecast（OD・reproduction_error・node_confidence レンジ・
resolution_modes・resolution_reasons・imputed_arcs・fallback_default_edges・staying_nodes）／detour（起点別
k_effective・経路本数・対象エッジ和集合）／optimization（solver・phase 時間・軽量モード統計・
tau*・throughput・fallback・可達性・route_importance_nonzero・方向変更種別・restriction proposals・boundary controls）。

にまとめる。履歴は数値のみで軽量。これを後述の `compare` で突き合わせると、コード変更前後の
**数値ベースの回帰/改善追跡**ができる。

### `compare` — 2 つの数値スナップショットを比較
```sh
# 変更前にスナップショットを取り、変更後にもう一度取って比較する
uv run python -m devtools run-all --label before
# （コード変更）
uv run python -m devtools run-all --label after
uv run python -m devtools compare before after
```
`base`/`against` は **ラベル / `latest` / ファイルパス** のいずれか。シナリオ単位で
- 結果系（verdict・solver・tau*・throughput・OD・fallback）= **決定的**なので差分は回帰/改善を意味する
- 性能系（phase1+phase2 ms と Δ%）= 壁時計のため目安

を数値テーブルで出力する。結果系に差分があれば `CHANGED:<field>` と表示し、終了コード 1 を返す
（CI での回帰検出に利用可）。

### `fuzz` — ランダムシナリオで不変条件を検証
```sh
uv run python -m devtools fuzz --count 50 --seed 1 --out ./_devout
```
プリセットグラフ上にランダムな観測・履歴・イベントを生成して多数実行し、以下を検証:
- 決定性（同一入力の再実行で出力一致）/ 例外なし / 空結果・INFEASIBLE の検出
- `ConstraintReport`（非フォールバック解で local/boundary 可達性・法規制違反 0）
- Forecasting（reproduction_error 有限・node_confidence∈[0,1]・OD 需要 ≥ 0）

違反/例外のあるケースのみ `_devout/fuzz/fail/` に成果物を保存（`--save-all` で全件）。
件数・内訳・各ケースの結果は違反有無に関わらず `_devout/fuzz/summary.json` に常時出力。
`--graph <preset|file>` で対象グラフを固定（既定は毎回ランダムなプリセット）。

### `graph` — グラフを構築・描画／保存
```sh
uv run python -m devtools graph venue --out ./_devout --save ./_devout/venue.yaml
uv run python -m devtools graph ./_devout/venue.yaml --out ./_devout   # 読み戻し
```

## プリセット

- グラフ:
  - 汎用位相: `linear` / `y-junction` / `grid` / `ring` / `venue` /
    `expo`（出入口1・ホール4・一方通行の周回コリドー）/
    `crossing`（2 ハブ＋主通路＋並行バイパス 2 本。迂回・方向提案が映える）
  - シナリオ固有位相（すべて `graph` コマンドで単独描画・保存可）:
    `crossing-oneway`（crossing のバイパスを一方通行循環に）/
    `plaza-line`（直線＋中央混在広場。Open モード最小）/
    `closed-ring`（入退出点なしの環状。Closed モード最小）/
    `oneway-leaf`（法規制固定の内向き葉＝構成異常）/
    `deadend-lobby`（袋小路ホール。機能2 最小）/
    `festival`（入場一本道→二系統分岐）/
    `station-stairs`（改札→並行 2 階段→ホーム）/
    `transfer-station`（2 改札・2 ホーム・並行 2 連絡通路）/
    `school`（唯一の1階入口→6階目的地。北・南階段と各階停止エレベーター、
    階段以外は未観測通過区間）/
    `stadium`（ボウル・可変コンコース・スカラー支線）/
    `flex-corridor`（可変通路＋常設細通路の 2 ノード最小）/
    `museum`（特別展袋小路＋常設展）/
    `design-limit`（上限規模 10 ノード/50 エッジの密グラフ）
  - ファジングのランダムローテーションは汎用位相のみ（expo とシナリオ固有位相は除外。
    `fuzz --graph <preset>` の明示指定は可）
- シナリオ（各シナリオの想定ケースと**期待する誘導提案**の一覧は
  `docs/devtools_scenario_catalog.md` を参照。緊急時・法的対処はスコープ外で、
  通常運営時の誘導のみを扱う）:
  - **A. 機能・モジュール検証**
    - Detection 判定・配分の基本: `single-route-surge`（組合せ発火ベースライン）/
      `multi-route-surge` / `high-stagnation`（lineless 縮退発火）/ `normal-no-trigger` /
      `danger-flag-edge` / `danger-flag-node`
    - Forecasting モード: `open-mode` / `closed-mode`
    - 状態遷移: `cooldown-skip`（**SKIPPED_COOLDOWN**）/ `cooldown-queued`（**QUEUED**）/
      `queue-burst-fire`（キュー累積の**統合発火**）/ `warmup-skip`（**SKIPPED_WARMUP**）
    - パンク: `puncture-scalar-corridor`（スカラー容量超過→**パンクトリガー**。
      スカラー区間が OD 推定の盲点であることも同時に示す）
    - 迂回・方向提案: `crossing-detour`（**並行バイパス 2 本へ迂回**）/
      `crossing-oneway`（**direction_proposal が有向/双方向を提示**）/
      `reversible-corridor-flip`（退場需要増で入場向き可変通路を**双方向へ解除 RELEASE_ONEWAY**）
    - 特殊経路・機能2・性能: `infeasible-fallback`（Phase1 INFEASIBLE→フォールバック）/
      `restriction-undrainable`（**機能2 の通行制限提案** LIMIT。
      `restriction_proposal_enabled` と `tau_danger_threshold` を設定して有効化）/
      `stress-design-limit`（上限規模 10 ノード/50 エッジの性能計測）
  - **B. 現実的・複雑ケース**
    - expo（一方通行＋観測のないルート/ポイントを含む大規模会場）:
      `expo-single-hall-surge` / `expo-multi-hall-surge` / `expo-oneway-unobserved` /
      `expo-danger-hall` /
      `expo-approach-capacity`（直行制限→**一方通行ループへ迂回**）/
      `expo-gate-overcrowded`（入口過密→**gate で入場停止**: boundary_control）/
      `expo-incident-resume`（過密解消後の**再開提案 RESUME**）
    - その他: `festival-gate-split`（入場急増を**二系統へ分散**）/
      `station-platform-closure`（階段低容量化→**代替階段へ誘導**）/
      `station-transfer-peak`（乗換ピーク→**センサ未設置の地下通路へ迂回**）/
      `school-north-stair-peak` / `school-south-stair-peak`
      （1〜5階と1階入口から6階目的地へ集まるピークで、混雑した片側階段を分散）/
      `school-north-stair-maintenance`（各階から6階へ集まる時間帯の北階段保守による容量低下を迂回）/
      `stadium-egress-concourse`（退場ピークで可変コンコースを**双方向へ解除**）/
      `museum-special-exhibit-limit`（特別展待ち列→**上流へ整理入場の LIMIT**）

> `expo-*` はホール 4 つ・一方通行ループ・センサ無し区間を含む現実的ケース。
> STRICT で基準系を回す場合に備え MILP 時間上限を 8 秒に短縮している。
> ファジングのランダム選択からは `expo` を除外（`fuzz --graph expo` で明示利用可）。

## 構成

| ファイル | 役割 |
|----------|------|
| `graph_builder.py` | グラフ構築（ビルダー API・プリセット・YAML/JSON 入出力・レイアウト） |
| `scenario_base.py` | シナリオ共通基盤（`Scenario`・設定・観測/履歴生成・`make_scenario` 等） |
| `scenarios/` | **1 ファイル 1 シナリオ**の定義群＋レジストリ（自動探索） |
| `pipeline.py` | 直列オーケストレーションハーネス（mode 判定・二相コミット） |
| `visualize.py` | matplotlib による各モジュール結果の PNG 描画 |
| `serialize.py` | ドメイン/結果 → JSON 変換 |
| `report.py` | 1 実行分の JSON＋PNG 一括出力、横断インデックス・履歴スナップショット |
| `compare.py` | 2 つの数値スナップショットの比較（履歴ベースの回帰/改善追跡） |
| `fuzzer.py` | ランダムシナリオ生成＋不変条件チェック |
| `cli.py` / `__main__.py` | CLI エントリポイント |

`scenarios/` の内訳:

| ファイル | 役割 |
|----------|------|
| `__init__.py` | 配下モジュールを名前順に自動 import し登録を集約。`SCENARIOS` / `get_scenario` を公開 |
| `_registry.py` | `@register("<name>")` デコレータ・レジストリ本体 |
| `_expo.py` | expo シナリオ共通部品（`expo_configs` / `make_expo_scenario`） |
| `<scenario>.py` | 各シナリオ（`@register` で登録された `build()` を 1 つ持つ） |

## シナリオの追加方法

`scenarios/` に 1 ファイル追加するだけ（手動登録・一覧への追記は不要。`__init__.py` が
自動探索する）。

```python
# devtools/scenarios/my_case.py
from flow_control.domain import EdgeID
from .. import graph_builder
from ..scenario_base import (
    Scenario,
    build_observations_and_history,
    established_watch_state,
    make_scenario,
)
from ._registry import register


@register("my-case")  # ← この名前で list/run から参照される
def build() -> Scenario:
    built = graph_builder.venue()
    hot = frozenset({EdgeID("e_in_j1")})
    # 組合せ発火: 急増（需要警戒）と停滞警戒＋計時済み watch を同一エッジへ与える。
    # 急増単独・停滞単独では現行 Detection は発火しない
    obs, hist = build_observations_and_history(built.graph, surge_edges=hot, stagnation_edges=hot)
    return make_scenario(
        "my-case",
        "説明文",
        built,
        obs,
        hist,
        previous_state=established_watch_state(hot),
    )
```

メトリクス発火させるシナリオは上記のように**組合せ条件**を満たす必要がある（危険フラグ
イベント経由なら不要）。発火しないことが意図のシナリオは `expect_trigger=False` を渡す。
`Scenario.expect_trigger` と実際の verdict の一致はテストで検証される（検証空洞化の防止）。

**観測生成は保存則整合の `build_consistent_observations_and_history` を推奨する。**
`ODSpec`（起点→終点レート、`surge=True` で急増成分）を渡すと current 方向の最短路で
流し込み、通過ノードで流入=流出、混在ホールで流入超過=ΔOcc が成立する観測を合成する。
Forecasting の OD 再現誤差が構造的に小さくなり、`delta_min` による需要全カット
（発火したのに提案が空になる）を避けられる。旧 `build_observations_and_history`
（エッジ一様フロー）は保存則が成立せず OD が過小になるため新規シナリオでは使わない。
留意: 混在ホールを「通過」する OD は滞在/通過の帰属が本質的に曖昧で誤差が残る。
境界→境界（ext→ext）の OD は設計の対象外のため内部目的地を必ず置くこと。

カスタムグラフが要るなら `graph_builder.GraphBuilder` で組むか、`graph_builder` にプリセットを
追加する。危険フラグは `scenario_base.with_edge_danger` / `with_node_danger`、観測のない
ルート/ポイントは `unobserved_edges=... / unobserved_nodes=...`
で表現できる。`登録キー == 返す Scenario.name` はテストで検証される。

出力先（既定 `_devout/`）は `.gitignore` 済み。画像内テキストは matplotlib 既定フォント
（CJK 非対応）に合わせて ASCII で記述している。
