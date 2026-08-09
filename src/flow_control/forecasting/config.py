from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedConfig:
    min_reference_sample_count: int
    fallback_eta: float
    gravity_alpha: float = 1.0  # 距離減衰指数 α
    delta_min: float = 0.5  # OD 量カット δ_min
    transit_time_prior_sec: float | None = (
        None  # 通過所要時間 prior τ_pass（リトルの法則）。None で無効
    )
    dwell_time_prior_sec: float | None = None  # 滞在時間 prior W_dwell（リトルの法則）。None で無効
    ipf_max_iter: int = 50  # 両制約 IPF 反復上限（決定性のため固定）
    ipf_tolerance: float = 1e-6  # IPF 収束閾値
    epsilon_0: float = 1e-6  # ゼロ除算回避
