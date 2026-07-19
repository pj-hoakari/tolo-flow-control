"""Verdict（サービス最終判定の 8 値）"""

from enum import Enum


class Verdict(str, Enum):
    OPTIMIZED = "optimized"
    QUEUED = "queued"
    SKIPPED_NO_TRIGGER = "skipped_no_trigger"  # トリガー未検出かつクールタイム外（定常状態）
    SKIPPED_COOLDOWN = "skipped_cooldown"
    SKIPPED_WARMUP = "skipped_warmup"
    SKIPPED_TIME = "skipped_time"
    ERROR_SIZE_EXCEEDED = "error_size_exceeded"
    ERROR_INVALID_INPUT = "error_invalid_input"
