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

- グラフ: `linear` / `y-junction` / `grid` / `ring` / `venue` /
  `expo`（出入口1・ホール4・一方通行の周回コリドー）/
  `crossing`（2 ハブ＋主通路＋並行バイパス 2 本。迂回・方向提案が映える）
- シナリオ:
  - 基本: `single-route-surge` / `multi-route-surge` / `high-stagnation` /
    `danger-flag-edge` / `danger-flag-node` / `normal-no-trigger` /
    `open-mode` / `closed-mode` / `infeasible-fallback`
  - 大規模（expo グラフ。一方通行＋観測のないルート/ポイントを含む）:
    `expo-single-hall-surge` / `expo-multi-hall-surge` /
    `expo-oneway-unobserved` / `expo-danger-hall`
  - 運用効果が分かりやすい（expo グラフ）:
    `expo-gate-overcrowded`（入口過密→**gate で入退場停止**: boundary_control）/
    `expo-approach-capacity`（hallA 直行を低容量制限→**一方通行ループへ迂回**: route_importance がループへ）/
    `expo-incident-resume`（前回 gate 停止→危険解除で**再開提案 RESUME**）
  - 迂回・方向提案が映える（crossing グラフ）:
    `crossing-detour`（主通路 e_main 急増・低容量→**並行バイパス 2 本へ迂回**: detour_set k_eff=2、route_importance がバイパスへ）/
    `crossing-oneway`（バイパスを一方通行循環に→**direction_proposal が有向/双方向を提案**: 北 A_TO_B・南 B_TO_A・主通路 BIDIRECTIONAL）

> `expo-*` はホール 4 つ・一方通行ループ・センサ無し区間を含む現実的ケース。コモディティ数が
> 多く MILP が重いため `delta_min` を上げ MILP 時間上限を 8 秒に設定している（数〜20 秒程度）。
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
from ..scenario_base import Scenario, build_observations_and_history, make_scenario
from ._registry import register


@register("my-case")  # ← この名前で list/run から参照される
def build() -> Scenario:
    built = graph_builder.venue()
    obs, hist = build_observations_and_history(
        built.graph, surge_edges=frozenset({EdgeID("e_in_j1")})
    )
    return make_scenario("my-case", "説明文", built, obs, hist)
```

カスタムグラフが要るなら `graph_builder.GraphBuilder` で組むか、`graph_builder` にプリセットを
追加する。危険フラグは `scenario_base.with_edge_danger` / `with_node_danger`、観測のない
ルート/ポイントは `build_observations_and_history(..., unobserved_edges=..., unobserved_nodes=...)`
で表現できる。`登録キー == 返す Scenario.name` はテストで検証される。

出力先（既定 `_devout/`）は `.gitignore` 済み。画像内テキストは matplotlib 既定フォント
（CJK 非対応）に合わせて ASCII で記述している。
