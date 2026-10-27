"""Instantaneous gravity bounds, paired momentum exchange and work accounting."""
from dataclasses import FrozenInstanceError, replace
import math

import numpy as np
import pytest

from collision_outcomes import SphereState, collision_budget
from debris import summarize_debris
from debris_gravity import estimate_gravity, gravity_kick
from units import G_SI


def fragments():
    return tuple(SphereState(m, 2e5 * (m / 1e20)**(1 / 3), position, velocity, (1e24, 2e24, 3e24), 1e21)
                 for m, position, velocity in (
                     (1e20, (-2e6, 0, 0), (25, 15, 0)),
                     (2e20, (1e6, 2e6, 0), (-5, 15, 2)),
                     (3e20, (0, -1e6, 1e6), (0, -10, -1))))


def external_body():
    return SphereState(1e22, 1e6, (1e9, 3e8, -2e8), (-50, 10, 20))


def kick(cloud, body, duration=1000, **options):
    limits = dict(max_relative_force_error=.001, max_tidal_velocity_change_m_s=1e-4)
    limits.update(options)
    return gravity_kick(cloud, body, duration, **limits)


def exact_field(states, body, centre):
    forces, potentials, torques = [], [], []
    for s in states:
        delta = np.subtract(body.position_m, s.position_m)
        distance = np.linalg.norm(delta)
        force = G_SI * s.mass_kg * body.mass_kg * delta / distance**3
        forces.append(force)
        potentials.append(-G_SI * s.mass_kg * body.mass_kg / distance)
        torques.append(np.cross(np.subtract(s.position_m, centre), force))
    return np.sum(forces, axis=0), math.fsum(potentials), np.sum(torques, axis=0), forces


@pytest.mark.parametrize('direction', [(1, 0, 0), (0, 1, 1), (1, -2, 3)])
def test_force_potential_and_tidal_bounds_against_resolved_fragments(direction):
    states = fragments()
    cloud = summarize_debris(states)
    body = replace(external_body(), position_m=tuple(1e8 * x for x in direction))
    estimated = estimate_gravity(cloud, body)
    force, potential, torque, forces = exact_field(states, body, cloud.centre_m)
    assert np.linalg.norm(force - estimated.force_on_reservoir_n) <= estimated.force_error_bound_n
    assert abs(potential - estimated.potential_j) <= estimated.potential_error_bound_j
    assert np.linalg.norm(torque) <= estimated.tidal_torque_bound_nm
    bulk_acceleration = np.array(estimated.force_on_reservoir_n) / cloud.mass_kg
    for state, f in zip(states, forces, strict=True):
        assert np.linalg.norm(f / state.mass_kg - bulk_acceleration) <= estimated.tidal_acceleration_bound_m_s2


def test_monopole_force_converges_quadratically_with_cloud_distance():
    states = fragments()
    cloud = summarize_debris(states)
    errors = []
    for distance in (1e8, 2e8, 4e8):
        body = replace(external_body(), position_m=(distance, 0, 0))
        estimate = estimate_gravity(cloud, body)
        exact, _, _, _ = exact_field(states, body, cloud.centre_m)
        errors.append(np.linalg.norm(np.subtract(estimate.force_on_reservoir_n, exact)) / np.linalg.norm(exact))
    assert errors[0] / errors[1] == pytest.approx(4, rel=.1)
    assert errors[1] / errors[2] == pytest.approx(4, rel=.1)


def test_single_spherical_fragment_has_exact_monopole_interaction():
    state, body = fragments()[0], external_body()
    estimate = estimate_gravity(summarize_debris([state]), body)
    delta = np.subtract(body.position_m, state.position_m)
    expected = G_SI * state.mass_kg * body.mass_kg * delta / np.linalg.norm(delta)**3
    np.testing.assert_allclose(estimate.force_on_reservoir_n, expected, rtol=1e-12)


