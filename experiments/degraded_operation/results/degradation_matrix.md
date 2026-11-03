# 縮退入力ごとの Flow エンジンの出力

`uv run python experiments/degraded_operation/matrix/degradation_matrix.py` が生成する。
手で編集しない。

## 条件

- グラフは devtools の `venue`、急増エッジは `e_j1_hallA`。1 分ごとに 50 サイクルを `decode_request` → `handle_request` に通し、`updated_detection_state` と `optimization_result` を次へ渡す。
- 平坦 30 サイクルのあと 31 サイクル目から急増する。「+N 分」は急増開始からの経過で、初回 OPTIMIZED で打ち切る。
- 設定は tolo-observation `defaultFlowConfig()`（急増閾値 10%/分、fallback_eta 0.25）。devtools の `observation_config()` は急増閾値 50 で、本番と食い違う。
- 入力の形は本番に合わせた。両方向の `ArcFlow` を常に送る、`completeness=0`、`references` 空、`directional_flow_samples` なし、全エッジ VECTOR。
- 長期統計は p90=1.5、baseline=1.0、eta=0.5、スパン 24.0 時間。基準の event_context は LONG・720 時間。
- 対照は 2 本。停滞のみ上昇（流量は平坦）と、全て平坦。どちらも発火すべきでない。

## 現状（プロトタイプなし）

列の意味。P/Δ/急 は急増エッジで (a).1・(a).2・急増が一度でも成立したか。警告は `Diagnostics.warnings` で、tolo-observation は捨てる。

| 条件 | 急増: 初回 OPTIMIZED | 発火エッジ | P/Δ/急 | 警告（Observation では不可視） | 対照 誤発火（停滞のみ / 平坦） | degraded_short_tenant | 仕様の期待 | 急増 | 対照 |
|---|---|---|---|---|---|---|---|---|---|
| 長期履歴あり（基準） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | §9.2.3 停滞警戒∧急増で発火 | 一致 | 一致 |
| 履歴なし（統計も直近窓もなし） | 発火せず | - | -/-/- | - | なし / なし | なし | §9.2.4 は P90 欠損だけを扱い、直近窓の欠落を定めない | 仕様外 | 一致 |
| 履歴スパン 4 時間未満（p90/baseline/eta が null） | 39（+8 分） | e_j1_hallA | -/Δ/急 | - | なし / なし | なし | §9.2.4 履歴不足 / §9.3: (a).2 だけで停滞警戒を判定して発火 | 一致 | 一致 |
| 長期統計あり・直近窓が常に空 | 発火せず | - | P/Δ/- | - | なし / なし | なし | 定めなし（§9.2.4 は P90 欠損時の縮退だけ） | 仕様外 | 一致 |
| 急増開始時に再起動（直近窓が空から 1 分ずつ戻る） | 36（+5 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | 定めなし。窓が戻れば §9.2.3 で発火するはず | 一致 | 一致 |
| 急増エッジにラインなし（arc_flows を送らない） | 36（+5 分） | e_j1_hallA | P/Δ/- | WARNING_CODE_DEGRADED_COMBINED_TRIGGER, WARNING_CODE_SURGE_PROXY_FALLBACK | あり / なし | なし | §9.2.4 ラインなし: 停滞警戒単独の縮退発火（DEGRADED_COMBINED_TRIGGER）、§9.1 SURGE_PROXY_FALLBACK | 一致 | 一致 |
| 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 発火せず | - | P/Δ/- | - | なし / なし | なし | §9.2.4 ラインなし（入力上は 0 人/分のラインと区別できない） | 不一致 | 不一致 |
| 間欠ライン（今回値あり・窓の流量 0 点） | 発火せず | - | P/Δ/- | - | なし / なし | なし | 定めなし（§9.1 は窓の系列を前提にする） | 仕様外 | 一致 |
| 間欠ライン（今回値あり・窓の流量 1 点） | 36（+5 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | §9.1 窓内の点で傾きを求める（今回値と合わせて 2 点） | 一致 | 一致 |
| 疎なライン（窓の点を 5 分に 1 点へ間引く） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | §9.1 窓内の点で傾きを求める | 一致 | 一致 |
| 観測点なし（急増エッジが無観測） | 発火せず | - | -/-/- | - | なし / なし | なし | §9.2.4 カメラなし: 警戒・発火なし | 一致 | 一致 |
| ノード占有なし | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | §9.2 は検知にノード占有を使わない（発火は変わらない） | 一致 | 一致 |
| 急増エッジが INVALID（急増開始 +3 分から。Observation の形） | 発火せず | - | P/Δ/- | - | なし / なし | なし | 要件 §5.6 / 設計 §3: INVALID の値は使わない（§9.2.4 カメラなし相当） | 一致 | 一致 |
| 急増エッジが HOLD（フラグのみ。値は実測のまま） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | 要件 §5.6: HOLD は低信頼として扱うが値は使う | 一致 | 一致 |
| 急増エッジが HOLD（Observation の形: 値を凍結し窓から外す） | 発火せず | - | P/Δ/- | - | なし / なし | なし | 要件 §5.6 / 設計 §3.5: 低信頼として使い、窓には含めない。発火可否は定めない | 仕様外 | 一致 |
| 端末脱落（急増開始 +3 分から今回値なし・窓も途切れる） | 発火せず | - | P/Δ/- | - | なし / なし | なし | 連携 §2.2.7: 欠損は HOLD/INVALID で届く前提。今回値なしはカメラなし相当（§9.2.4） | 一致 | 一致 |
| 観測が 10 分古い（observed_at だけ遅れる） | 40（+9 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | 定めなし（observed_at の鮮度規則はない） | 仕様外 | 一致 |
| 短期テナント（term=SHORT・available_history_hours=1） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | なし / なし | なし | §9.3 / 設計 §4.5: (a).2 のみ・degraded_short_tenant=true・ウォームアップ 15 分 | 不一致 | 一致 |

