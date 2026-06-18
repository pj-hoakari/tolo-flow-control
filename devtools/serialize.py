"""ドメイン/結果オブジェクトを JSON 可能な素朴な構造へ変換する

frozen dataclass・``NodeID``/``EdgeID``・Enum・``datetime``・frozenset を再帰的に
変換し、各モジュール結果の検査ログ兼リプレイ素材として書き出すために使う。
本番エンジン側には手を入れず devtools 内で完結させる。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from flow_control.domain import EdgeID, NodeID

# 値オブジェクトはラップを剥がして文字列として表現する（{"value": "n1"} を避ける）
_ID_TYPES = (NodeID, EdgeID)


def to_jsonable(obj: Any) -> object:
    """任意のオブジェクトを JSON シリアライズ可能な構造へ再帰変換する"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, _ID_TYPES):
        return obj.value
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {"_type": type(obj).__name__}
        for f in dataclasses.fields(obj):
            result[f.name] = to_jsonable(getattr(obj, f.name))
        return result
    if isinstance(obj, dict):
        return {_key_str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (frozenset, set)):
        # 決定性のため文字列表現でソートする
        return sorted((to_jsonable(v) for v in obj), key=repr)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    # 未知型は文字列化（最後の砦）
    return str(obj)


def _key_str(key: Any) -> str:
    if isinstance(key, _ID_TYPES):
        return key.value
    if isinstance(key, Enum):
        return str(key.value)
    return str(key)


def dump_json(obj: Any, path: Path) -> None:
    """``to_jsonable`` 変換後の JSON をファイルへ書き出す"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(to_jsonable(obj), fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
