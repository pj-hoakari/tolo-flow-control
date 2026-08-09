"""flow_control 開発用パイプライン可視化ツール（CLI）

各モジュール（Detection / Forecasting / DetourRouting / Optimization）を直列に実行し、
シナリオ（プリセット＋ファジング）ごとに中間結果を JSON と PNG 画像で出力・検証する
開発専用ツール。本番エンジン（src/flow_control）には影響しない。
"""

import logging

# linopy/HiGHS は INFEASIBLE/TIMEOUT 時に warning を多量に標準出力へ流す。
# フォールバックは設計上の正常系なので開発ツールでは抑制する。
logging.getLogger("linopy").setLevel(logging.ERROR)
