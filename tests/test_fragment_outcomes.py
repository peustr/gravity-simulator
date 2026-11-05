"""Conservation and feasibility of explicitly proposed remnant layouts."""
from dataclasses import FrozenInstanceError, replace
import math

import numpy as np
import pytest

from collision_outcomes import RemnantSpec, SphereState, allocate_remnants, collision_budget
from disruption import classify_contact
from impacts import Impact
from units import G_SI


def incoming():
    return (SphereState(1e20, 2e5, (-2e5, 0, 0), (1000, 50, 0), (2e26, 0, 0)),
            SphereState(1e20, 2e5, (2e5, 0, 0), (-1000, -50, 0), (0, 3e26, 0)))


def tetrahedron():
    radius = 2e5 * .5**(1 / 3)
    return tuple(RemnantSpec(5e19, radius, tuple(8e5 * x for x in point))
                 for point in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)))


def assert_conserved(before, after, *, origin=(0, 0, 0), frame=(0, 0, 0)):
    initial = collision_budget(before, origin_m=origin, frame_velocity_m_s=frame)
    final = collision_budget(after, origin_m=origin, frame_velocity_m_s=frame)
    assert final.mass_kg == pytest.approx(initial.mass_kg, rel=1e-12)
    states = (*before, *after)
    positions = [np.subtract(s.position_m, origin) for s in states]
    velocities = [np.subtract(s.velocity_m_s, frame) for s in states]
    # Scale absolute errors by physical terms before cancellation, so zero net
    # momentum/angular momentum does not demand impossible exact floating sums.
    p_scale = sum(s.mass_kg * np.linalg.norm(v) for s, v in zip(states, velocities, strict=True))
    l_scale = sum(s.mass_kg * np.linalg.norm(r) * np.linalg.norm(v) + math.hypot(*s.spin_kg_m2_s)
                  for s, r, v in zip(states, positions, velocities, strict=True))
    np.testing.assert_allclose(final.momentum_kg_m_s, initial.momentum_kg_m_s, rtol=0, atol=1e-12 * p_scale)
    np.testing.assert_allclose(final.angular_momentum_kg_m2_s, initial.angular_momentum_kg_m2_s,
                               rtol=0, atol=1e-12 * l_scale)
    e_scale = sum(abs(getattr(b, name)) for b in (initial, final)
                  for name in ('translational_energy_j', 'rotational_energy_j', 'self_binding_j',
                               'mutual_potential_j', 'internal_energy_j'))
    assert abs(final.energy_j - initial.energy_j) <= 1e-12 * e_scale
    before_position = sum((s.mass_kg * np.subtract(s.position_m, origin) for s in before), np.zeros(3))
    after_position = sum((s.mass_kg * np.subtract(s.position_m, origin) for s in after), np.zeros(3))
    x_scale = sum(s.mass_kg * np.linalg.norm(r) for s, r in zip(states, positions, strict=True))
    np.testing.assert_allclose(after_position, before_position, rtol=0, atol=1e-12 * x_scale)


@pytest.mark.parametrize('fraction', [0, .3, 1])
def test_four_fragments_close_all_budgets_and_separate(fraction):
    pair = incoming()
    result = allocate_remnants(*pair, tetrahedron(), expansion_fraction=fraction)
    assert len(result) == 4
    assert_conserved(pair, result)
    for i, a in enumerate(result):
        limit = a.inertia_kg_m2 * math.sqrt(G_SI * a.mass_kg / a.radius_m) / a.radius_m
        assert math.hypot(*a.spin_kg_m2_s) < limit
        for b in result[i + 1:]:
            r = np.subtract(b.position_m, a.position_m)
            v = np.subtract(b.velocity_m_s, a.velocity_m_s)
            assert np.linalg.norm(r) > a.radius_m + b.radius_m
            assert r @ v >= -1e-12 * np.linalg.norm(r) * np.linalg.norm(v)
    with pytest.raises(FrozenInstanceError):
        result[0].internal_energy_j = 0


def test_expansion_fraction_partitions_excess_energy_without_changing_spin():
    pair = incoming()
    cold = allocate_remnants(*pair, tetrahedron(), expansion_fraction=1)
    hot = allocate_remnants(*pair, tetrahedron(), expansion_fraction=0)
    mixed = allocate_remnants(*pair, tetrahedron(), expansion_fraction=.3)
    cold_budget, hot_budget, mixed_budget = map(collision_budget, (cold, hot, mixed))
    assert cold_budget.internal_energy_j == 0
    excess = cold_budget.translational_energy_j - hot_budget.translational_energy_j
    assert hot_budget.internal_energy_j == pytest.approx(excess, rel=1e-12)
    assert mixed_budget.internal_energy_j == pytest.approx(.7 * excess, rel=1e-12)
    assert mixed_budget.translational_energy_j - hot_budget.translational_energy_j == pytest.approx(.3 * excess, rel=1e-12)
    assert cold[0].spin_kg_m2_s == hot[0].spin_kg_m2_s == mixed[0].spin_kg_m2_s


