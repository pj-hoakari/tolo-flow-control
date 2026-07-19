from dataclasses import dataclass, field


@dataclass(frozen=True)
class TagReference:
    attribute_tag: str
    eta_typical: float | None = None
    baseline_stagnation: float | None = None
    # 容量ヒント典型値（任意、capacity_hint 未設定時のフォールバック）
    capacity_typical: float | None = None
    sample_count: int = 0  # 集約元テナント数


@dataclass(frozen=True)
class ThresholdSet:
    # テナント種別別のデフォルト閾値セット（主に短期テナント縮退モードの初期値）。
    # 設計側で ThresholdSet の内訳が明示されていないため、トリガー判定に用いる
    # 主要閾値を保持する最小構成とする（設計側で確定次第フィールドを拡張する）。
    surge_rate_threshold_percent_per_min: float | None = None
    high_stagnation_duration_min: float | None = None
    beta: float | None = None
    theta_demand: float | None = None
    warmup_duration_min: float | None = None


@dataclass(frozen=True)
class ThresholdDefaults:
    short_term: ThresholdSet = field(default_factory=ThresholdSet)
    long_term: ThresholdSet = field(default_factory=ThresholdSet)


@dataclass(frozen=True)
class Reference:
    by_attribute_tag: tuple[TagReference, ...] = field(default_factory=tuple)
    # テナント種別別のデフォルト閾値（None = 未提供）
    default_thresholds: ThresholdDefaults | None = None
    source_k_anonymity: int = 0  # 参考情報，K>=5 の場合のみ信頼

    def tag_reference_of(self, attribute_tag: str) -> TagReference | None:
        for tag_reference in self.by_attribute_tag:
            if tag_reference.attribute_tag == attribute_tag:
                return tag_reference
        return None
