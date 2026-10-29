"""Force choices, contact guards and persistent removal accounting."""
import math
import json
import time
from unittest.mock import Mock

import numpy as np
import pytest
import rebound

import configuration as C
import dynamics as D
import experiments as E
import server as S
import validation as V
import world as W


@pytest.mark.parametrize('changes', [None, [], {'unknown': 1}, {'gravity': 'automatic'},
    {'epsilon': 0}, {'epsilon': True}, {'epsilon': float('nan')},
    {'forecast_limit': -1}, {'forecast_limit': 1.5}, {'forecast_limit': True},
    {'escape_distance': 0}, {'escape_distance': float('inf')}, {'escape_distance': False}])
def test_invalid_physics_configuration_is_atomic(changes):
    w = W.World()
    before = E.capture(w, E.DEFAULT_CAMERA)
    with pytest.raises(ValueError):
        w.configure(changes)
    assert E.capture(w, E.DEFAULT_CAMERA) == before


def test_full_gravity_restores_collective_debris_back_reaction():
    worlds = []
    for gravity in ('tracers', 'full'):
        w = W.World()
        w.configure(dict(gravity=gravity))
        w.add_body(W.ROCKY, 1, (0, 0, 0), (0, 0, 0))
        for i in range(10):
            w.add_body(W.ASTEROID, .01, (10, i * .1, 0), (0, 0, 0))
        w.advance(.01, time.perf_counter() + 1)
        worlds.append(w)
    passive, full = worlds
    assert passive.sim.N_active == 1 and full.sim.N_active == 11
    assert passive.particle('1').vx == 0 and full.particle('1').vx > 0
    p = full.snapshot()
    np.testing.assert_allclose((p['m'][:, None] * p['v']).sum(axis=0), 0, atol=1e-15)
    summary = passive.gravity_summary()
    assert json.loads(json.dumps(summary)) == summary
    assert summary['tracers'] == 10 and summary['tracer_mass'] == pytest.approx(.1)
    assert summary['tracer_mass_fraction'] == pytest.approx(1 / 11)
    assert full.gravity_summary()['tracers'] == 0
    assert W.World().gravity_summary()['tracer_mass_fraction'] == 0
    passive.configure(dict(gravity='full'))
    assert passive.sim.N_active == 11


def test_tracer_cannot_attract_a_placed_body():
    w = W.World()
    w.configure(dict(gravity='tracers'))
    w.add_body(W.ASTEROID, .1, (0, 0, 0), (0, 0, 0))
    assert w._dominant((1, 0, 0), w.snapshot()) is None
    w.configure(dict(gravity='full'))
    assert w._dominant((1, 0, 0), w.snapshot()) == 0


def test_heavier_tracer_placement_does_not_recoil_its_active_attractor():
    w = W.World()
    w.configure(dict(gravity='tracers'))
    w.add_body(W.ROCKY, .01, (0, 0, 0), (0, 0, 0))
    bid = w.spawn(W.ASTEROID, (10, 0, 0), mass_mult=20000)
    assert w.particle('1').vxyz == [0, 0, 0]
    assert np.linalg.norm(w.particle(str(bid)).vxyz) == pytest.approx(math.sqrt(.01 / 10))


def test_partial_configuration_udp_acknowledgement_and_round_trip():
    w = W.World(seed=7)
    w.add_body(W.ASTEROID, .1, (1, 0, 0), (0, 1, 0))
    service = S.Server('127.0.0.1', 0, w)
    replies = []
    service.send_json = lambda value, addr=None: replies.append(value)
    try:
        service.handle(dict(cmd='physics', settings=dict(gravity='full', epsilon=1e-12, forecast_limit=0)), ('127.0.0.1', 1))
        assert replies[-1]['type'] == 'physics' and replies[-1]['tracers'] == 0
        assert w.sim.integrator.epsilon == 1e-12
        w.configure(dict(escape_distance=.5))
        with pytest.warns(RuntimeWarning, match='Last particle removed'):
            w._cull_escapers()
        assert w.removed == dict(bodies=1, mass=.1, momentum=[0, .1, 0], angular_momentum=[0, 0, .1], energy=.05, energy_defined=True)
        data = E.capture(w, E.DEFAULT_CAMERA)
        restored, _ = E.restore(data)
        assert restored.settings == w.settings and restored.removed == w.removed
        restored.removed['momentum'][0] = 99
        assert data['removed']['momentum'][0] == w.removed['momentum'][0] == 0
        w.configure(dict(escape_distance=None))
        w.add_body(W.ROCKY, 1, (1e6, 0, 0), (0, 0, 0))
        w._cull_escapers()
        assert w.sim.N == 1
        w.clear()
        assert w.removed['bodies'] == 0 and w.settings['gravity'] == 'full'
    finally:
        service.sock.close()


@pytest.mark.parametrize('version', [1, 2])
def test_old_saves_get_explicit_previous_approximation_settings(version):
    data = E.capture(W.World(), E.DEFAULT_CAMERA)
    data['version'] = version
    del data['physics'], data['removed']
    restored, _ = E.restore(data)
    assert restored.settings == C.LEGACY_DEFAULTS
    assert E.capture(restored, E.DEFAULT_CAMERA)['version'] == 4


@pytest.mark.parametrize('change', [
    lambda d: d.pop('physics'), lambda d: d['physics'].pop('gravity'),
    lambda d: d.update(removed=None), lambda d: d['removed'].pop('energy'),
    lambda d: d['removed'].update(energy_defined=1), lambda d: d['removed'].update(momentum=[0]),
    lambda d: d['removed'].update(bodies=-1), lambda d: d['removed'].update(energy=float('nan')),
])
def test_invalid_saved_physics_and_inventory_are_rejected(change):
    data = E.capture(W.World(), E.DEFAULT_CAMERA)
    change(data)
    with pytest.raises(ValueError):
        E.restore(data)


