"""Unresolved material retains its inventory independently of particle capacity."""
from dataclasses import FrozenInstanceError, replace
import gc
import math
import weakref

import numpy as np
import pytest

from collision_models import construct_collision
from collision_outcomes import RemnantSpec, SphereState, collision_budget
from debris import partition_debris, summarize_debris
from disruption import estimate_head_on_disruption
from units import G_SI
from test_collision_models import classify, encounter, layout_for, rocky_pair


def assert_inventory(actual, expected, states, *, origin=(0, 0, 0), velocity=(0, 0, 0)):
    assert actual.mass_kg == pytest.approx(expected.mass_kg, rel=1e-12)
    p_scale = sum(s.mass_kg * math.dist(s.velocity_m_s, velocity) for s in states)
    l_scale = sum(s.mass_kg * math.dist(s.position_m, origin) * math.dist(s.velocity_m_s, velocity)
                  + math.hypot(*s.spin_kg_m2_s) for s in states)
    np.testing.assert_allclose(actual.momentum_kg_m_s, expected.momentum_kg_m_s, rtol=0, atol=1e-12 * p_scale)
    np.testing.assert_allclose(actual.angular_momentum_kg_m2_s, expected.angular_momentum_kg_m2_s,
                               rtol=0, atol=1e-12 * l_scale)
    components = ('translational_energy_j', 'rotational_energy_j', 'self_binding_j',
                  'mutual_potential_j', 'internal_energy_j')
    for name in components:
        assert getattr(actual, name) == pytest.approx(getattr(expected, name), rel=1e-12, abs=0)
    scale = sum(abs(getattr(expected, name)) for name in components)
    assert abs(actual.energy_j - expected.energy_j) <= 1e-12 * scale


def opposite_spins():
    return (SphereState(1e20, 2e5, (-1e6, 0, 0), (0, -100, 0), (0, 0, 1e27), 2e22),
            SphereState(1e20, 2e5, (1e6, 0, 0), (0, 100, 0), (0, 0, -1e27), 3e22))


def test_reservoir_keeps_orbital_spin_dispersion_and_binding_separate():
    states = opposite_spins()
    reservoir = summarize_debris(states)
    assert reservoir.fragment_count == 2
    assert reservoir.mass_kg == 2e20
    assert reservoir.volume_m3 == pytest.approx(2 * (4 / 3) * math.pi * (2e5)**3, rel=1e-12)
    assert reservoir.centre_m == reservoir.velocity_m_s == (0, 0, 0)
    assert reservoir.extent_m == 1.2e6
    assert reservoir.spin_kg_m2_s == (0, 0, 0)
    assert reservoir.orbital_angular_momentum_kg_m2_s == pytest.approx((0, 0, 2e28), rel=1e-12)
    assert reservoir.dispersion_energy_j == pytest.approx(1e24, rel=1e-12)
    assert reservoir.rotational_energy_j == pytest.approx(6.25e23, rel=1e-12)
    assert reservoir.self_binding_j == pytest.approx(-2 * .6 * G_SI * 1e40 / 2e5, rel=1e-12)
    assert reservoir.mutual_potential_j == pytest.approx(-G_SI * 1e40 / 2e6, rel=1e-12)
    assert reservoir.internal_energy_j == 5e22
    assert_inventory(reservoir.budget(), collision_budget(states), states)
    with pytest.raises(FrozenInstanceError):
        reservoir.mass_kg = 0


def test_single_fragment_has_no_unresolved_orbital_motion_or_dispersion():
    state = opposite_spins()[0]
    reservoir = summarize_debris([state])
    assert reservoir.fragment_count == 1
    assert reservoir.centre_m == state.position_m
    assert reservoir.velocity_m_s == state.velocity_m_s
    assert reservoir.extent_m == state.radius_m
    assert reservoir.orbital_angular_momentum_kg_m2_s == (0, 0, 0)
    assert reservoir.dispersion_energy_j == reservoir.mutual_potential_j == 0
    assert_inventory(reservoir.budget(), collision_budget([state]), [state])


