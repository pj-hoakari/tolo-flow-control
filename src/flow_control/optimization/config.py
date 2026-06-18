from dataclasses import dataclass

from ..domain.graph import EdgeID


@dataclass(frozen=True)
class ResolvedConfig:
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
