# E1: 共通スケール k に対する決定の不変性

設定: tolo-observation の defaultFlowConfig。ただし通行制限のスイッチとしきい値はシナリオの値を使う（本番では通行制限は無効）。

対象は 11 シナリオ、k ∈ [0.01, 0.1, 1.0, 10.0, 100.0]、変種は 3 つ（history: 履歴あり、no_history: p90・baseline・η を None にしてフォールバック定数を使わせる、obs_only: 観測と履歴だけを k 倍し capacity_hint・danger_capacity は据え置く）。各実行は決定的で、k=1 を 2 回走らせて署名の一致を確かめた（シード数の概念はない）。

## 前提の確認

| scenario | variant | 主張する決定種別 | k=1 で非空 |
|---|---|---|---|
| reversible-corridor-flip | history | direction | yes |
| reversible-corridor-flip | no_history | direction | yes |
| stadium-egress-concourse | history | direction | yes |
| stadium-egress-concourse | no_history | direction | yes |
| station-transfer-peak | history | direction | yes |
| station-transfer-peak | no_history | direction | yes |
| expo-gate-overcrowded | history | boundary | yes |
| expo-gate-overcrowded | no_history | boundary | yes |
| expo-incident-resume | history | boundary | yes |
| expo-incident-resume | no_history | boundary | yes |
| museum-special-exhibit-limit | history | restriction | yes |
| museum-special-exhibit-limit | no_history | restriction | yes |
| restriction-undrainable | history | restriction | yes |
| restriction-undrainable | no_history | restriction | yes |
| festival-gate-split | history | restriction | yes |
| festival-gate-split | no_history | restriction | yes |
| crossing-detour | history | detour | yes |
| crossing-detour | no_history | detour | yes |
| school-north-stair-peak | history | detour | yes |
| school-north-stair-peak | no_history | detour | yes |
| multi-route-surge | history | detour | yes |
| multi-route-surge | no_history | detour | yes |

k 倍した浮動小数フィールド: baseline_stagnation, capacity_hint, danger_capacity, directional_flow_samples, flow_rate, flow_samples, observed_count, occupancy, occupancy_delta, p90_stagnation, stagnation, stagnation_samples。
据え置いた浮動小数フィールド（人数次元でないことを目視で確認する対象）: completeness, flow_sensitivity_eta, time_resolution_s。

## 変種 history: k=1 からの決定差分

| scenario | k=0.01 | k=0.1 | k=1 | k=10 | k=100 |
|---|---|---|---|---|---|
| reversible-corridor-flip | direction,emphasis | 一致 | 一致 | 一致 | 一致 |
| stadium-egress-concourse | direction,detour,emphasis | 一致 | 一致 | 一致 | 一致 |
| station-transfer-peak | direction,emphasis | emphasis | 一致 | 一致 | emphasis |
| expo-gate-overcrowded | emphasis | 一致 | 一致 | 一致 | 一致 |
| expo-incident-resume | emphasis | 一致 | 一致 | 一致 | 一致 |
| museum-special-exhibit-limit | restriction,restriction_limit,emphasis | emphasis | 一致 | 一致 | 一致 |
| restriction-undrainable | restriction,restriction_limit,emphasis | 一致 | 一致 | 一致 | 一致 |
| festival-gate-split | restriction,restriction_limit,emphasis | 一致 | 一致 | 一致 | 一致 |
| crossing-detour | emphasis | 一致 | 一致 | 一致 | 一致 |
| school-north-stair-peak | emphasis | emphasis | 一致 | 一致 | 一致 |
| multi-route-surge | emphasis | 一致 | 一致 | 一致 | 一致 |

決定が変わった組: 15/44（11 シナリオ × 4 つの k）。

決定が一致した組での連続量の最大ずれ（OD/k と throughput/k は相対、τ は相対、重要度は絶対差）: od=2.22e-16, throughput=2.42e-08, tau=3.00e-06, importance=3.63e-07（29 組）。

## 変種 no_history: k=1 からの決定差分

| scenario | k=0.01 | k=0.1 | k=1 | k=10 | k=100 |
|---|---|---|---|---|---|
| reversible-corridor-flip | verdict,triggered,direction,emphasis | verdict,triggered,direction,emphasis | 一致 | 一致 | 一致 |
| stadium-egress-concourse | verdict,triggered,direction,detour,emphasis | verdict,triggered,direction,detour,emphasis | 一致 | 一致 | 一致 |
| station-transfer-peak | verdict,triggered,direction,detour,emphasis | verdict,triggered,direction,detour,emphasis | 一致 | 一致 | 一致 |
| expo-gate-overcrowded | emphasis | 一致 | 一致 | 一致 | 一致 |
| expo-incident-resume | verdict,triggered,emphasis | verdict,triggered | 一致 | 一致 | 一致 |
| museum-special-exhibit-limit | verdict,triggered,restriction,restriction_limit,emphasis | verdict,triggered,restriction,restriction_limit,emphasis | 一致 | 一致 | 一致 |
| restriction-undrainable | verdict,triggered,restriction,restriction_limit,emphasis | verdict,triggered,restriction,restriction_limit | 一致 | 一致 | 一致 |
| festival-gate-split | verdict,triggered,restriction,restriction_limit,emphasis | verdict,triggered | 一致 | 一致 | 一致 |
| crossing-detour | verdict,triggered,detour,emphasis | verdict,triggered,detour,emphasis | 一致 | 一致 | 一致 |
| school-north-stair-peak | verdict,triggered,detour,emphasis | verdict,triggered,detour,emphasis | 一致 | 一致 | 一致 |
| multi-route-surge | verdict,triggered,detour,emphasis | verdict,triggered,detour,emphasis | 一致 | 一致 | 一致 |

