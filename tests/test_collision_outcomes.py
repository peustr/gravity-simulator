"""Independent budgets and feasibility checks for isolated spherical mergers."""
from dataclasses import FrozenInstanceError, replace
import math

import numpy as np
import pytest

from collision_outcomes import SphereState, collision_budget, merge_spheres
from units import G_SI


def pair():
    return (SphereState(1e20, 2e5, (-2e5, 0, 0), (100, 50, 0)),
            SphereState(1e20, 2e5, (2e5, 0, 0), (-100, -50, 0)))


def assert_closed(before, after):
    assert after.mass_kg == pytest.approx(before.mass_kg, rel=1e-14)
    np.testing.assert_allclose(after.momentum_kg_m_s, before.momentum_kg_m_s, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(after.angular_momentum_kg_m2_s, before.angular_momentum_kg_m2_s,
                               rtol=1e-12, atol=1e-12)
    assert after.energy_j == pytest.approx(before.energy_j, rel=1e-12)


def test_stationary_equal_spheres_release_analytic_binding_energy():
    a, b = (replace(p, velocity_m_s=(0, 0, 0)) for p in pair())
    remnant = merge_spheres(a, b)
    scale = G_SI * a.mass_kg**2 / a.radius_m
    # Initial: two self-binding terms (-6/5) plus contact potential (-1/2).
    # Final: one uniform sphere of mass 2m and radius cube_root(2)*r.
    expected_release = (12 / (5 * 2**(1 / 3)) - 17 / 10) * scale
    assert remnant.internal_energy_j == pytest.approx(expected_release, rel=1e-13)
    assert remnant.radius_m == pytest.approx(a.radius_m * 2**(1 / 3), rel=1e-14)
    assert remnant.position_m == remnant.velocity_m_s == remnant.spin_kg_m2_s == (0, 0, 0)
    assert collision_budget((a, b)).energy_j == pytest.approx(-1.7 * scale, rel=1e-14)
    assert_closed(collision_budget((a, b)), collision_budget((remnant,)))


def test_oblique_merger_retains_orbital_and_incoming_spin_angular_momentum():
    a, b = pair()
    a = replace(a, spin_kg_m2_s=(2e26, 0, 0), internal_energy_j=5e23)
    b = replace(b, spin_kg_m2_s=(0, 3e26, 0), internal_energy_j=7e23)
    remnant = merge_spheres(a, b)
    # mu*(r cross v) = (m/2)*(4e5,0,0) cross (-200,-100,0).
    assert remnant.spin_kg_m2_s == (2e26, 3e26, -2e27)
    assert remnant.inertia_kg_m2 == pytest.approx(.4 * 2e20 * remnant.radius_m**2, rel=1e-14)
    assert remnant.internal_energy_j > a.internal_energy_j + b.internal_energy_j
    before, after = collision_budget((a, b)), collision_budget((remnant,))
    assert before.rotational_energy_j > 0 and after.rotational_energy_j > 0
    assert before.mutual_potential_j < 0 and after.mutual_potential_j == 0
    assert_closed(before, after)
    assert merge_spheres(b, a) == remnant


def test_inertial_frame_changes_do_not_change_internal_energy_or_relative_spin():
    a, b = pair()
    # A dyadic mass fraction keeps the COM exactly representable after this
    # large boost, isolating invariance from absolute-coordinate quantisation.
    b = replace(b, mass_kg=3e20, velocity_m_s=(-70, -30, 10))
    remnant = merge_spheres(a, b)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    origin = np.array([1e9, -1e8, 1e7])
    boost = np.array([1e7, -1e6, 1e6])

    def transform(body):
        return replace(body, position_m=rotation @ body.position_m + origin,
                       velocity_m_s=rotation @ body.velocity_m_s + boost,
                       spin_kg_m2_s=rotation @ body.spin_kg_m2_s)

    moved = tuple(transform(p) for p in (a, b))
    merged = merge_spheres(*moved)
    assert merged.internal_energy_j == pytest.approx(remnant.internal_energy_j, rel=1e-12)
    np.testing.assert_allclose(merged.spin_kg_m2_s, rotation @ remnant.spin_kg_m2_s, rtol=1e-12)
    np.testing.assert_allclose(merged.position_m, transform(remnant).position_m, rtol=1e-15)
    np.testing.assert_allclose(merged.velocity_m_s, transform(remnant).velocity_m_s, rtol=1e-15)
    # Audit in the nearby inertial frame so a huge bulk kinetic energy cannot
    # hide errors in the much smaller collision energy.
    before = collision_budget(moved, origin_m=origin, frame_velocity_m_s=boost)
    after = collision_budget((merged,), origin_m=origin, frame_velocity_m_s=boost)
    assert_closed(before, after)


def test_energy_deficit_is_rejected_and_existing_internal_energy_can_supply_it():
    a, _ = pair()
    a = replace(a, position_m=(0, 0, 0), velocity_m_s=(0, 0, 0))
    b = SphereState(1e18, 2e6, (2.2e6, 0, 0), (0, 0, 0))
    # Expanding a compact massive sphere into a much larger mixed volume costs
    # binding energy. There must be a source for that energy, not negative heat.
    with pytest.raises(ValueError, match='Insufficient'):
        merge_spheres(a, b)
    warm = replace(a, internal_energy_j=10 * abs(a.self_binding_j))
    remnant = merge_spheres(warm, b)
    assert_closed(collision_budget((warm, b)), collision_budget((remnant,)))


def test_spin_limit_is_checked_on_both_sides_of_surface_retention_boundary():
    a, b = pair()
    radius = a.radius_m * 2**(1 / 3)
    mass = a.mass_kg + b.mass_kg
    inertia = .4 * mass * radius**2
    limit = inertia * math.sqrt(G_SI * mass / radius**3)
    mu = mass / 4
    tangential_speed = limit / (mu * (a.radius_m + b.radius_m))
    a = replace(a, velocity_m_s=(0, 0, 0))
    for factor in (1 - 1e-8, 1 + 1e-8):
        candidate = replace(b, velocity_m_s=(-200, factor * tangential_speed, 0))
        if factor < 1:
            remnant = merge_spheres(a, candidate)
            assert math.hypot(*remnant.spin_kg_m2_s) == pytest.approx(factor * limit, rel=1e-13)
        else:
            with pytest.raises(ValueError, match='spin limit'):
                merge_spheres(a, candidate)


def test_geometry_exclusions_and_empty_inventory():
    a, b = pair()
    for position in ((1e5, 0, 0), (3e5, 0, 0)):
        with pytest.raises(ValueError, match='surface contact'):
            merge_spheres(a, replace(b, position_m=position))
    with pytest.raises(ValueError, match='non-overlapping'):
        collision_budget((a, replace(b, position_m=a.position_m)))
    with pytest.raises(ValueError, match='separating'):
        merge_spheres(a, replace(b, velocity_m_s=(200, 0, 0)))
    assert collision_budget(()).mass_kg == collision_budget(()).energy_j == 0
    assert collision_budget(()).angular_momentum_kg_m2_s == (0, 0, 0)


def test_states_own_vectors_and_are_immutable():
    position, velocity, spin = [1, 2, 3], [4, 5, 6], [7, 8, 9]
    body = SphereState(10, 2, position, velocity, spin)
    position[0] = velocity[0] = spin[0] = 100
    assert body.position_m == (1, 2, 3) and body.velocity_m_s == (4, 5, 6)
    assert body.spin_kg_m2_s == (7, 8, 9)
    with pytest.raises(FrozenInstanceError):
        body.mass_kg = 1


@pytest.mark.parametrize('changes,message', [
    ({'mass_kg': 0}, 'positive'), ({'radius_m': -1}, 'positive'),
    ({'internal_energy_j': -1}, 'nonnegative'),
    ({'internal_energy_j': math.inf}, 'finite'), ({'radius_m': math.nan}, 'finite'),
    ({'position_m': (1, 2)}, 'three finite'), ({'velocity_m_s': (0, math.inf, 0)}, 'three finite'),
    ({'mass_kg': 1e-300, 'radius_m': 1e-300}, 'inertia'),
    ({'mass_kg': 1e300, 'radius_m': 1e300}, 'inertia'),
    ({'mass_kg': 1e300, 'radius_m': 1}, 'Sphere energy'),
    ({'spin_kg_m2_s': (1e300, 0, 0)}, 'Sphere energy'),
])
def test_invalid_spherical_states(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(pair()[0], **changes)


def test_nonfinite_computed_energy_is_rejected():
    a, b = pair()
    a = replace(a, velocity_m_s=(0, 0, 0))
    b = replace(b, velocity_m_s=(-1e200, 0, 0))
    with pytest.raises(ValueError, match='non-finite energy'):
        merge_spheres(a, b)
    with pytest.raises(ValueError, match='budget is outside'):
        collision_budget((a, b))
