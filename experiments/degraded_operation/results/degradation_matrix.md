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

## 結果

列の意味。P/Δ/急 は急増エッジで (a).1・(a).2・急増が一度でも成立したか。状態と省いた判定は、急増の系列の 36 サイクル目（急増開始 +5 分。それより前に発火した行は発火の直前）に急増エッジへ出た `Diagnostics.element_states` の観測/履歴/ラインの点数と省いた判定。記録がなければ通常の状態。片側成立は急増開始後の `PARTIAL_COMBINED_TRIGGER` の held（reason があれば括弧に添える）。黙った不発は、発火せず、省いた判定も片側成立も出ない行。

| 条件 | 急増: 初回 OPTIMIZED | 発火エッジ | P/Δ/急 | 状態 | 省いた判定 | 片側成立 | 対照 誤発火（停滞のみ / 平坦） | 状態の表 | 急増 | 対照 | 黙った不発 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 長期履歴あり（基準） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | §6.2 観測 OK・履歴十分: 停滞警戒 ∧ 急増で発火 | 一致 | 一致 | なし |
| 履歴なし（統計も直近窓もなし） | 発火せず | - | -/-/- | OK/NONE/1 点 | SURGE, HIGH_STAGNATION, COMBINED | - | なし / なし | §6.2 履歴なし: 急増も停滞警戒も判定不能 | 一致 | 一致 | なし |
| 履歴スパン 4 時間未満（p90/baseline/eta が null） | 39（+8 分） | e_j1_hallA | -/Δ/急 | OK/SHORT/31 点 | - | - | なし / なし | §6.2 履歴 4 時間未満: (a).2 だけで停滞警戒を判定して発火 | 一致 | 一致 | なし |
| 長期統計あり・直近窓が常に空 | 発火せず | - | P/Δ/- | OK/ESTABLISHED/1 点 | SURGE, COMBINED | HIGH_STAGNATION | なし / なし | §6.2 長期統計あり・窓が空: 急増は判定不能。停滞警戒の成立を警告する | 一致 | 一致 | なし |
| 急増開始時に再起動（直近窓が空から 1 分ずつ戻る） | 36（+5 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | §6.2 窓が戻るまでは窓が空・ライン間欠、戻れば通常 | 一致 | 一致 | なし |
| 急増エッジにラインなし（arc_flows を送らない） | 発火せず | - | P/Δ/- | OK/ESTABLISHED/0 点 | SURGE, COMBINED | HIGH_STAGNATION | なし / なし | Q4: ラインなしの規則はない。流量が 0 点なので急増は判定不能（ライン間欠と同じ） | 一致 | 一致 | なし |
| 急増エッジにラインなし（Observation の形: 0 人/分を送る） | 発火せず | - | P/Δ/- | - | - | HIGH_STAGNATION (zero_flow) | なし / なし | Q4: 0 人/分は観測値。平均 0 は急増なし。停滞警戒の成立を流量 0 の理由つきで警告する | 一致 | 一致 | なし |
| 間欠ライン（今回値あり・窓の流量 0 点） | 発火せず | - | P/Δ/- | OK/ESTABLISHED/1 点 | SURGE, COMBINED | HIGH_STAGNATION | なし / なし | §6.2 ライン間欠（今回値の 1 点のみ）: 急増は判定不能 | 一致 | 一致 | なし |
| 間欠ライン（今回値あり・窓の流量 1 点） | 36（+5 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | §6.2 窓と今回値で 2 点: 通常 | 一致 | 一致 | なし |
| 疎なライン（窓の点を 5 分に 1 点へ間引く） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | §6.2 窓に 2 点以上: 通常 | 一致 | 一致 | なし |
| 観測点なし（急増エッジが無観測） | 発火せず | - | -/-/- | UNOBSERVED/NONE/0 点 | - | - | なし / なし | §6.2 観測なし: 対象外 | 一致 | 一致 | なし |
| ノード占有なし | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | 検知はノード占有を使わない（発火は変わらない） | 一致 | 一致 | なし |
| 急増エッジが INVALID（急増開始 +3 分から。Observation の形） | 発火せず | - | P/Δ/- | INVALID/ESTABLISHED/28 点 | - | - | なし / なし | §6.2 INVALID: 対象外 | 一致 | 一致 | なし |
| 急増エッジが HOLD（フラグのみ。値は実測のまま） | 発火せず | - | P/Δ/- | HOLD/ESTABLISHED/31 点 | SURGE, HIGH_STAGNATION, COMBINED | - | なし / なし | §6.2 HOLD: 値が実測でもフラグで判定不能 | 一致 | 一致 | なし |
| 急増エッジが HOLD（Observation の形: 値を凍結し窓から外す） | 発火せず | - | P/Δ/- | HOLD/ESTABLISHED/29 点 | SURGE, HIGH_STAGNATION, COMBINED | - | なし / なし | §6.2 HOLD: 判定不能 | 一致 | 一致 | なし |
| 端末脱落（急増開始 +3 分から今回値なし・窓も途切れる） | 発火せず | - | P/Δ/- | UNOBSERVED/ESTABLISHED/28 点 | - | - | なし / なし | §6.2 今回値なしは観測なしとして対象外 | 一致 | 一致 | なし |
| 観測が 10 分古い（observed_at だけ遅れる） | 発火せず | - | -/-/- | STALE/ESTABLISHED/31 点 | SURGE, HIGH_STAGNATION, COMBINED | - | なし / なし | §6.2 観測が古い（2 分解能以上、下限 60 秒）: HOLD と同じ | 一致 | 一致 | なし |
| 短期テナント（term=SHORT・available_history_hours=1） | 39（+8 分） | e_j1_hallA | P/Δ/急 | - | - | - | なし / なし | §6.3 term は縮退に使わない: 基準と同じ応答 | 一致 | 一致 | なし |

