"""シナリオパッケージ

配下のシナリオモジュール（先頭が ``_`` 以外）を名前順に自動 import し、各モジュールの
``@register`` による登録を集約する。**新しいシナリオはこのディレクトリに 1 ファイル追加する
だけ**で `list` / `run` / テストに反映される（手動の登録は不要）。
"""

from __future__ import annotations

import importlib
import pkgutil

from ._registry import SCENARIOS, get_scenario, register

__all__ = ["SCENARIOS", "get_scenario", "register"]

# 配下モジュールを名前順（決定的）に import して登録を発火させる
for _module in sorted(m.name for m in pkgutil.iter_modules(__path__)):
    if not _module.startswith("_"):
        importlib.import_module(f"{__name__}.{_module}")
