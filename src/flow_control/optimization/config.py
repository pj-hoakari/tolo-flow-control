from dataclasses import dataclass
from enum import Enum

from ..domain.graph import EdgeID


class OptimizationMode(str, Enum):
    """Optimization Step の求解機構。"""

    LIGHTWEIGHT = "LIGHTWEIGHT"
    STRICT = "STRICT"


@dataclass(frozen=True)
class ResolvedConfig:
    # 既定は局所配分を基礎にした軽量モード。STRICT は基準系・小規模用。
    optimization_mode: OptimizationMode = OptimizationMode.LIGHTWEIGHT
    local_radius_hops: int = 2
    max_trigger_zones: int = 4
    greedy_improve_margin: float = 0.05
    lightweight_opt_budget_sec: float = 120.0
    # 配分 LP の混雑逓増（段ごとの単価増分）。>0 で等コストの並列ルートへ配分が
    # 分散する。0 で無効（単純な最短路シード配分）
    congestion_increment: float = 0.2
    restriction_proposal_enabled: bool = False
    tau_danger_threshold: float | None = None
    # ソルバー乱数シード（決定性担保）
    solver_seed: int = 0
    # MILP 単体のタイムアウト上限（秒）
    milp_time_limit_sec: float = 600.0
    # 辞書式 2 段階の緩和幅
    epsilon: float = 1e-3
    # ゼロ除算回避の微小値
    epsilon_0: float = 1e-6
    # Big-M 定数の係数倍
    big_m_factor: float = 1.0
    # OD 量の足切り閾値（これ以下の需要は最適化対象から除外）
    delta_min: float = 0.5
    # 停滞量制約の信頼度重み c_e の下限クリップ
    confidence_weight_floor: float = 0.5
    # オペレータ指定の特定ルート集合（スループット最大化対象）
    throughput_target_edges: tuple[EdgeID, ...] = ()
    # 基準停滞量 s̄_e が履歴に無い場合の補完値
    fallback_baseline_stagnation: float = 1.0
    # MILP 相対ギャップ許容（0 で HiGHS 既定＝ほぼ厳密解）
    # >0 を与えると最適性をわずかに譲る代わりに分枝限定を早期打ち切りして高速化する
    mip_rel_gap: float = 0.0
