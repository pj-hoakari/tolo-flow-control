# flow_control_service

人流グラフの観測値から迂回・方向制御を導くステートレスな最適化エンジン。
`tolo.flow.v1.FlowControlService/Optimize` を gRPC（h2c）で公開する。

## 開発ツール

buf と task のバージョンは `mise.toml` で管理する。初回は `mise trust` が必要である。

```sh
mise install
```

proto 関連の作業は task にまとめてあり、CI も同じタスクを実行する。

```sh
task proto           # lint と生成をまとめて実行する
task proto:gen:check # 生成コードがコミット済みの内容と一致するか検査する
```

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
| `TOLO_RPC_MAX_REQUEST_BYTES` | `8388608` | 受理する要求メッセージの上限バイト数 |
| `TOLO_RPC_MAX_EXECUTION_SEC` | `720` | 1 要求あたりの最大実行時間（秒） |

## smoke テスト

起動中のコンテナに対して `grpc.health.v1.Health/Check` と Optimize（基本・厳密の両モード）を検証する。

```sh
TOLO_SMOKE_ADDRESS=127.0.0.1:8080 uv run pytest tests/rpc/test_container_smoke.py
```

`docker compose up --build` で起動した場合も `TOLO_SMOKE_ADDRESS=127.0.0.1:8080` で検証できる。

`TOLO_SMOKE_ADDRESS` を設定しない場合は skip される。

## publish

`task release VERSION=vX.Y.Z`（または `vX.Y.Z-suffix`）で GitHub Release を作ると publish される。
version は既存のタグのどれよりも新しくなければならず、publish 時にも、タグが release の commit を指していることと最新の version であることを確かめる。
実行イメージ `ghcr.io/pj-hoakari/tolo-flow-control` と proto の OCI アーティファクト `ghcr.io/pj-hoakari/tolo-flow-control-proto` を同一 version で公開する。

タグは先頭 `v` を外した `<version>` と `sha-<短縮 commit SHA>` を付け、安定版にはさらに `latest` を付ける。
pre-release には `latest` を付けない。

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
