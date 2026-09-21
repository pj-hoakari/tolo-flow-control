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