def test_reservoir_rotation_translation_boost_and_audit_frame():
    states = (*opposite_spins(), SphereState(3e20, 2.5e5, (0, 3e6, 0), (80, 25, 0)))
    baseline = summarize_debris(states)
    rotation = np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]])
    shift, boost = np.array([1e8, -2e7, 3e6]), np.array([1e4, -2e4, 3e4])
    moved = tuple(replace(s, position_m=rotation @ s.position_m + shift,
                          velocity_m_s=rotation @ s.velocity_m_s + boost,
                          spin_kg_m2_s=rotation @ s.spin_kg_m2_s) for s in states)
    actual = summarize_debris(moved)
    assert actual.dispersion_energy_j == pytest.approx(baseline.dispersion_energy_j, rel=1e-12)
    assert actual.extent_m == pytest.approx(baseline.extent_m, rel=1e-12)
    np.testing.assert_allclose(actual.orbital_angular_momentum_kg_m2_s,
                               rotation @ baseline.orbital_angular_momentum_kg_m2_s, rtol=1e-12, atol=0)
    for origin, velocity in (((0, 0, 0), (0, 0, 0)), (shift, boost), ((-2e7, 1e6, 3e5), (1000, 30, 100))):
        options = dict(origin_m=origin, frame_velocity_m_s=velocity)
        assert_inventory(actual.budget(**options), collision_budget(moved, **options), moved,
                         origin=origin, velocity=velocity)


def constructed(regime):
    if regime in ('merging', 'graze_and_merge', 'hit_and_run', 'eroded_runner'):
        b, speed = {'merging': (0, .5), 'graze_and_merge': (.6, 1),
                    'hit_and_run': (.9, 1.5), 'eroded_runner': (.7, 3)}[regime]
        pair, material = rocky_pair(b, speed), 'fluid_planets'
    else:
        ratio = {'partial_accretion': .3, 'erosion': .7, 'disruption': 1.2, 'supercatastrophic_disruption': 2}[regime]
        target = 4.2e15
        threshold = estimate_head_on_disruption(target, target / 4, 0,
                                               material='planetesimals').disruption_energy_j_kg
        pair, material = encounter(speed=math.sqrt(2 * ratio * threshold / .16)), 'planetesimals'
    classification = classify(pair, material)
    options = {} if regime in ('merging', 'graze_and_merge') else {
        'layout': layout_for(pair, classification), 'expansion_fraction': 1}
    return construct_collision(*pair, material=material, body_types=(0, 0), **options)


@pytest.mark.parametrize('regime', ['merging', 'graze_and_merge', 'hit_and_run', 'eroded_runner',
                                   'partial_accretion', 'erosion', 'disruption', 'supercatastrophic_disruption'])
def test_capacity_cannot_change_regime_primary_states_or_inventory(regime):
    outcome = constructed(regime)
    expected = collision_budget(outcome.remnants)
    primary_count = 1 + int(outcome.classification.runner_mass_kg > 0)
    debris = outcome.remnants[primary_count:]
    for capacity in (0, 1, 2, len(debris), len(debris) + 10):
        partition = partition_debris(outcome, max_explicit_debris=capacity)
        assert partition.classification is outcome.classification
        assert partition.escape_certificate == outcome.escape_certificate
        assert partition.primaries == outcome.remnants[:primary_count]
        assert len(partition.explicit_debris) == min(capacity, len(debris))
        assert_inventory(partition.budget(), expected, outcome.remnants)
        unresolved_count = 0 if partition.reservoir is None else partition.reservoir.fragment_count
        assert len(partition.explicit_debris) + unresolved_count == len(debris)
        volume = sum((4 / 3) * math.pi * s.radius_m**3 for s in (*partition.primaries, *partition.explicit_debris))
        volume += 0 if partition.reservoir is None else partition.reservoir.volume_m3
        assert volume == pytest.approx(sum((4 / 3) * math.pi * s.radius_m**3 for s in outcome.remnants), rel=1e-12)


