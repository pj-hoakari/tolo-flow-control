"""TenantContext と EventContext（イベント種別・履歴可用時間。縮退モード要否判定用）"""

from dataclasses import dataclass
from enum import Enum


class EventTerm(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"


@dataclass(frozen=True)
class TenantContext:
    # tenant_id はデータ整合性検証のラベルとしてのみ使用する
    tenant_id: str


@dataclass(frozen=True)
class EventContext:
    # term と available_history_hours は縮退モード要否判定にのみ使用する
    term: EventTerm = EventTerm.SHORT
    available_history_hours: float = 0.0
