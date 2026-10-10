# tolo-observation の形のリクエストで提案が出る条件

tolo-observation が `Optimize` に送るリクエストを再現し、verdict と `optimization_result` を確かめた記録。
再現の対象は tolo-observation `origin/main` の `internal/infra/connect/flow_client.go` にある `newOptimizeRequest` と、`internal/domain/snapshot.go` にある `NewSnapshot` である。
対象の Linear Issue は MER-107。

## 再現の方法

`devtools/scenarios/_observation.py` は、Observation と同じ固定値でリクエストを proto で組み立てる。
組み立てたリクエストは `decode_request` と `handle_request` に渡す。
1 分窓の計測を 1 分ごとに 17 サイクル送り、前サイクルの `updated_detection_state` と `optimization_result` を次のリクエストへ渡す。
Observation の `ObservationCycle.Run` と同じ持ち回りである。

グラフは `venue` プリセットの位相を使い、エッジの属性は Observation に合わせた。
全エッジを `BIDIRECTIONAL_PRIOR`、`VECTOR`、`enabled=true` とし、`danger_flag` は `false` とした。
計測では、通過流量 5 人/分が `in→j1→hallB→j2→out` を流れる。
`in→j1→hallA` の流量は 10 人/分から始まり、11 サイクル目から毎分 1.4 倍に増える。

シナリオは 2 つある。

| シナリオ | 内容 | 結果 |
|----------|------|------|
| `observation-as-sent` | Observation が今送る形のまま | 全サイクルで `SKIPPED_NO_TRIGGER` |
| `observation-with-history` | 後述の値を足した形 | 17 サイクル目で `OPTIMIZED` |

```sh
uv run python -m devtools run observation-as-sent
uv run python -m devtools run observation-with-history
uv run pytest tests/test_devtools.py -k observation_shaped
```

## 今の形では提案が出ない

`observation-as-sent` は、流量が毎分 1.4 倍に増えている間も 17 サイクルすべてが `SKIPPED_NO_TRIGGER` になり、`optimization_result` を返さない。
ウォームアップと危険フラグは関係しない。`Events` が空なので、どちらも設定されないからである。

Detection の通常トリガーは、停滞警戒が `high_stagnation_duration_min` 分続いたうえで、需要警戒と組み合わさったときだけ発火する。
今の形には、この判定に使う値が 3 つ欠けている。

- `Observations.arc_stagnations` が空なので、停滞警戒が成立しない。
- 停滞警戒の相対増分 (a).2 は、`HistoryDigest.window_series[].stagnation_samples` の平均と比べる。履歴が空なので、`arc_stagnations` だけを送っても成立しない。
- 急増の判定は、`flow_samples` と今回のライン通過から傾きを求める。サンプルが今回の 1 点だけになり、傾きを計算できない。

パンクトリガーも発火しない。`puncture_trigger_enabled=false` で、全エッジが `VECTOR` だからである。
`TenantCategory=SHORT_TERM` と `AvailableHistoryHours=0` は、今の実装の判定に使われていない。

## 提案を出すために Observation 側で埋める値

`observation-with-history` は、次の 4 点を変えると 17 サイクル目で `OPTIMIZED` になる。

1. ルートごとの停滞量を `ArcStagnation` で送る。Observation の `RouteScore.StagnationScore` は今は常に 0 で、送ってもいない。
2. ルートごとに、直近のサイクルの値を `ArcWindowSeries` で送る。`flow_samples` には両方向のライン通過の合計を、`stagnation_samples` には停滞量を入れる。シナリオでは直近 30 サイクル分を入れた。急増の評価窓が `surge_evaluate_window_minute`（既定 30 分）だからである。
3. `surge_rate_threshold_percent_per_min` を下げる。50 では発火しない。
4. 流量が 0 の方向の `ArcFlow` を送らない。

3 の閾値は次のように決めた。
急増率は、窓内の系列に最小二乗で直線を当てはめた傾きを系列の平均で割った値である。
平坦な期間が窓に残っていると、急増率は小さく出る。
10 分の平坦期間のあとに毎分 3 倍で増える系列でも、急増率は最大でおよそ 31%/分にとどまる。
シナリオの系列は 10%/分以下の閾値でだけ発火し、15%/分以上では 17 サイクル内に発火しなかった。

4 は Forecasting 側の挙動による。
`forecasting/od.py` の `_directed_flows` は、エッジごとに最後の `ArcFlow` だけを残す。
Observation は両方向の `ArcFlow` を必ず送るので、流量 0 の `B_TO_A` が `A_TO_B` の値を上書きする。
その結果、OD が空になる。
OD が空でも `OPTIMIZED` にはなるが、`throughput` は 0 で、迂回路は実際の需要を反映しない。
両方向に人が流れるエッジでは、どちらかの方向が必ず失われる。
Observation 側の回避策とは別に、Flow 側で直すかどうかを決める必要がある。

## 埋めた後にも残る点

`observation-with-history` の最終サイクルは `OPTIMIZED` だが、`solver_status` は `INFEASIBLE` になる。
軽量モードの基準配分 LP が解けず、容量超過をスラック化したフォールバックが結果を返すためである。
`route_importance` と `tau_star` は返るが、`detour_paths` は空で、`direction_proposal` はすべて `KEEP` である。

シナリオを一時的に書き換えて確かめると、停滞量を送るエッジを発火エッジ 1 本だけにした場合は `LIGHTWEIGHT` で解け、迂回路が 2 本返った。
`e_in_j1`、`e_j1_hallB`、`e_hallA_j2`、`e_hallB_j2` のどれか 1 本に停滞量 1.0 を足すと、`INFEASIBLE` に戻った。
停滞量を 0 にしても結果は変わらなかった。
原因は特定していない。
Observation は観測した全ルートの停滞量を送る想定なので、Flow 側で調べる必要がある。

`NodeOccupancy.occupancy` を常に 0 で送る点（`people_score` が 0）は、今回の発火と OD の推定を止めなかった。
提案の内容への影響は確かめていない。
