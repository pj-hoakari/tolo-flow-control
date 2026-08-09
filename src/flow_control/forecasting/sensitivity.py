"""フロー感度 η_e の決定（エッジ単位）

各ベクトル型エッジの流量感度 η_e を，
履歴 → 参照値 → 既定値のフォールバック階層
で解決し，どの段にフォールバックしたかをFallbackReport に記録， FeedbackExtractor に供する

η_e^eff = η_e^history                if history にあり
        = η_e^ref(tag)               if 参照値あり かつ sample_count >= min_reference_sample_count
        = config.fallback_eta        otherwise
"""

from dataclasses import dataclass, field

from ..domain.enums import ObservationType
from ..domain.graph import Edge, EdgeID, Graph
from ..domain.history import HistoryDigest
from ..domain.references import Reference
from .config import ResolvedConfig


@dataclass(frozen=True)
class ArcFlowSensitivity:
    edge_id: EdgeID
    eta: float


@dataclass(frozen=True)
class ReferenceSampleCount:
    attribute_tag: str
    sample_count: int


@dataclass(frozen=True)
class FallbackReport:
    used_reference_edges: tuple[EdgeID, ...] = ()  # η_e を参照値からフォールバックしたエッジ
    used_default_edges: tuple[EdgeID, ...] = ()  # 最終フォールバック値を使ったアーク
    reference_sample_counts: tuple[ReferenceSampleCount, ...] = ()  # 使った参照値の信頼度


@dataclass(frozen=True)
class SensitivityResult:
    arc_flow_sensitivity: tuple[ArcFlowSensitivity, ...] = ()
    fallback_usage: FallbackReport = field(default_factory=FallbackReport)


def resolve_arc_flow_sensitivity(
    graph: Graph,
    history_digest: HistoryDigest,
    references: Reference,
    config: ResolvedConfig,
) -> SensitivityResult:
    """有効ベクトルエッジごとに η_e を決定し，フォールバック利用を記録

    - 対象は有効なベクトル型（VECTOR）エッジのみ（η_e はベクトル型のみ）
    - 出力は enabled_edges() の順序（決定的）
    """
    sensitivities: list[ArcFlowSensitivity] = []
    used_reference_edges: list[EdgeID] = []
    used_default_edges: list[EdgeID] = []
    reference_sample_counts: dict[str, int] = {}

    for edge in graph.enabled_edges():
        if edge.observation_type != ObservationType.VECTOR:
            continue

        eta, source, tag, sample_count = _resolve_eta(edge, history_digest, references, config)
        sensitivities.append(ArcFlowSensitivity(edge_id=edge.edge_id, eta=eta))

        if source == _SOURCE_REFERENCE:
            used_reference_edges.append(edge.edge_id)
            if tag is not None and tag not in reference_sample_counts:
                reference_sample_counts[tag] = sample_count
        elif source == _SOURCE_FALLBACK:
            used_default_edges.append(edge.edge_id)
        # _SOURCE_HISTORY は一次ソースのためフォールバック記録対象外

    fallback_usage = FallbackReport(
        used_reference_edges=tuple(used_reference_edges),
        used_default_edges=tuple(used_default_edges),
        reference_sample_counts=tuple(
            ReferenceSampleCount(attribute_tag=tag, sample_count=count)
            for tag, count in reference_sample_counts.items()
        ),
    )
    return SensitivityResult(
        arc_flow_sensitivity=tuple(sensitivities),
        fallback_usage=fallback_usage,
    )


_SOURCE_HISTORY = "history"
_SOURCE_REFERENCE = "reference"
_SOURCE_FALLBACK = "fallback"


def _resolve_eta(
    edge: Edge,
    history_digest: HistoryDigest,
    references: Reference,
    config: ResolvedConfig,
) -> tuple[float, str, str | None, int]:
    """1 エッジの η_e をフォールバック階層で解決する

    戻り値は (eta, source, 参照に使った tag, その sample_count)
    """
    # 1. 履歴の flow_sensitivity_eta
    stat = history_digest.stat_of(edge.edge_id)
    if stat is not None and stat.flow_sensitivity_eta is not None:
        return stat.flow_sensitivity_eta, _SOURCE_HISTORY, None, 0

    # 2. 参照値（edge.attribute_tags の順で最初に一致したもの。K-匿名性しきい値を満たす場合のみ）
    for tag in edge.attribute_tags:
        ref = references.tag_reference_of(tag)
        if ref is None or ref.eta_typical is None:
            continue
        if ref.sample_count < config.min_reference_sample_count:
            continue
        return ref.eta_typical, _SOURCE_REFERENCE, tag, ref.sample_count

    # 3. 最終フォールバック
    return config.fallback_eta, _SOURCE_FALLBACK, None, 0
