"""TenantContext（テナント種別・履歴可用時間。縮退モード要否判定用）"""

from dataclasses import dataclass
from enum import Enum


class TenantCategory(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


@dataclass(frozen=True)
class TenantContext:
    # tenant_id はデータ整合性検証のラベルとしてのみ使用する
    tenant_id: str
    # tenant_category と available_history_hours は縮退モード要否判定にのみ使用する
    tenant_category: TenantCategory = TenantCategory.LONG_TERM
    available_history_hours: float = 0.0
