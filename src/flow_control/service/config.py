"""統一 ResolvedConfig（サービス境界の設定契約）

外部（テナント管理サービス）がグローバルデフォルトとテナントオーバーライドを
マージ済みの最終値である。本サービスはマージロジックを持たない。

各モジュール（detection / forecasting / detour_routing / optimization）は現状
それぞれ独自の ResolvedConfig を持つが、設計はサービス境界で単一の
ResolvedConfig を受け取ることを正典とする。本クラスはその正典契約を定義する。
既存のモジュール別 config は当面温存し、将来この統一 config からの射影
（サブビュー）へ段階的に置き換える。

拡張ロードマップ連動フラグは、すべて初期値で現状動作と同一（ノーハーム）に
なるよう default を設定する。外部が最終値を必ず与えるため、必須項目にも
構築容易性のための便宜的 default を与えている（実挙動には外部提供値が用いられる）。
"""

from dataclasses import dataclass, field
from enum import Enum

from ..domain.graph import EdgeID


class OptimizationMode(str, Enum):
    LIGHTWEIGHT = "LIGHTWEIGHT"  # 基本モード（軽量分解）
    STRICT = "STRICT"  # 厳密モード（2 段階辞書式 MILP）


@dataclass(frozen=True)
class ThroughputWeights:
    # 第 2 段階スループット重み（ロードマップ項目 G-1）
    trigger_origin: float = 1.0
    detour_path: float = 1.0
    operator_set: float = 1.0


@dataclass(frozen=True, kw_only=True)
class ResolvedConfig:
    # ── トリガー判定 ─────────────
    surge_rate_threshold_percent_per_min: float = 50.0
    high_stagnation_duration_min: float = 5.0  # M 分
    beta: float = 1.0  # 停滞警戒 (a).2 の相対閾値（停滞プロキシ基準値 s̄_e 比）
    # 需要超過比 ρ̂ の閾値（需要警戒 (b).2）。None = 需要超過判定を無効化（急増 (b).1 のみ）
    theta_demand: float | None = None
    min_window_samples: int = 5  # 窓内有効サンプル数の下限（未満は警戒どまり）
    cooldown_duration_min: float = 60.0  # >= 10
    warmup_duration_min: float = 60.0
    retrigger_warning_threshold: int = 3
    retrigger_reset_quiet_cycles: int = 3
    queue_score_threshold: float = 5.0  # クールタイム中スコア超過判定
    queue_diversity_threshold: int = 3  # クールタイム中多様性超過判定
    # キュー統合発火の鮮度ガード X 分。None = cooldown_duration_min / 2 を使用
    queue_freshness_min: float | None = None

    # ── 最適化対象設定 ─────────
    throughput_target_edges: tuple[EdgeID, ...] = ()  # 特定ルート (B)

    # ── 最適化モード（基本＝軽量分解／厳密＝MILP） ──
    optimization_mode: OptimizationMode = OptimizationMode.LIGHTWEIGHT
    local_radius_hops: int = 2  # L7 局所化半径（基本モード）
    max_trigger_zones: int = 4  # 散在トリガー時のゾーン上限
    greedy_improve_margin: float = 0.05  # 方向反転採用の正規化 τ 改善しきい値

    # ── 機能2（通行制限/通行止め） ──
    restriction_proposal_enabled: bool = False  # しきい値調整・シャドウ検証後に有効化
    tau_danger_threshold: float | None = None  # 残留危険判定。None = 機能2 無効
    # ── 前処理 P（パンクトリガー (d)） ──
    puncture_trigger_enabled: bool = False
    puncture_ratio_threshold: float = 1.0  # σ_e ≥ ρ·C_e で発火

    # ── 計算時間予算 ─────────
    forecasting_budget_sec: float = 30.0
    detour_budget_sec: float = 30.0
    lightweight_opt_budget_sec: float = 120.0  # 基本モードの Optimization 予算
    milp_time_limit_sec: float = 600.0  # 厳密モード MILP 単体上限（基本モードでは未使用）
    max_consecutive_skips: int = 3  # 連続スキップ上限

    # ── ソルバー定数 ──────
    solver_seed: int = 0
    epsilon: float = 1e-3  # 辞書式緩和幅
    epsilon_0: float = 1e-6  # ゼロ除算回避
    big_m_factor: float = 1.0  # M = total_demand + max_capacity + 1 を係数倍
    delta_min: float = 0.5  # OD 量足切り
    confidence_weight_floor: float = 0.5  # 停滞プロキシ制約の信頼度重み c_e の下限クリップ
    mip_rel_gap: float = 0.0  # MILP 相対ギャップ許容（0 で HiGHS 既定＝ほぼ厳密解）

    # ── Forecasting Step ───
    gravity_alpha: float = 1.0  # 転換率欠測区間で使う距離 prior の減衰指数
    ipf_max_iter: int = 50  # 両制約 IPF 反復上限（決定性のため固定）
    ipf_tolerance: float = 1e-6  # IPF 収束閾値
    transit_time_prior_sec: float | None = None  # 通過所要時間 prior τ_pass。None で無効
    dwell_time_prior_sec: float | None = None  # 滞在時間 prior W_dwell。None で無効
    min_reference_sample_count: int = 5  # 参照値採用しきい値（K-匿名性連動）

    # ── Detour Step ────────
    k_shortest_paths: int = 3

    # ── フォールバック ───────────────────────
    fallback_eta: float = 1.0  # 最終フォールバック
    fallback_baseline_stagnation: float = 1.0

    # ── 拡張ロードマップ連動フラグ（default で現状動作と同一） ──
    scalar_direction_enabled: bool = False  # 項目 B
    k_shortest_paths_auto: bool = False  # 項目 C-1
    k_shortest_paths_max: int = 3  # 項目 C-1（auto 無効時は未使用）
    phase_feedback_enabled: bool = False  # 項目 E
    phase_feedback_candidates: int = 0  # 項目 E
    attribute_tag_priority: tuple[str, ...] = ()  # 項目 F-1
    full_weight_hours: float = 0.0  # 項目 F-2
    eta_mixing_ratio: float = 0.0  # 項目 F-3
    throughput_weights: ThroughputWeights = field(default_factory=ThroughputWeights)
    throughput_max_per_edge: tuple[tuple[EdgeID, float], ...] = ()  # 項目 G-2
    two_stage_optimization: bool = False  # 項目 I
    backoff_enabled: bool = False  # 項目 J
    improvement_threshold: float = 0.0  # 項目 J
    backoff_max_factor: int = 1  # 項目 J（指数 2^k の上限 k）
    shadow_extensions: tuple[str, ...] = ()  # 項目 MT-1-A
    delta_objective_enabled: bool = False  # 項目 K
    node_detour_enabled: bool = False  # 項目 L
    milp_boundary_control_enabled: bool = False  # 項目 M
    scheduled_inflow_prior_enabled: bool = False  # 項目 A-4

    # ── ロギング ─────────────────────────────
    log_tenant_id: bool = False
