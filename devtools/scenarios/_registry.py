"""シナリオレジストリ

各シナリオファイルは ``@register("<name>")`` で自前の builder を登録する。
``devtools/scenarios/__init__.py`` が全モジュールを自動 import することで登録が完了する。
"""

from __future__ import annotations

from collections.abc import Callable

from ..scenario_base import Scenario

# 登録順（= import 順）を保持する。表示順の決定性は __init__ の探索順で担保する
SCENARIOS: dict[str, Callable[[], Scenario]] = {}


def register(name: str) -> Callable[[Callable[[], Scenario]], Callable[[], Scenario]]:
    """シナリオ builder を ``name`` で登録するデコレータ"""

    def deco(fn: Callable[[], Scenario]) -> Callable[[], Scenario]:
        if name in SCENARIOS:
            raise ValueError(f"duplicate scenario name: {name!r}")
        SCENARIOS[name] = fn
        return fn

    return deco


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario: {name!r}. available: {sorted(SCENARIOS)}")
    return SCENARIOS[name]()