決定が変わった組: 21/44（11 シナリオ × 4 つの k）。

決定が一致した組での連続量の最大ずれ（OD/k と throughput/k は相対、τ は相対、重要度は絶対差）: od=2.22e-16, throughput=2.11e-04, tau=9.90e-01, importance=2.11e-04（23 組）。

## 変種 obs_only: k=1 からの決定差分

| scenario | k=0.01 | k=0.1 | k=1 | k=10 | k=100 |
|---|---|---|---|---|---|
| reversible-corridor-flip | direction,emphasis | direction,emphasis | 一致 | direction,emphasis | direction,emphasis |
| stadium-egress-concourse | direction,detour,emphasis | direction,emphasis | 一致 | direction,detour,emphasis | direction,detour,emphasis |
| station-transfer-peak | direction,emphasis | emphasis | 一致 | direction,detour,emphasis | direction,detour,emphasis |
| expo-gate-overcrowded | emphasis | 一致 | 一致 | 一致 | 一致 |
| expo-incident-resume | emphasis | 一致 | 一致 | 一致 | 一致 |
| museum-special-exhibit-limit | restriction,restriction_limit,emphasis | emphasis | 一致 | restriction,restriction_limit | restriction,restriction_limit |
| restriction-undrainable | restriction,restriction_limit,emphasis | 一致 | 一致 | restriction,restriction_limit | restriction,restriction_limit |
| festival-gate-split | restriction,restriction_limit,emphasis | restriction,restriction_limit | 一致 | restriction_limit | restriction_limit |
| crossing-detour | emphasis | emphasis | 一致 | emphasis | emphasis |
| school-north-stair-peak | emphasis | emphasis | 一致 | detour,emphasis | detour,emphasis |
| multi-route-surge | emphasis | 一致 | 一致 | detour,emphasis | detour,emphasis |

決定が変わった組: 36/44（11 シナリオ × 4 つの k）。

決定が一致した組での連続量の最大ずれ（OD/k と throughput/k は相対、τ は相対、重要度は絶対差）: od=1.48e-16, throughput=0.00e+00, tau=3.00e-06, importance=3.33e-07（8 組）。

## 帰属: 定数も k 倍したときに不変性が戻るか

| scenario | variant | k | 変わった決定 | commodities/OD | 不変性が戻る定数集合 |
|---|---|---|---|---|---|
| reversible-corridor-flip | history | 0.01 | direction,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| reversible-corridor-flip | no_history | 0.01 | verdict,triggered,direction,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| reversible-corridor-flip | no_history | 0.1 | verdict,triggered,direction,emphasis | 1/1 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| stadium-egress-concourse | history | 0.01 | direction,detour,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| stadium-egress-concourse | no_history | 0.01 | verdict,triggered,direction,detour,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| stadium-egress-concourse | no_history | 0.1 | verdict,triggered,direction,detour,emphasis | 1/1 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| station-transfer-peak | history | 0.01 | direction,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| station-transfer-peak | history | 0.1 | emphasis | 3/3 | delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| station-transfer-peak | history | 100 | emphasis | 3/3 | delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| station-transfer-peak | no_history | 0.01 | verdict,triggered,direction,detour,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| station-transfer-peak | no_history | 0.1 | verdict,triggered,direction,detour,emphasis | 3/3 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance |
| expo-gate-overcrowded | history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| expo-gate-overcrowded | no_history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| expo-incident-resume | history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| expo-incident-resume | no_history | 0.01 | verdict,triggered,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| expo-incident-resume | no_history | 0.1 | verdict,triggered | 2/2 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| museum-special-exhibit-limit | history | 0.01 | restriction,restriction_limit,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| museum-special-exhibit-limit | history | 0.1 | emphasis | 2/2 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| museum-special-exhibit-limit | no_history | 0.01 | verdict,triggered,restriction,restriction_limit,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| museum-special-exhibit-limit | no_history | 0.1 | verdict,triggered,restriction,restriction_limit,emphasis | 2/2 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| restriction-undrainable | history | 0.01 | restriction,restriction_limit,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| restriction-undrainable | no_history | 0.01 | verdict,triggered,restriction,restriction_limit,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| restriction-undrainable | no_history | 0.1 | verdict,triggered,restriction,restriction_limit | 2/2 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| festival-gate-split | history | 0.01 | restriction,restriction_limit,emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| festival-gate-split | no_history | 0.01 | verdict,triggered,restriction,restriction_limit,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| festival-gate-split | no_history | 0.1 | verdict,triggered | 2/2 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| crossing-detour | history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| crossing-detour | no_history | 0.01 | verdict,triggered,detour,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| crossing-detour | no_history | 0.1 | verdict,triggered,detour,emphasis | 1/1 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| school-north-stair-peak | history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| school-north-stair-peak | history | 0.1 | emphasis | 1/1 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| school-north-stair-peak | no_history | 0.01 | verdict,triggered,detour,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| school-north-stair-peak | no_history | 0.1 | verdict,triggered,detour,emphasis | 1/1 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| multi-route-surge | history | 0.01 | emphasis | 0/0 | delta_min, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| multi-route-surge | no_history | 0.01 | verdict,triggered,detour,emphasis | 0/0 | delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |
| multi-route-surge | no_history | 0.1 | verdict,triggered,detour,emphasis | 2/2 | fallback_baseline, delta_min+fallback_baseline, delta_min+fallback_baseline+ipf_tolerance, delta_min+fallback_baseline+epsilon_0, delta_min+fallback_baseline+ipf_tolerance+epsilon_0 |