## 発火したサイクルの提案（急増の行のみ）

全 216 実行で `fallbacks_applied` は計 0 件だった。

| 条件 | solver | route_importance | detour_paths | 方向変更 | throughput | estimation_resolution | 補完アーク | 参照値の既定使用 | low_confidence_arc_ratio |
|---|---|---|---|---|---|---|---|---|---|
| 長期履歴あり（基準） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| 履歴スパン 4 時間未満（p90/baseline/eta が null） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | あり | 0.0 |
| 急増開始時に再起動（直近窓が空から 1 分ずつ戻る） | LIGHTWEIGHT | 7 | 2 | 0 | 75.29536 | TURNING_EXACT:6 | - | なし | 0.0 |
| 急増エッジにラインなし（arc_flows を送らない） | LIGHTWEIGHT | 7 | 2 | 0 | 75.29536 | DOUBLY_CONSTRAINED:6 | e_j1_hallA, e_j1_hallA | なし | 0.0 |
| 間欠ライン（今回値あり・窓の流量 1 点） | LIGHTWEIGHT | 7 | 2 | 0 | 75.29536 | TURNING_EXACT:6 | - | なし | 0.0 |
| 疎なライン（窓の点を 5 分に 1 点へ間引く） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| ノード占有なし | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| 急増エッジが HOLD（フラグのみ。値は実測のまま） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| 観測が 10 分古い（observed_at だけ遅れる） | INFEASIBLE | 7 | 0 | 0 | 289.254655 | TURNING_EXACT:6 | - | なし | 0.0 |
| 短期テナント（term=SHORT・available_history_hours=1） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |

## プロトタイプ適用後に変わった行

- D5: 直近窓に停滞サンプルがなく、履歴統計に baseline_stagnation があるとき、それを直近平均の代わりに使う。baseline がなければ従来どおり (a).2 を不成立とする。
- D6: ラインがあるのに傾きを計算できないとき、そのエッジをラインなし規則で判定する。
- D6 の「傾きを計算できない」には流量平均が 0 のエッジも入る。試作は急増エッジに限らず、流量 0 の全エッジをラインなし規則に回す。停滞が上がれば単独で発火するので、停滞のみの対照で誤発火が出る。窓の点が 2 点未満のときだけに絞れば、この誤発火は出ないはずである（推測。未実行）。
- どちらも `detection.detector.detect_metric_triggers` を入力書換えのラッパーで差し替えた試作で、src は変えていない。

| 試作 | 条件 | 系列 | 現状 | 試作後 |
|---|---|---|---|---|
| D6 | 長期統計あり・直近窓が常に空 | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D6 | 長期統計あり・直近窓が常に空 | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |
| D6 | 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D6 | 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |
| D6 | 間欠ライン（今回値あり・窓の流量 0 点） | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D6 | 間欠ライン（今回値あり・窓の流量 0 点） | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |
| D5+D6 | 長期統計あり・直近窓が常に空 | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D5+D6 | 長期統計あり・直近窓が常に空 | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |
| D5+D6 | 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D5+D6 | 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |
| D5+D6 | 間欠ライン（今回値あり・窓の流量 0 点） | 急増＋停滞（発火すべき） | 発火せず | 36（+5 分） |
| D5+D6 | 間欠ライン（今回値あり・窓の流量 0 点） | 停滞のみ上昇（発火すべきでない） | 発火せず | 36（+5 分） |

## Observation から見えない信号

tolo-observation は verdict、`updated_detection_state`、`optimization_result`、`feedback_values` を保存し、`Diagnostics` を捨てる。

- `SURGE_PROXY_FALLBACK` と `DEGRADED_COMBINED_TRIGGER` は `Diagnostics.warnings` にしか出ないので、Observation からは見えない。
- `fallbacks_applied`、`trigger_evidences`、`degraded_short_tenant` は Observation が捨てる以前に、`handle_request` が詰めない。
- `feedback_values.warnings` は空のまま、`quality_metrics.low_confidence_arc_ratio` は 0.0 固定である。HOLD/INVALID を送っても feedback には現れない。
- feedback から読めるのは `estimation_resolution` の解像度と補完アーク、`reference_usage.used_default` だけである。

## 入力の作り方で注意する点

- 端末脱落の行は依頼どおり今回値を送らない形にした。Observation の `NewSnapshot` は欠損 15 分以内を HOLD（最後の値を保持）、それより長いと INVALID として送るので、本番の形は HOLD（凍結）と INVALID の行に当たる。
- HOLD（凍結）の行は急増開始 +3 分から最後まで HOLD のままにした。本番では 15 分で INVALID に変わるが、HOLD の間に一度も発火していないので結論は変わらない。
- 古い観測の行は `observed_at` だけを 10 分戻し、値は今回のものを使った。値ごと 10 分遅れる場合は、基準の発火が 10 分遅れるだけになる（推測。未実行）。
- `devtools/observation_shaped_request.md` は、両方向の `ArcFlow` を送ると OD が空になり throughput が 0 になると書く。今回は両方向を送っても throughput は発火時の急増エッジ流量に等しかった（原因は未調査）。発火が遅い行で INFEASIBLE になるのは、`e_in_j1` の需要が capacity_hint 80 を超えるためと推測する。
- ラインなし（0 人/分）の行は、ラインのない観測点でも Observation が `RouteScore` の両方向 0 を送るという推測に基づく（`appendArcObservations` は常に 2 本の `ArcFlow` を足す）。
