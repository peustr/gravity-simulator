"""Homologous transport, changing potential, and resolved trajectory references."""
from dataclasses import replace
import math

import numpy as np
import pytest
import rebound

from collision_outcomes import SphereState, collision_budget
from debris_gravity import estimate_gravity
from debris_transport import advance_transport, start_transport
from units import G_SI


LIMITS = dict(max_relative_force_error=.01, max_omitted_velocity_change_m_s=1,
              max_relative_energy_error=.01)


def initial_cloud(rate=1e-4):
    states = tuple(SphereState(1e16, 1000, (0, sign * 5e4, 0), (0, sign * 5e4 * rate, 0),
                               (1e17, 0, 0), 1e12) for sign in (-1, 1))
    body = SphereState(1e20, 1e5, (1e9, 0, 0), (0, math.sqrt(G_SI * 1.0002e20 / 1e9), 0))
    return states, body


def evolve(state, duration, steps, **limits):
    options = {**LIMITS, **limits}
    for _ in range(steps):
        state = advance_transport(state, duration / steps, **options)
    return state


def explicit_reference(states, body, duration):
    sim = rebound.Simulation()
    sim.G = G_SI
    sim.integrator = 'ias15'
    for s in (*states, body):
        x, y, z = s.position_m
        vx, vy, vz = s.velocity_m_s
        sim.add(m=s.mass_kg, x=x, y=y, z=z, vx=vx, vy=vy, vz=vz)
    sim.integrate(duration)
    return sim


def test_expanding_cloud_trajectory_converges_against_resolved_gravity():
    states, body = initial_cloud()
    initial = start_transport(states, body)
    reference = explicit_reference(states, body, 10000)
    expected_scale = math.dist(reference.particles[0].xyz, reference.particles[1].xyz) / 1e5
    errors = []
    energy_errors = []
    for steps in (40, 80, 160):
        final = evolve(initial, 10000, steps)
        errors.append(abs(final.scale - expected_scale))
        energy_errors.append(abs(final.energy_error_j))
        assert final.scale > 1
        assert 0 < final.expansion_rate_s < initial.expansion_rate_s
        assert final.elapsed_s == 10000
        assert final.reservoir.extent_m == pytest.approx(final.scale * 5e4 + 1000, rel=1e-12)
        assert final.reservoir.mutual_potential_j == pytest.approx(initial.initial_mutual_potential_j / final.scale)
        assert final.reservoir.volume_m3 == initial.reservoir.volume_m3
        assert final.reservoir.spin_kg_m2_s == initial.reservoir.spin_kg_m2_s
        assert final.reservoir.internal_energy_j == initial.reservoir.internal_energy_j
    assert 3.5 < errors[0] / errors[1] < 4.5
    assert 3.5 < errors[1] / errors[2] < 4.5
    assert errors[-1] < 2e-6
    assert 3.5 < energy_errors[0] / energy_errors[1] < 4.5
    for original, particle in zip(states, reference.particles[:2], strict=True):
        position = np.array(final.reservoir.centre_m) + final.scale * np.array(original.position_m)
        np.testing.assert_allclose(position, particle.xyz, rtol=0, atol=.1)
    np.testing.assert_allclose(final.body.position_m, reference.particles[2].xyz, rtol=0, atol=1e-3)


def test_single_fragment_transport_matches_a_kepler_orbit():
    mass, distance = 1e20, 1e8
    speed = math.sqrt(2 * G_SI * mass / distance)
    a = SphereState(mass, 2e5, (-distance / 2, 0, 0), (0, -speed / 2, 0))
    b = replace(a, position_m=(distance / 2, 0, 0), velocity_m_s=(0, speed / 2, 0))
    start = start_transport([a], b)
    duration = math.pi * distance / speed / 2
    errors = []
    for steps in (20, 40, 80):
        final = evolve(start, duration, steps, max_omitted_velocity_change_m_s=100)
        relative = np.subtract(final.body.position_m, final.reservoir.centre_m)
        errors.append(np.linalg.norm(relative - [0, distance, 0]) / distance)
        assert final.scale == 1 and final.expansion_rate_s == 0
        assert final.reservoir.dispersion_energy_j == final.reservoir.mutual_potential_j == 0
    assert 3.8 < errors[0] / errors[1] < 4.2
    assert 3.8 < errors[1] / errors[2] < 4.2
    assert errors[-1] < 2e-4


def test_initial_energy_offset_and_later_potential_error_are_explicit():
    states, body = initial_cloud()
    initial = start_transport(states, body)
    exact_initial = collision_budget((*states, body))
    assert initial.budget().energy_j + initial.energy_offset_j == pytest.approx(exact_initial.energy_j, rel=1e-12)
    final = evolve(initial, 10000, 80)
    reconstructed = tuple(replace(s, position_m=tuple(np.array(final.reservoir.centre_m) + final.scale * np.array(s.position_m)),
                                  velocity_m_s=tuple(np.array(final.reservoir.velocity_m_s)
                                                     + final.expansion_rate_s * np.array(s.position_m))) for s in states)
    exact_shape = collision_budget((*reconstructed, final.body))
    model = final.budget()
    bound = estimate_gravity(final.reservoir, final.body).potential_error_bound_j
    assert abs(exact_shape.mutual_potential_j - model.mutual_potential_j) <= bound
    assert final.energy_offset_j == initial.energy_offset_j
    assert model.internal_energy_j == exact_initial.internal_energy_j
    # Roundoff-scaled inventory closure; numerical integration energy error is separate.
    for name in ('momentum_kg_m_s', 'angular_momentum_kg_m2_s'):
        original = getattr(initial.budget(), name)
        actual = getattr(model, name)
        scale = max(math.hypot(*original), math.hypot(*actual))
        np.testing.assert_allclose(actual, original, rtol=0, atol=1e-12 * scale)