定数集合の中身は delta_min = forecasting.delta_min と optimization.delta_min、fallback_baseline = detection と optimization の fallback_baseline_stagnation、ipf_tolerance = forecasting.ipf_tolerance、epsilon_0 = 3 モジュールの epsilon_0 である。fallback_eta はどの集合にも入れていない（η は 停滞/流量 で人数次元が打ち消し合う）。

## 退化の検査: k=1 のまま epsilon_0 だけを 0 倍・2 倍する

epsilon_0 は 1e-6 の零除算よけで、決定に効くはずがない。k=1 でこれを動かして決定が変わるなら、そのシナリオの決定は 1e-6 程度の摂動で入れ替わる境目（LP の代替最適解など）に乗っている。上の帰属で epsilon_0 が要った組は 2 種類ある。station-transfer-peak（history）は k=1 でも ε0 の摂動で重要度順位が入れ替わるので、LP の代替最適解の揺れであってスケールの効果ではない。reversible-corridor-flip（no_history）は k=1 の摂動では変わらない。k=0.1 では fallback を k 倍した s̄=0.1 に対してε0 の比が 10 倍になり、重要度 5e-4 の e_service が重要度 1e-9 の採用しきい値を割って順位から消える。流量のごく小さいエッジが表示のしきい値をまたぐ効果である。

| scenario | variant | ε0×0 | ε0×2 |
|---|---|---|---|
| reversible-corridor-flip | history | 一致 | 一致 |
| reversible-corridor-flip | no_history | 一致 | 一致 |
| stadium-egress-concourse | history | 一致 | 一致 |
| stadium-egress-concourse | no_history | 一致 | 一致 |
| station-transfer-peak | history | emphasis | emphasis |
| station-transfer-peak | no_history | 一致 | 一致 |
| expo-gate-overcrowded | history | 一致 | 一致 |
| expo-gate-overcrowded | no_history | 一致 | 一致 |
| expo-incident-resume | history | 一致 | 一致 |
| expo-incident-resume | no_history | 一致 | 一致 |
| museum-special-exhibit-limit | history | 一致 | 一致 |
| museum-special-exhibit-limit | no_history | 一致 | 一致 |
| restriction-undrainable | history | 一致 | 一致 |
| restriction-undrainable | no_history | 一致 | 一致 |
| festival-gate-split | history | 一致 | 一致 |
| festival-gate-split | no_history | 一致 | 一致 |
| crossing-detour | history | 一致 | 一致 |
| crossing-detour | no_history | 一致 | 一致 |
| school-north-stair-peak | history | 一致 | 一致 |
| school-north-stair-peak | no_history | 一致 | 一致 |
| multi-route-surge | history | 一致 | 一致 |
| multi-route-surge | no_history | 一致 | 一致 |

## この数字が別のものを測っている可能性

- 時間予算による打ち切り: 全実行で greedy_truncated が偽、solver_status が TIMEOUT でないことを assert した。
- 非決定性: k=1 を 2 回走らせ、署名の一致を assert した。
- スケールが効いていない: 変換前後の浮動小数の葉を全て列挙し、各葉の比が規則どおりの係数であることを assert した。k 倍したフィールドと据え置いたフィールドの一覧は上に載せた。
- 重要度の順位の同着: 重要度を 1e-6 で丸めて同着をまとめてから順位を比べている。LP の退化で同着の並びが揺れる分は差分に数えない。
- シナリオの偏り: devtools のシナリオは compact_configs（optimization.delta_min=8.0）を使う。本番既定の 0.5 では、壊れ始める k が変わる。
- 今回のシナリオは references、arc_demand_digest、SCHEDULED_INFLOW、前回の通行制限を持たないことを assert した。これらを持つ入力では、それらも k 倍しないと不変性の検証にならない。

