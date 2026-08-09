"""``resolve_arc_flow_sensitivity``（η_e 決定）のテスト"""

import pytest

from flow_control.domain import (
    ArcHistoryStat,
    CurrentDirection,
    DirectionConstraint,
    Edge,
    EdgeID,
    Graph,
    HistoryDigest,
    Node,
    NodeID,
    NodeKind,
    ObservationType,
    Reference,
    TagReference,
)
from flow_control.forecasting.config import ResolvedConfig
from flow_control.forecasting.sensitivity import resolve_arc_flow_sensitivity


def _node(node_id: str) -> Node:
    return Node(
        node_id=NodeID(node_id),
        kind=NodeKind.GOAL,
        is_boundary=False,
        enabled=True,
    )


def _edge(
    edge_id: str,
    *,
    attribute_tags: tuple[str, ...] = (),
    observation_type: ObservationType = ObservationType.VECTOR,
    enabled: bool = True,
) -> Edge:
    return Edge(
        edge_id=EdgeID(edge_id),
        endpoint_a=NodeID("a"),
        endpoint_b=NodeID("b"),
        direction_constraint=DirectionConstraint.BIDIRECTIONAL_PRIOR,
        current_direction=CurrentDirection.BIDIRECTIONAL,
        enabled=enabled,
        observation_type=observation_type,
        attribute_tags=attribute_tags,
    )


def _graph(*edges: Edge) -> Graph:
    return Graph(nodes=(_node("a"), _node("b")), edges=edges)


def _config(*, min_reference_sample_count: int = 5, fallback_eta: float = 2.0) -> ResolvedConfig:
    return ResolvedConfig(
        min_reference_sample_count=min_reference_sample_count,
        fallback_eta=fallback_eta,
    )


def _eta_of(result, edge_id: str) -> float:
    for s in result.arc_flow_sensitivity:
        if s.edge_id == EdgeID(edge_id):
            return s.eta
    raise AssertionError(f"sensitivity for {edge_id} not found")


def test_history_eta_is_primary() -> None:
    """履歴に flow_sensitivity_eta があれば使用し，フォールバック記録はしない"""
    graph = _graph(_edge("e1"))
    history = HistoryDigest(
        arc_stats=(ArcHistoryStat(edge_id=EdgeID("e1"), flow_sensitivity_eta=0.3),)
    )

    result = resolve_arc_flow_sensitivity(graph, history, Reference(), _config())

    assert _eta_of(result, "e1") == pytest.approx(0.3)
    assert result.fallback_usage.used_reference_edges == ()
    assert result.fallback_usage.used_default_edges == ()


def test_reference_eta_used_when_history_absent() -> None:
    """履歴が無く参照値が K しきい値を満たせば参照値を使い，記録する"""
    graph = _graph(_edge("e1", attribute_tags=("wide",)))
    references = Reference(
        by_attribute_tag=(TagReference(attribute_tag="wide", eta_typical=0.5, sample_count=10),)
    )

    result = resolve_arc_flow_sensitivity(
        graph, HistoryDigest(), references, _config(min_reference_sample_count=5)
    )

    assert _eta_of(result, "e1") == pytest.approx(0.5)
    assert result.fallback_usage.used_reference_edges == (EdgeID("e1"),)
    assert result.fallback_usage.used_default_edges == ()
    counts = result.fallback_usage.reference_sample_counts
    assert len(counts) == 1
    assert counts[0].attribute_tag == "wide"
    assert counts[0].sample_count == 10


def test_reference_skipped_below_sample_threshold() -> None:
    """参照値の sample_count が min 未満なら採用せず最終フォールバックへ"""
    graph = _graph(_edge("e1", attribute_tags=("wide",)))
    references = Reference(
        by_attribute_tag=(TagReference(attribute_tag="wide", eta_typical=0.5, sample_count=3),)
    )

    result = resolve_arc_flow_sensitivity(
        graph,
        HistoryDigest(),
        references,
        _config(min_reference_sample_count=5, fallback_eta=2.0),
    )

    assert _eta_of(result, "e1") == pytest.approx(2.0)
    assert result.fallback_usage.used_reference_edges == ()
    assert result.fallback_usage.used_default_edges == (EdgeID("e1"),)


def test_final_fallback_when_nothing_matches() -> None:
    """履歴も参照値も無ければ config.fallback_eta を使い used_default_edges に記録"""
    graph = _graph(_edge("e1"))

    result = resolve_arc_flow_sensitivity(
        graph, HistoryDigest(), Reference(), _config(fallback_eta=2.0)
    )

    assert _eta_of(result, "e1") == pytest.approx(2.0)
    assert result.fallback_usage.used_default_edges == (EdgeID("e1"),)


def test_scalar_edge_excluded() -> None:
    """スカラー型エッジは η_e の対象外（ベクトル型のみ）"""
    graph = _graph(_edge("e1", observation_type=ObservationType.SCALAR))

    result = resolve_arc_flow_sensitivity(graph, HistoryDigest(), Reference(), _config())

    assert result.arc_flow_sensitivity == ()


def test_first_matching_tag_is_used() -> None:
    """attribute_tags の順で最初に一致した参照値を使う"""
    graph = _graph(_edge("e1", attribute_tags=("narrow", "wide")))
    references = Reference(
        by_attribute_tag=(
            TagReference(attribute_tag="narrow", eta_typical=0.1, sample_count=10),
            TagReference(attribute_tag="wide", eta_typical=0.5, sample_count=10),
        )
    )

    result = resolve_arc_flow_sensitivity(
        graph, HistoryDigest(), references, _config(min_reference_sample_count=5)
    )

    assert _eta_of(result, "e1") == pytest.approx(0.1)  # narrow が先
    assert result.fallback_usage.reference_sample_counts[0].attribute_tag == "narrow"