def test_rotation_translation_and_boost_preserve_the_model():
    states, body = initial_cloud()
    baseline = evolve(start_transport(states, body), 1000, 10)
    rotation = np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]])
    offset, boost = np.array([1e8, -1e7, 2e6]), np.array([100, -50, 25])
    def move(s):
        return replace(s, position_m=rotation @ s.position_m + offset,
                        velocity_m_s=rotation @ s.velocity_m_s + boost,
                        spin_kg_m2_s=rotation @ s.spin_kg_m2_s)
    actual = evolve(start_transport([move(s) for s in states], move(body)), 1000, 10)
    assert actual.scale == pytest.approx(baseline.scale, rel=1e-12)
    assert actual.expansion_rate_s == pytest.approx(baseline.expansion_rate_s, rel=1e-12)
    np.testing.assert_allclose(actual.reservoir.centre_m,
                               rotation @ baseline.reservoir.centre_m + offset + 1000 * boost, rtol=1e-12)
    np.testing.assert_allclose(actual.body.velocity_m_s, rotation @ baseline.body.velocity_m_s + boost, rtol=1e-12)


def test_nonhomologous_contracting_and_bound_clouds_are_rejected():
    states, body = initial_cloud()
    for bad in ((replace(states[0], velocity_m_s=(1, -5, 0)), states[1]), initial_cloud(-1e-4)[0]):
        with pytest.raises(ValueError, match='outward homologous'):
            start_transport(bad, body)
    with pytest.raises(ValueError, match='positive escape energy'):
        start_transport(*initial_cloud(1e-6))
    enormous = tuple(replace(s, position_m=(0, sign * 1e154, 0), velocity_m_s=(0, 0, 0))
                     for s, sign in zip(states, (-1, 1), strict=True))
    with pytest.raises(ValueError, match='inertia is outside numerical range'):
        start_transport(enormous, body)
    with pytest.raises(ValueError, match='Transport state is outside numerical range'):
        start_transport([replace(states[0], velocity_m_s=(1e200, 0, 0))], body)


def test_noncentral_self_gravity_has_an_accumulated_force_defect():
    states, body = initial_cloud()
    additional = SphereState(2e16, 1000, (0, 0, 1e5), (0, 0, 10))
    state = start_transport((*states, additional), body)
    assert state.initial_self_force_residual_m_s2 > 0
    after = advance_transport(state, 100, **LIMITS)
    assert after.force_defect_impulse_m_s >= 100 * state.initial_self_force_residual_m_s2
    limited = {**LIMITS, 'max_omitted_velocity_change_m_s': after.force_defect_impulse_m_s * 1.1}
    with pytest.raises(ValueError, match='Accumulated force defect'):
        advance_transport(after, 100, **limited)


@pytest.mark.parametrize('duration,options,message', [(-1, {}, 'duration'), (math.inf, {}, 'duration'),
    (1, {'max_relative_force_error': 0}, 'Force error'), (1, {'max_relative_energy_error': math.nan}, 'Energy error'),
    (1, {'max_omitted_velocity_change_m_s': -1}, 'Omitted velocity')])
def test_invalid_step_parameters(duration, options, message):
    state = start_transport(*initial_cloud())
    with pytest.raises(ValueError, match=message):
        advance_transport(state, duration, **{**LIMITS, **options})
    assert state.elapsed_s == 0


def test_oversized_steps_and_accumulated_energy_error_are_rejected():
    state = start_transport(*initial_cloud())
    timescale = state.expansion_rate_s * state.expansion_inertia_kg_m2 / abs(state.initial_mutual_potential_j)
    for factor in (1.8, 2.1):
        with pytest.raises(ValueError, match='reverses cloud expansion'):
            advance_transport(state, factor * timescale, **{**LIMITS, 'max_omitted_velocity_change_m_s': 100})
    with pytest.raises(ValueError, match='Accumulated energy error'):
        advance_transport(state, 500, **{**LIMITS, 'max_relative_energy_error': 1e-12})
    assert advance_transport(state, 0, **LIMITS) is state


def test_drift_cannot_hide_a_close_encounter_between_endpoints():
    cloud = SphereState(1e10, 100, (0, 0, 0), (0, 0, 0))
    body = SphereState(1e10, 100, (1e7, 0, 0), (-2e5, 0, 0))
    state = start_transport([cloud], body)
    with pytest.raises(ValueError, match='non-overlapping supports'):
        advance_transport(state, 100, **LIMITS)
    # A near miss still breaches the far-field accuracy limit mid-drift.
    state = start_transport([cloud], replace(body, position_m=(1e7, 1000, 0)))
    with pytest.raises(ValueError, match='Drift path exceeds'):
        advance_transport(state, 100, **LIMITS)


def test_instantaneously_stationary_relative_drift_is_supported():
    cloud = SphereState(1e10, 100, (0, 0, 0), (0, 0, 0))
    body = replace(cloud, position_m=(1e7, 0, 0))
    initial = start_transport([cloud], body)
    force = estimate_gravity(initial.reservoir, body).force_on_reservoir_n[0]
    cloud = replace(cloud, velocity_m_s=(-force / 2 / cloud.mass_kg, 0, 0))
    body = replace(body, velocity_m_s=(force / 2 / body.mass_kg, 0, 0))
    state = start_transport([cloud], body)
    result = advance_transport(state, 1, **LIMITS)
    assert result.reservoir.centre_m == cloud.position_m
    assert result.body.position_m == body.position_m
