from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedConfig:
    surge_rate_threshold_percent_per_min: float
    surge_evaluate_window_minute: float = 30.0
    high_stagnation_duration_min: float = 5.0
    # 停滞警戒 (a).2 の相対閾値（停滞プロキシ基準値 s̄_e に対する比率）
    beta: float = 1.0
    # 需要超過比 ρ̂ の閾値（需要警戒 (b).2）。None = 需要超過判定を無効化（急増のみ）
    theta_demand: float | None = None

    cooldown_duration_min: float = 60.0
    queue_score_threshold: float = 5.0
    queue_diversity_threshold: int = 3
    # キュー統合発火の鮮度ガード X 分
    # None なら cooldown_duration_min / 2 を使用
    queue_freshness_min: float | None = None

    warmup_duration_min: float = 60.0

    retrigger_warning_threshold: int = 3
    retrigger_reset_quiet_cycles: int = 3
    max_consecutive_skips: int = 3

    # パンクトリガー（前処理 P）。既定は無効（ノーハーム）
    puncture_trigger_enabled: bool = False
    puncture_ratio_threshold: float = 1.0  # σ_e ≥ ρ·C_e で発火

    # (a).2 の基準停滞量 s̄_e が履歴・参照値のいずれにも無い場合の最終フォールバック
    fallback_baseline_stagnation: float = 1.0
    # 参照値（属性タグ別 baseline）採用の集約元テナント数しきい値
    min_reference_sample_count: int = 5
    # ゼロ除算回避の微小値（相対閾値・需要超過比の分母）
    epsilon_0: float = 1e-6
