"""サービス境界の Request / Response

プロトコル（gRPC／HTTP／メッセージキュー）非依存の論理スキーマ。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from ..detection.state import DetectionState
from ..detection.triggers import Event
from ..domain.graph import Graph
from ..domain.history import HistoryDigest
from ..domain.observations import Observations
from ..domain.references import Reference
from .config import ResolvedConfig
from .context import TenantContext
from .diagnostics import Diagnostics
from .feedback import FeedbackValues
from .verdict import Verdict

if TYPE_CHECKING:
    # 最適化ソルバー（linopy/highspy）の実 import を避けるため型チェック時のみ参照。
    # from __future__ import annotations によりアノテーションは遅延評価される。
    from ..optimization.results import OptimizationResult

REQUEST_SCHEMA_VERSION = "request/1"


@dataclass(frozen=True, kw_only=True)
class Request:
    request_id: str  # 外部が発行する冪等キー
    tenant_context: TenantContext
    graph: Graph
    observations: Observations
    history_digest: HistoryDigest
    detection_state: DetectionState  # 前回本サービスが返した値
    references: Reference  # コールドスタート／フォールバック用
    config: ResolvedConfig  # マージ済み設定値
    server_time: datetime  # 外部が付与する現在時刻
    schema_version: str = REQUEST_SCHEMA_VERSION
    previous_result: OptimizationResult | None = None  # 前回本サービスの出力
    events: tuple[Event, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Response:
    request_id: str
    verdict: Verdict
    updated_detection_state: DetectionState  # 次回リクエストで渡す
    feedback_values: FeedbackValues = field(default_factory=FeedbackValues)
    diagnostics: Diagnostics = field(default_factory=Diagnostics)
    optimization_result: OptimizationResult | None = None  # verdict = optimized のみ
    elapsed_ms: int = 0