def test_two_body_rotation_has_analytic_combined_inertia():
    a, b = incoming()
    a, b = replace(a, spin_kg_m2_s=(0, 0, 0)), replace(b, spin_kg_m2_s=(0, 0, 0))
    layout = (RemnantSpec(a.mass_kg, a.radius_m, a.position_m),
              RemnantSpec(b.mass_kg, b.radius_m, b.position_m))
    result = allocate_remnants(a, b, layout, expansion_fraction=0)
    # Two spheres at +/-R: Jz = 2*(2/5*m*R^2) + 2*m*R^2 = 14/5*m*R^2.
    expected_omega = -2e27 / ((14 / 5) * a.mass_kg * a.radius_m**2)
    assert result[0].velocity_m_s == pytest.approx((0, -a.radius_m * expected_omega, 0), rel=1e-12)
    assert result[0].spin_kg_m2_s == pytest.approx((0, 0, a.inertia_kg_m2 * expected_omega), rel=1e-12)
    assert_conserved((a, b), result)


def test_collinear_layout_can_carry_axial_angular_momentum_as_spin():
    a, b = incoming()
    a = replace(a, velocity_m_s=(1000, 0, 0), spin_kg_m2_s=(2e26, 0, 0))
    b = replace(b, velocity_m_s=(-1000, 0, 0), spin_kg_m2_s=(0, 0, 0))
    layout = (RemnantSpec(1e20, 2e5, (-8e5, 0, 0)), RemnantSpec(1e20, 2e5, (8e5, 0, 0)))
    result = allocate_remnants(a, b, layout, expansion_fraction=.5)
    for state in result:
        assert state.spin_kg_m2_s == pytest.approx((1e26, 0, 0), rel=1e-12)
    assert_conserved((a, b), result)


@pytest.mark.parametrize('impact_parameter,speed_ratio', [(.9, 1.5), (.7, 3)])
def test_classified_runner_and_debris_masses_are_preserved(impact_parameter, speed_ratio):
    mass = .5 * 5.9722e24
    radius = (mass / ((4 / 3) * math.pi * 5514))**(1 / 3)
    speed = speed_ratio * math.sqrt(2 * G_SI * mass / radius)
    velocity = (-speed * math.sqrt(1 - impact_parameter**2), speed * impact_parameter, 0)
    impact = Impact(mass, mass, radius, radius, (2 * radius, 0, 0), velocity, G_SI)
    classified = classify_contact(impact, unit_system='si', material='fluid_planets', body_types=(0, 0))
    assert classified.regime == 'hit_and_run'
    masses = (classified.largest_remnant_mass_kg, classified.runner_mass_kg)
    if classified.remaining_mass_kg > 0:
        masses += (classified.remaining_mass_kg / 2,) * 2
    # Prescribed spacing and debris split test budget compatibility only;
    # they do not calibrate ejecta or demonstrate a runner's escape.
    points = ((1, 1, 1), (-1, -1, 1), (1, -1, -1), (-1, 1, -1))
    layout = tuple(RemnantSpec(m, radius * (m / mass)**(1 / 3), tuple(4 * radius * x for x in point))
                   for m, point in zip(masses, points[:len(masses)], strict=True))
    pair = (SphereState(mass, radius, (0, 0, 0), (0, 0, 0)),
            SphereState(mass, radius, impact.relative_position, velocity))
    result = allocate_remnants(*pair, layout, expansion_fraction=.3)
    assert tuple(s.mass_kg for s in result) == masses
    assert_conserved(pair, result)