def test_cross_potential_is_counted_exactly_once_and_not_approximated_by_a_point():
    outcome = constructed('supercatastrophic_disruption')
    partition = partition_debris(outcome, max_explicit_debris=2)
    explicit = (*partition.primaries, *partition.explicit_debris)
    unresolved = tuple(s for s in outcome.remnants if s not in explicit)
    cross = math.fsum(-G_SI * a.mass_kg * b.mass_kg / math.dist(a.position_m, b.position_m)
                      for a in explicit for b in unresolved)
    assert partition.cross_potential_j == pytest.approx(cross, rel=1e-12)
    assert partition.budget().mutual_potential_j == pytest.approx(
        collision_budget(explicit).mutual_potential_j + collision_budget(unresolved).mutual_potential_j + cross,
        rel=1e-12)
    # Moving the audit frame changes no pair potential, and all other inventories transform together.
    options = dict(origin_m=(1e7, -2e6, 3e5), frame_velocity_m_s=(800, 30, 0))
    assert_inventory(partition.budget(**options), collision_budget(outcome.remnants, **options), outcome.remnants,
                     origin=options['origin_m'], velocity=options['frame_velocity_m_s'])


def test_capacity_prefers_larger_fragments_with_stable_ties():
    pair = rocky_pair(.7, 3)
    classification = classify(pair, 'fluid_planets')
    a, b = pair
    masses = [classification.largest_remnant_mass_kg, classification.runner_mass_kg,
              classification.remaining_mass_kg * .2, classification.remaining_mass_kg * .4,
              classification.remaining_mass_kg * .4]
    layout = tuple(RemnantSpec(m, a.radius_m * (m / a.mass_kg)**(1 / 3),
                              (20 * a.radius_m * math.cos(2 * math.pi * i / 5),
                               20 * a.radius_m * math.sin(2 * math.pi * i / 5), 0))
                   for i, m in enumerate(masses))
    outcome = construct_collision(a, b, material='fluid_planets', body_types=(0, 0),
                                  layout=layout, expansion_fraction=1)
    for capacity, indices in ((1, [3]), (2, [3, 4]), (3, [3, 4, 2])):
        partition = partition_debris(outcome, max_explicit_debris=capacity)
        assert partition.explicit_debris == tuple(outcome.remnants[i] for i in indices)
        assert_inventory(partition.budget(), collision_budget(outcome.remnants), outcome.remnants)


def test_partition_does_not_retain_hidden_fragment_states():
    outcome = constructed('supercatastrophic_disruption')
    references = [weakref.ref(s) for s in outcome.remnants[1:]]
    partition = partition_debris(outcome, max_explicit_debris=0)
    del outcome
    gc.collect()
    assert all(reference() is None for reference in references)
    assert partition.reservoir.fragment_count == len(references)
    with pytest.raises(FrozenInstanceError):
        partition.reservoir = None


@pytest.mark.parametrize('capacity', [-1, 1.5, True, None])
def test_invalid_capacity_is_rejected(capacity):
    with pytest.raises(ValueError, match='nonnegative integer'):
        partition_debris(constructed('merging'), max_explicit_debris=capacity)


def test_invalid_reservoirs_and_audit_frames_are_rejected():
    with pytest.raises(ValueError, match='at least one'):
        summarize_debris([])
    state = opposite_spins()[0]
    with pytest.raises(ValueError, match='non-overlapping'):
        summarize_debris([state, state])
    with pytest.raises(ValueError, match='numerical range'):
        summarize_debris([SphereState(1e-104, 1e103, (0, 0, 0), (0, 0, 0))])
    with pytest.raises(ValueError, match='finite components'):
        summarize_debris([state]).budget(frame_velocity_m_s=(math.nan, 0, 0))
    with pytest.raises(ValueError, match='numerical range'):
        summarize_debris([state]).budget(frame_velocity_m_s=(1e200, 0, 0))
