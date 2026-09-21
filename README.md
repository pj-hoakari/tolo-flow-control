# flow_control_service

人流グラフの観測値から迂回・方向制御を導くステートレスな最適化エンジン。
`tolo.flow.v1.FlowControlService/Optimize` を ConnectRPC（HTTP/1.1）で公開する。

## ローカル起動

```sh
uv sync
uv run python -m flow_control.rpc
```

## イメージの build

```sh
docker buildx build --platform linux/amd64 -t tolo-flow-control:amd64 --load .
docker buildx build --platform linux/arm64 -t tolo-flow-control:arm64 --load .
```

## 起動

読み取り専用の root filesystem で動作する。

```sh
docker run -d --read-only --tmpfs /tmp -p 8080:8080 tolo-flow-control:arm64
```

`docker compose up --build` でも起動できる。環境変数は `compose.yml` の `environment` で変更できる。

## 環境変数

| 変数 | 既定値 | 内容 |
|---|---|---|
| `PORT` | `8080` | 待ち受けポート |
| `TOLO_RPC_MAX_REQUEST_BYTES` | `8388608` | 受理する要求本文の上限バイト数 |
| `TOLO_RPC_MAX_EXECUTION_SEC` | `720` | 1 要求あたりの最大実行時間（秒） |

## smoke テスト

起動中のコンテナに対して `/livez`・`/readyz` と Optimize（基本・厳密の両モード）を検証する。

```sh
TOLO_SMOKE_BASE_URL=http://127.0.0.1:8080 uv run pytest tests/rpc/test_container_smoke.py
```

`docker compose up --build` で起動した場合も `TOLO_SMOKE_BASE_URL=http://127.0.0.1:8080` で検証できる。

`TOLO_SMOKE_BASE_URL` を設定しない場合は skip される。

## publish

GitHub Release の公開、または `publish` workflow の手動実行（`version` 必須、`vX.Y.Z` / `vX.Y.Z-suffix`）で publish する。
手動実行でも対象は入力 version に対応する既存 release タグの commit であり、任意の branch の内容を publish することはできない。
共通検証（`ci` workflow）を通してから、実行イメージ `ghcr.io/pj-hoakari/tolo-flow-control` と proto の OCI アーティファクト `ghcr.io/pj-hoakari/tolo-flow-control-proto` を同一 version で公開する。

タグは先頭 `v` を外した `<version>` を必ず付け、安定版のうちリポジトリで最大の version のときだけ `<major>.<minor>`・`latest`（major が 0 以外なら `<major>` も）を追加する。
pre-release は `<version>` だけを付ける。

以下は publish 後の利用例である。**まだ一度も publish していないため、これらの成果物は現時点では存在しない。** private package の場合は事前に `docker login` / `oras login` する。

```sh
# 実行イメージ。配備では digest を固定する。
docker pull 'ghcr.io/pj-hoakari/tolo-flow-control:<version>'
docker pull 'ghcr.io/pj-hoakari/tolo-flow-control@sha256:<image-digest>'

# proto。取得先は旧版が混ざらない新規の空ディレクトリにする。
oras pull 'ghcr.io/pj-hoakari/tolo-flow-control-proto:<version>' -o proto
oras pull 'ghcr.io/pj-hoakari/tolo-flow-control-proto@sha256:<proto-digest>' -o proto

# 取得した proto を module にした buf.yaml と生成設定を利用側で用意して client を生成する。
buf generate --template '<consumer-buf.gen.yaml>'
```

公開するのは `.proto` と実行イメージだけで、Go / JS の生成済み client は配布しない。
利用側が必要な言語の client を proto から生成する。