## 発火したサイクルの提案（急増の行のみ）

全 54 実行で `fallbacks_applied` は計 10 件だった。INFEASIBLE で発火したサイクルに記録がないと、スクリプトが止まる。

| 条件 | solver | route_importance | detour_paths | 方向変更 | throughput | estimation_resolution | 補完アーク | 参照値の既定使用 | low_confidence_arc_ratio |
|---|---|---|---|---|---|---|---|---|---|
| 長期履歴あり（基準） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| 履歴スパン 4 時間未満（p90/baseline/eta が null） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | あり | 0.0 |
| 急増開始時に再起動（直近窓が空から 1 分ずつ戻る） | LIGHTWEIGHT | 7 | 2 | 0 | 75.29536 | TURNING_EXACT:6 | - | なし | 0.0 |
| 間欠ライン（今回値あり・窓の流量 1 点） | LIGHTWEIGHT | 7 | 2 | 0 | 75.29536 | TURNING_EXACT:6 | - | なし | 0.0 |
| 疎なライン（窓の点を 5 分に 1 点へ間引く） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| ノード占有なし | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |
| 短期テナント（term=SHORT・available_history_hours=1） | INFEASIBLE | 7 | 0 | 0 | 206.610468 | TURNING_EXACT:6 | - | なし | 0.0 |

## Observation から見えない信号

tolo-observation は verdict、`updated_detection_state`、`optimization_result`、`feedback_values` を保存し、`Diagnostics` を捨てる。

- `element_states` と `PARTIAL_COMBINED_TRIGGER` の警告は `Diagnostics` にしか出ないので、Observation が保存するまで（O3）見えない。
- `fallbacks_applied` は配分 LP がフォールバックしたサイクルで記録する。`trigger_evidences` は `handle_request` が詰めない。
- `feedback_values.warnings` は空のまま、`quality_metrics.low_confidence_arc_ratio` は 0.0 固定である。HOLD/INVALID を送っても feedback には現れない。
- feedback から読めるのは `estimation_resolution` の解像度と補完アーク、`reference_usage.used_default` だけである。

## 入力の作り方で注意する点

- 端末脱落の行は依頼どおり今回値を送らない形にした。Observation の `NewSnapshot` は欠損 15 分以内を HOLD（最後の値を保持）、それより長いと INVALID として送るので、本番の形は HOLD（凍結）と INVALID の行に当たる。
- HOLD（凍結）の行は急増開始 +3 分から最後まで HOLD のままにした。本番では 15 分で INVALID に変わるが、HOLD の間に一度も発火していないので結論は変わらない。
- 古い観測の行は `observed_at` だけを 10 分戻し、値は今回のものを使った。古いとみなすのは観測分解能の 2 倍（下限 60 秒）以上の遅れで、分解能 60 秒では 120 秒になる。
- `devtools/observation_shaped_request.md` は、両方向の `ArcFlow` を送ると OD が空になり throughput が 0 になると書く。今回は両方向を送っても throughput は発火時の急増エッジ流量に等しかった（原因は未調査）。発火が遅い行で INFEASIBLE になるのは、`e_in_j1` の需要が capacity_hint 80 を超えるためと推測する。
- ラインなし（0 人/分）の行は、ラインのない観測点でも Observation が `RouteScore` の両方向 0 を送るという推測に基づく（`appendArcObservations` は常に 2 本の `ArcFlow` を足す）。
