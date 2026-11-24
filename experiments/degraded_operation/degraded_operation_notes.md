# 観測点のゲインと縮退の実験

調査日: 2026-11-24

本書は `experiments/degraded_operation/` の実験の実行方法と、ADR-0131（hoakari-root）に書いた数値と今の結果の対応を記録する。
ADR-0131 の E1 と E2(a)(c) の数値は、判定を変える前のエンジンで測った値である。ADR は書き換えず、対応を本書に残す。

## 実験

| スクリプト                    | 内容                                                       | 結果                                                                    |
| ----------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| `gain/e1_scale_invariance.py` | E1: 全観測点を同じ倍率 k で変えたときの決定の不変性        | `results/e1_scale_invariance.md`、`results/e1_scale_invariance.production.md` |
| `gain/e2ac_point_gain.py`     | E2(a)(c): 観測点ごとのゲインの影響と、推定ゲインによる補正 | `results/e2ac_point_gain.md`、`results/e2ac_point_gain.production.md`   |
| `gain/e2b_gain_estimation.py` | E2(b): 保存則による相対ゲインの推定                        | `results/e2b_gain_estimation.md`                                        |
| `panic/panic_redefinition.py` | パンク判定の再定義の検証                                   | `results/panic_redefinition.md`                                         |
| `matrix/degradation_matrix.py` | 縮退入力ごとのエンジンの出力                              | `results/degradation_matrix.md`                                         |

各スクリプトは JSON と md を `results/` に書く。

```sh
uv run python experiments/degraded_operation/gain/e1_scale_invariance.py
uv run python experiments/degraded_operation/gain/e2ac_point_gain.py
EXPERIMENT_CONFIG=production uv run python experiments/degraded_operation/gain/e1_scale_invariance.py
EXPERIMENT_CONFIG=production uv run python experiments/degraded_operation/gain/e2ac_point_gain.py
uv run python experiments/degraded_operation/gain/e2b_gain_estimation.py
uv run python experiments/degraded_operation/panic/panic_redefinition.py
uv run python experiments/degraded_operation/matrix/degradation_matrix.py
```

E1 と E2(a)(c) は `EXPERIMENT_CONFIG` で設定を選ぶ。
既定の `devtools` はシナリオの設定のまま動かし、`*.md` に書く。
`production` は `gain/_common.py` の `production_configs()`（tolo-observation の defaultFlowConfig の写し。急増の閾値 5%/分、キューのスコアのしきい値 80、fallback_eta 0.25）で動かし、`*.production.md` に書く。
通行制限のスイッチとしきい値だけはシナリオの値を使う。
E2(b) は `EXPERIMENT_CONFIG` を付けずに動かす。付けると `e2b_gain_estimation.production.md` に書く。

2026-11-24 に上の 7 本を動かし直した。
どの結果もコミット済みのものとバイト単位で一致した。
所要時間は手元の Mac で、production の E1 が 18 秒、E2(a)(c) が 5 分 17 秒、E2(b) が 1 分 57 秒、パンクが 41 秒、縮退の表が 3.5 秒だった。

### 急増とキューの閾値を変えても E1 と E2(a)(c) の結果は同じだった

production の設定を急増 10%/分・キュー 5 から急増 5%/分・キュー 80 に変えた後も（cb1c67c）、E1 と E2(a)(c) の production の結果は変わらなかった。
変える前の値（急増 10%/分、キューは既定の 5）に戻して動かしても、結果は今のものとバイト単位で一致した。

## ADR-0131 の数値との対応

ADR-0131 の E1 と E2(a)(c) の数値は cce639f の production の結果である。
このときのエンジンには需要超過の判定と基準停滞量の固定の既定値があり、シナリオは 11 あった。
今の結果は判定を変えた後のエンジンで測った値で、発火しなくなった 2 シナリオを除いて 9 シナリオになっている（3b4bdaf）。

| 項目                                                     | ADR-0131（cce639f、11 シナリオ） | 今の結果（9 シナリオ） |
| -------------------------------------------------------- | -------------------------------- | ---------------------- |
| E1 履歴あり: 決定が変わった組                            | 15/44                            | 2/36                   |
| E1 履歴なし: 決定が変わった組                            | 21/44                            | 0/36                   |
| E1 観測だけを倍率で変える: 決定が変わった組              | 36/44                            | 20/36                  |
| E2(a) 判定と発火の集合が変わった件数                     | 0/550                            | 0/450                  |
| E2(a) 中核の決定が変わった割合                           | 9/550（1.6%）                    | 1/450（0.2%）          |
| E2(a) 重要度の順位が変わった割合                         | 234/550（42.5%）                 | 228/450（50.7%）       |
| E2(a) 通行制限の上限値の相対差（中央値 / p90）           | 14.7% / 39.0%                    | 12.5% / 34.1%          |
| E2(c) 30 分の推定値で補正したときの中核の決定（inject:poisson:60） | 45/550（8.2%）          | 30/450（6.7%）         |

E1 の履歴あり・履歴なしの変化は、ADR-0131 の Consequences にも書いてある。
E2(a)(c) の変化は ADR に書いていない。
今の結果でも、判定と発火の集合はゲインで変わらず、中核の決定より重要度の順位と上限値がゲインに弱い。
30 分の推定値で補正すると、中核の決定が変わる割合は補正しない場合より増える（0.2% から 6.7%）。

E2(b) とパンクの数値は ADR-0131 と今の結果で一致する。