def test_kick_preserves_momentum_and_angular_momentum_and_accounts_for_work():
    states = fragments()
    # Store the stationary body directly in the audit frame so a tiny recoil is
    # not quantized by adding it to a large absolute orbital velocity.
    body = replace(external_body(), velocity_m_s=(0, 0, 0))
    cloud = summarize_debris(states)
    result = kick(cloud, body)
    origin, frame = cloud.centre_m, body.velocity_m_s
    options = dict(origin_m=origin, frame_velocity_m_s=frame)
    before = (cloud.budget(**options), collision_budget([body], **options))
    after = (result.reservoir.budget(**options), collision_budget([result.body], **options))
    for attribute in ('momentum_kg_m_s', 'angular_momentum_kg_m2_s'):
        initial = np.sum([getattr(b, attribute) for b in before], axis=0)
        final = np.sum([getattr(b, attribute) for b in after], axis=0)
        scale = sum(np.linalg.norm(getattr(b, attribute)) for b in (*before, *after))
        np.testing.assert_allclose(final, initial, rtol=0, atol=1e-12 * scale)
    before_energy = math.fsum(b.energy_j for b in before)
    after_energy = math.fsum(b.energy_j for b in after)
    scale = sum(abs(b.translational_energy_j) + abs(b.self_binding_j) for b in (*before, *after))
    assert abs((after_energy - before_energy) - result.kinetic_work_j) < 1e-12 * scale
    assert replace(result.reservoir, velocity_m_s=cloud.velocity_m_s) == cloud
    assert replace(result.body, velocity_m_s=body.velocity_m_s) == body
    np.testing.assert_allclose(result.impulse_on_reservoir_kg_m_s,
                               np.array(result.estimate.force_on_reservoir_n) * 1000, rtol=1e-12)
    # Compare a fully resolved frozen-position kick, not a trajectory advance.
    exact_force, _, torque, forces = exact_field(states, body, cloud.centre_m)
    assert np.linalg.norm(exact_force * 1000 - result.impulse_on_reservoir_kg_m_s) <= (
        result.estimate.force_error_bound_n * 1000)
    assert np.linalg.norm(torque) * 1000 <= result.omitted_tidal_angular_momentum_change_bound_kg_m2_s
    delta_v = np.subtract(result.reservoir.velocity_m_s, cloud.velocity_m_s)
    for state, force in zip(states, forces, strict=True):
        assert np.linalg.norm(force * 1000 / state.mass_kg - delta_v) <= result.omitted_tidal_velocity_change_bound_m_s
    with pytest.raises(FrozenInstanceError):
        result.kinetic_work_j = 0


def test_work_is_frame_invariant_and_kick_is_rotation_covariant():
    cloud, body = summarize_debris(fragments()), external_body()
    baseline = kick(cloud, body)
    rotation = np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]])
    shift, boost = np.array([1e10, -2e9, 3e8]), np.array([1e4, -2e4, 3e4])
    transformed = tuple(replace(s, position_m=rotation @ s.position_m + shift,
                                velocity_m_s=rotation @ s.velocity_m_s + boost,
                                spin_kg_m2_s=rotation @ s.spin_kg_m2_s) for s in fragments())
    transformed_body = replace(body, position_m=rotation @ body.position_m + shift,
                               velocity_m_s=rotation @ body.velocity_m_s + boost)
    result = kick(summarize_debris(transformed), transformed_body)
    np.testing.assert_allclose(result.impulse_on_reservoir_kg_m_s,
                               rotation @ baseline.impulse_on_reservoir_kg_m_s, rtol=1e-12)
    assert result.kinetic_work_j == pytest.approx(baseline.kinetic_work_j, rel=1e-12)


def test_zero_duration_and_negative_work_are_supported():
    cloud, body = summarize_debris(fragments()), external_body()
    zero = kick(cloud, body, 0, max_tidal_velocity_change_m_s=0)
    assert zero.reservoir == cloud and zero.body == body
    assert zero.kinetic_work_j == 0
    assert zero.impulse_on_reservoir_kg_m_s == (0, 0, 0)
    # An outgoing reservoir is decelerated: kinetic work is negative, not clamped.
    direction = np.subtract(body.position_m, cloud.centre_m)
    direction /= np.linalg.norm(direction)
    outgoing = replace(cloud, velocity_m_s=tuple(-100 * direction))
    assert kick(outgoing, replace(body, velocity_m_s=(0, 0, 0))).kinetic_work_j < 0


@pytest.mark.parametrize('options,message', [({'duration': -1}, 'duration'), ({'duration': math.inf}, 'duration'),
                                            ({'max_relative_force_error': 0}, 'force error limit'),
                                            ({'max_relative_force_error': 2}, 'force error limit'),
                                            ({'max_relative_force_error': math.nan}, 'force error limit'),
                                            ({'max_tidal_velocity_change_m_s': -1}, 'Tidal velocity limit'),
                                            ({'max_tidal_velocity_change_m_s': math.inf}, 'Tidal velocity limit')])
def test_invalid_accuracy_parameters(options, message):
    with pytest.raises(ValueError, match=message):
        kick(summarize_debris(fragments()), external_body(), **options)


def test_close_supports_and_insufficient_accuracy_are_rejected_without_mutation():
    cloud, body = summarize_debris(fragments()), external_body()
    with pytest.raises(ValueError, match='non-overlapping supports'):
        estimate_gravity(cloud, replace(body, position_m=cloud.centre_m))
    with pytest.raises(ValueError, match='force accuracy'):
        kick(cloud, body, max_relative_force_error=1e-10)
    with pytest.raises(ValueError, match='tidal velocity change'):
        kick(cloud, body, max_tidal_velocity_change_m_s=0)
    assert cloud == summarize_debris(fragments())
    assert body == external_body()


def test_nonfinite_estimates_and_work_are_rejected():
    tiny = SphereState(1e100, 1e-100, (0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError, match='estimate is outside numerical range'):
        estimate_gravity(summarize_debris([tiny]), replace(tiny, position_m=(1e-99, 0, 0)))
    cloud = replace(summarize_debris(fragments()), velocity_m_s=(1e300, 0, 0))
    with pytest.raises(ValueError, match='kick is outside numerical range'):
        kick(cloud, external_body())