def test_unequal_layout_rotation_translation_boost_and_body_order():
    pair = incoming()
    layout = tuple(RemnantSpec(m, 2e5 * (m / 1e20)**(1 / 3), point)
                   for m, point in ((5e19, (-8e5, 0, 2e5)), (1e20, (2e5, 4e5, 0)),
                                    (5e19, (6e5, -4e5, -2e5))))
    baseline = allocate_remnants(*pair, layout, expansion_fraction=.5)
    assert_conserved(pair, baseline)
    reverse = allocate_remnants(*reversed(pair), tuple(reversed(layout)), expansion_fraction=.5)
    for original, actual in zip(baseline, reversed(reverse), strict=True):
        np.testing.assert_allclose(actual.velocity_m_s, original.velocity_m_s, rtol=1e-12)
        np.testing.assert_allclose(actual.spin_kg_m2_s, original.spin_kg_m2_s, rtol=1e-12)
        assert actual.internal_energy_j == pytest.approx(original.internal_energy_j, rel=1e-12)

    rotation = np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]])
    origin, boost = np.array([1e8, -1e7, 1e6]), np.array([1e4, -2e4, 3e4])
    moved = tuple(replace(s, position_m=rotation @ s.position_m + origin,
                          velocity_m_s=rotation @ s.velocity_m_s + boost,
                          spin_kg_m2_s=rotation @ s.spin_kg_m2_s) for s in pair)
    shifted_layout = tuple(replace(s, offset_m=rotation @ s.offset_m + [1e9, 1e9, 1e9]) for s in layout)
    result = allocate_remnants(*moved, shifted_layout, expansion_fraction=.5)
    assert_conserved(moved, result, origin=origin, frame=boost)
    for original, actual in zip(baseline, result, strict=True):
        np.testing.assert_allclose(actual.velocity_m_s - boost, rotation @ original.velocity_m_s, rtol=1e-12)
        np.testing.assert_allclose(actual.spin_kg_m2_s, rotation @ original.spin_kg_m2_s, rtol=1e-12)
        assert actual.internal_energy_j == pytest.approx(original.internal_energy_j, rel=1e-12)


def test_zero_excess_energy_and_thermally_supplied_fragmentation():
    pair = tuple(replace(s, velocity_m_s=(0, 0, 0), spin_kg_m2_s=(0, 0, 0)) for s in incoming())
    unchanged_layout = tuple(RemnantSpec(s.mass_kg, s.radius_m, s.position_m) for s in pair)
    assert allocate_remnants(*pair, unchanged_layout, expansion_fraction=1) == pair
    with pytest.raises(ValueError, match='Insufficient'):
        allocate_remnants(*pair, tetrahedron(), expansion_fraction=0)
    warm = (replace(pair[0], internal_energy_j=1e25), pair[1])
    result = allocate_remnants(*warm, tetrahedron(), expansion_fraction=.5)
    assert_conserved(warm, result)
    specific = [s.internal_energy_j / s.mass_kg for s in result]
    assert specific == pytest.approx([specific[0]] * 4, rel=1e-12)


@pytest.mark.parametrize('fraction', [-.1, 1.1, math.nan])
def test_invalid_energy_splits_are_rejected(fraction):
    with pytest.raises(ValueError, match='Expansion fraction'):
        allocate_remnants(*incoming(), tetrahedron(), expansion_fraction=fraction)


def test_invalid_layouts_are_rejected_without_changing_masses():
    pair, layout = incoming(), tetrahedron()
    for proposal in ((), layout[:1]):
        with pytest.raises(ValueError, match='at least two'):
            allocate_remnants(*pair, proposal, expansion_fraction=.5)
    bad_mass = (replace(layout[0], mass_kg=4e19), *layout[1:])
    with pytest.raises(ValueError, match='masses'):
        allocate_remnants(*pair, bad_mass, expansion_fraction=.5)
    bad_volume = (replace(layout[0], radius_m=1e5), *layout[1:])
    with pytest.raises(ValueError, match='volumes'):
        allocate_remnants(*pair, bad_volume, expansion_fraction=.5)
    overlapping = (replace(layout[0], offset_m=layout[1].offset_m), *layout[1:])
    with pytest.raises(ValueError, match='non-overlapping'):
        allocate_remnants(*pair, overlapping, expansion_fraction=.5)
    assert layout[0].mass_kg == 5e19


def test_separation_spin_and_inertia_exclusions():
    a, b = incoming()
    with pytest.raises(ValueError, match='surface contact'):
        allocate_remnants(a, replace(b, position_m=(1e6, 0, 0)), tetrahedron(), expansion_fraction=.5)
    with pytest.raises(ValueError, match='separating'):
        allocate_remnants(a, replace(b, velocity_m_s=(2000, 0, 0)), tetrahedron(), expansion_fraction=.5)
    layout = tuple(RemnantSpec(s.mass_kg, s.radius_m, s.position_m) for s in (a, b))
    fast_a, fast_b = replace(a, velocity_m_s=(1000, 5000, 0)), replace(b, velocity_m_s=(-1000, -5000, 0))
    with pytest.raises(ValueError, match='spin limit'):
        allocate_remnants(fast_a, fast_b, layout, expansion_fraction=.5)
    unresolved = tuple(replace(s, offset_m=tuple(x * 1e8 for x in s.offset_m)) for s in layout)
    with pytest.raises(ValueError, match='unresolved inertia'):
        allocate_remnants(a, b, unresolved, expansion_fraction=.5)


def test_specs_own_offsets_and_validate_spherical_properties():
    offset = [1, 2, 3]
    spec = RemnantSpec(1e20, 2e5, offset)
    offset[0] = 8
    assert spec.offset_m == (1, 2, 3)
    with pytest.raises(ValueError, match='positive'):
        RemnantSpec(-1, 2e5, (0, 0, 0))