def test_removal_inventory_counts_losses_even_when_energy_is_undefined():
    w = W.World()
    for _ in range(2):
        w.add_body(W.ROCKY, 1, (W.ESCAPE_DISTANCE + 1, 0, 0), (0, 1, 0))
    with pytest.warns(RuntimeWarning, match='Last particle removed'):
        w._cull_escapers()
    assert w.removed['bodies'] == 2 and w.removed['mass'] == 2
    assert w.removed['momentum'] == [0, 2, 0] and not w.removed['energy_defined']


def test_ballistic_ias15_convergence_and_mode_restoration(monkeypatch):
    w = W.World()
    w.configure(dict(gravity='tracers'))
    w.add_body(W.ASTEROID, .01, (-1, 0, 0), (-1, 0, 0))
    w.add_body(W.ASTEROID, .01, (1, 0, 0), (1, 0, 0))
    for _ in range(30):
        w.advance(.1, time.perf_counter() + 1)
    assert w.sim.integrator.adaptive_mode == 'PRS23'
    assert w.sim.particles[0].x == pytest.approx(-31)
    # A native error must also restore the force-bearing solver's mode.
    with monkeypatch.context() as context:
        context.setattr(rebound.Simulation, 'steps', Mock(side_effect=RuntimeError('stop')))
        with pytest.raises(RuntimeError):
            D.step(w.sim, 1, D.ContactGuard())
    assert w.sim.integrator.adaptive_mode == 'PRS23'


def test_contact_guard_handles_unpartitioned_and_zero_gravity_states():
    sim = rebound.Simulation()
    sim.add(m=1, r=.01, x=-1, vx=1)
    sim.add(m=1, r=.01, x=1, vx=-1)
    assert sim.N_active > sim.N  # REBOUND's unsigned sentinel means all active.
    assert 0 < D.contact_step_limit(sim, 1) < 1
    sim.G = 0
    sim.dt = .1
    D.step(sim, .1, D.ContactGuard())
    assert sim.particles[0].x == pytest.approx(-.9)
    assert sim.integrator.adaptive_mode == 'PRS23'


def test_separating_surface_pair_is_rechecked_before_turnaround():
    sim = rebound.Simulation()
    sim.add(m=1, r=.5)
    sim.add(m=1, r=.5, x=1 + 1e-8, vx=.1)
    limit = D.contact_step_limit(sim, 1)
    # The nearly zero gap must not stall outward motion. Mutual acceleration
    # cannot reverse this pair before v*r**2/(G*M), even for a radial orbit.
    assert .01 < limit < .1 * (1 + 1e-8)**2 / 2


def test_cached_contact_geometry_matches_fresh_bounds_and_resets_after_edits():
    w = W.World(seed=42)
    w.load_preset('solar')
    guard = D.ContactGuard()
    for gravity in ('full','tracers'):
        w.configure(dict(gravity=gravity))
        for _ in range(3):
            fresh = D.contact_step_limit(w.sim, math.inf)
            assert guard.limit(w.sim, math.inf) == pytest.approx(fresh, rel=1e-14)
            D.step(w.sim,.001,guard)
    w.sim.particles[1].m *= 2
    w.sim.particles[1].r *= 2
    guard.reset()
    assert guard.limit(w.sim, math.inf) == D.contact_step_limit(w.sim, math.inf)


def test_safe_step_does_not_stop_at_a_stale_guard_boundary():
    sim = rebound.Simulation()
    sim.G = 0
    sim.dt = .1
    sim.add(m=1, r=.01, x=-1, vx=1)
    sim.add(m=1, r=.01, x=1, vx=-1)
    guard = D.ContactGuard()
    for _ in range(4):
        D.step(sim, .1, guard)
    sim.dt = .2
    D.step(sim, .2, guard)
    # Contact is at t=.99: a fresh check permits this whole step, without
    # splitting at the first cached bound and shrinking the native timestep.
    assert sim.t == pytest.approx(.6)
    assert sim.particles[1].x - sim.particles[0].x == pytest.approx(.8)


def test_forecast_matches_live_gravity_and_reports_omissions():
    outcome = V.forecast_accuracy()
    assert outcome['passed'], outcome
    limited = outcome['cases'][-1]
    assert limited['omitted_bodies'] > 0 and limited['omitted_active_mass'] > 0
    assert limited['position_error'] > outcome['errors']['full_state_error']


def test_forecast_radial_contact_matches_live_capture():
    w = W.World()
    w.configure(dict(gravity='tracers'))
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    preview = w.predict(W.ASTEROID, (20, 0, 0), 'launch', (0, 0, 0), 1, wall_budget=2)
    radius = w.sim.particles[0].r + W.radius_for(W.ASTEROID, 2e-5)
    assert preview['hit']
    assert math.dist(preview['points'][-1], (0, 0, 0)) == pytest.approx(radius, rel=1e-4)
    ratio = radius / 20
    expected_time = math.sqrt(20**3 / 40000) * (math.acos(math.sqrt(ratio)) + math.sqrt(ratio * (1 - ratio)))
    impact_speed = math.sqrt(40000 * (1 / radius - 1 / 20))
    assert abs(preview['times'][-1] - expected_time) * impact_speed / radius < .002
    assert w.sim.N == 1 and w.sim.t == 0
