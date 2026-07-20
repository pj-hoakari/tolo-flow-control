"""機能2 の残留評価と Detour 不足ゲート（純関数）"""

import pytest

from flow_control.domain import EdgeID
from flow_control.optimization.model import MilpInputs
from flow_control.optimization.restriction import (
    assess_residual,
    evaluate_detour_gate,
)

_E_HOT = EdgeID("e_hot")
_E_SCALAR = EdgeID("e_scalar")
_E_D1 = EdgeID("e_d1")
_E_D2 = EdgeID("e_d2")

_ARC_KEYS = {
    _E_HOT: ("e_hot|A_TO_B",),
    _E_SCALAR: ("e_scalar|A_TO_B",),
    _E_D1: ("e_d1|A_TO_B",),
    _E_D2: ("e_d2|A_TO_B",),
}


def _inputs(**overrides) -> MilpInputs:
    base = dict(
        s_obs={_E_HOT: 30.0, _E_D1: 10.0, _E_D2: 10.0},
        s_bar={_E_HOT: 10.0, _E_D1: 10.0, _E_D2: 10.0},
        eta={_E_HOT: 0.5, _E_D1: 0.5, _E_D2: 0.5},
        c_e={},
        capacity_hint={_E_SCALAR: 50.0},
        sigma={_E_SCALAR: 10.0},
        scalar_edges=frozenset({_E_SCALAR}),
        edge_danger_capacity={},
        node_danger_capacity={},
        big_m=1000.0,
        epsilon=1e-3,
        epsilon_0=1e-6,
    )
    base.update(overrides)
    return MilpInputs(**base)


def test_residual_fires_on_tau_exceeded():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=3.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.tau_exceeded
    assert not got.puncture_residual and not got.undrainable_present


def test_residual_quiet_when_below_threshold():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=1.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.residual


def test_residual_fires_on_puncture_overflow():
    # スカラー上限 max(0, 50-10)=40 に対しフロー 45 → パンク残留
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_SCALAR}),
        tau_zone=0.0,
        flow={"e_scalar|A_TO_B": 45.0},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.puncture_residual
    assert got.puncture_edges == (_E_SCALAR,)


def test_residual_ignores_puncture_within_limit():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_SCALAR}),
        tau_zone=0.0,
        flow={"e_scalar|A_TO_B": 35.0},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.residual


def test_residual_fires_on_undrainable_in_zone():
    got = assess_residual(
        _inputs(),
        zone_edges=frozenset({_E_HOT}),
        tau_zone=0.0,
        flow={},
        arc_keys_of_edge=_ARC_KEYS,
        undrainable=frozenset({_E_HOT}),
        tau_danger_threshold=2.0,
    )
    assert got.residual and got.undrainable_present
    assert got.undrainable_edges == (_E_HOT,)


def test_gate_structural_shortage_when_k_small():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1}),
        k_effective=1,
        flow={"e_d1|A_TO_B": 20.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.structural_shortage


def test_gate_unused_when_detour_carries_no_flow():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={},  # どちらの迂回路も使われていない
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.unused
    assert got.used_ratio == pytest.approx(0.0)


def test_gate_sufficient_when_detour_used_and_safe():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        # 残留停滞 10-0.5*18=1 → 正規化 0.1 で閾値以下
        flow={"e_d1|A_TO_B": 18.0, "e_d2|A_TO_B": 18.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=2.0,
    )
    assert not got.insufficient
    assert got.used_ratio == pytest.approx(1.0)


def test_gate_endangered_when_detour_stagnates():
    # 迂回路は使われているが残留停滞が閾値超（10-0.5*2=9 → 0.9 ... 閾値 0.5 で超過）
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 2.0, "e_d2|A_TO_B": 2.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=0.5,
    )
    assert got.insufficient and got.detour_endangered
    assert set(got.endangered_edges) == {_E_D1, _E_D2}


def test_gate_endangered_when_detour_is_triggered_or_watched():
    got = evaluate_detour_gate(
        _inputs(),
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 18.0, "e_d2|A_TO_B": 18.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset({_E_D1}),
        watched_edges=frozenset({_E_D2}),
        tau_danger_threshold=2.0,
    )
    assert got.insufficient and got.detour_endangered
    assert set(got.endangered_edges) == {_E_D1, _E_D2}


def test_gate_skips_stagnation_term_without_observation():
    # 停滞観測のない迂回エッジは正規化停滞を評価しない（幻の停滞を作らない）
    inputs = _inputs(s_obs={_E_HOT: 30.0}, s_bar={_E_HOT: 10.0}, eta={_E_HOT: 0.5})
    got = evaluate_detour_gate(
        inputs,
        detour_edges=frozenset({_E_D1, _E_D2}),
        k_effective=2,
        flow={"e_d1|A_TO_B": 5.0, "e_d2|A_TO_B": 5.0},
        arc_keys_of_edge=_ARC_KEYS,
        triggered_edges=frozenset(),
        watched_edges=frozenset(),
        tau_danger_threshold=0.1,
    )
    assert not got.detour_endangered
    assert not got.insufficient
