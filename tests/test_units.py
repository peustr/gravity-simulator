"""Dimensional references, physical placement, and lossless scene migration."""
import copy
import math
import time

import numpy as np
import pytest

import experiments as E
import server as S
import units as U
import world as W


def test_si_scale_and_observed_two_body_quantities():
    assert U.G == pytest.approx(1, rel=2e-15)
    assert U.LENGTH_M * 60 == U.AU_M
    assert U.MASS_KG * 1000 == pytest.approx(1.9884e30, rel=1e-4)
    # Independent astronomical references (not a copy of radius-model formulas).
    earth = W.radius_for(W.ROCKY, .003) * U.LENGTH_M
    assert earth == pytest.approx(6_371_000, rel=.001)
    assert W.radius_for(W.STAR, 1000) * U.LENGTH_M == 695_700_000
    assert W.radius_for(W.GAS_GIANT, U.JUPITER_MASS) * U.LENGTH_M == 69_911_000
    assert W.radius_for(W.NEUTRON_STAR, 1400) * U.LENGTH_M == pytest.approx(12_000)
    assert W.radius_for(W.BLACK_HOLE, 1000) * U.LENGTH_M == pytest.approx(2953.25, rel=1e-5)
    year = 2 * math.pi * math.sqrt(60**3 / 1000.003) * U.TIME_S / 86400
    assert year == pytest.approx(365.256, rel=1e-5)
    escape = math.sqrt(2 * .003 / W.radius_for(W.ROCKY, .003)) * U.VELOCITY_M_S
    assert escape == pytest.approx(11_186, rel=.001)
    for kind in W.TYPE_KEYS.values():
        assert 0 < W.radius_for(kind, 1e-20) < math.inf
    assert W.radius_for(W.ASTEROID, .003) > W.radius_for(W.ROCKY, .003)
    assert W.radius_for(W.STAR, 2000) > W.radius_for(W.STAR, 1000)


def test_solar_initial_conditions_and_moon_hill_sphere():
    w = W.World(seed=42)
    w.load_preset('solar')
    sun, earth, moon = (w.particle(str(i)) for i in (1, 5, 6))
    separation = np.array(moon.xyz) - earth.xyz
    relative_v = np.array(moon.vxyz) - earth.vxyz
    distance = np.linalg.norm(separation)
    assert distance * U.LENGTH_M == pytest.approx(384_400_000, rel=1e-12)
    assert np.dot(separation, relative_v) == pytest.approx(0, abs=1e-15)
    assert np.linalg.norm(relative_v)**2 == pytest.approx((earth.m + moon.m) / distance)
    period_days = 2 * math.pi * math.sqrt(distance**3 / (earth.m + moon.m)) * U.TIME_S / 86400
    assert period_days == pytest.approx(27.3, rel=.01)
    hill = np.linalg.norm(np.array(earth.xyz) - sun.xyz) * (earth.m / (3 * sun.m))**(1/3)
    assert distance < .4 * hill
    center = (earth.m * np.array(earth.xyz) + moon.m * np.array(moon.xyz)) / (earth.m + moon.m)
    assert np.linalg.norm(center - sun.xyz) == pytest.approx(60, rel=1e-12)


@pytest.mark.parametrize('scenario', W.SCENARIOS)
def test_scenarios_begin_outside_physical_contact(scenario):
    w = W.World(seed=42)
    w.load_preset(scenario)
    s = w.snapshot()
    for i in range(s['n']):
        gaps = np.linalg.norm(s['xyz'][i + 1:] - s['xyz'][i], axis=1)
        assert np.all(gaps > s['r'][i + 1:] + s['r'][i]), scenario
    assert w.units == U.SYSTEM


def test_satellite_creation_preserves_barycentre_and_handles_capacity():
    w = W.World(max_bodies=2)
    parent = w.add_body(W.ROCKY, .003, (1, 2, 3), (4, 5, 6))
    w.add_satellite(parent, W.ROCKY, 3.7e-5, .154)
    snap = w.snapshot()
    for key, expected in (('xyz', [1, 2, 3]), ('v', [4, 5, 6])):
        np.testing.assert_allclose(np.sum(snap[key] * snap['m'][:, None], axis=0) / snap['m'].sum(), expected)
    assert w.add_satellite(parent, W.ROCKY, .003, .1) is None
    assert w.add_satellite(None, W.ROCKY, .003, .1) is None


def test_enlarged_visual_footprint_does_not_block_placement_or_forecast():
    w = W.World()
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    # Well inside the old 5-unit drawn star, outside its 0.279-unit photosphere.
    forecast = w.predict(W.ROCKY, (2, 0, 0), 'orbit', (0, 0, 0), 1, wall_budget=2)
    assert not forecast['hit'] and len(forecast['points']) > 50
    assert forecast['radius'] == W.radius_for(W.ROCKY, .003)
    assert w.spawn(W.ROCKY, (2, 0, 0)) is not None
    # Forecast agrees with placement at exactly touching physical surfaces.
    r = W.radius_for(W.STAR, 1000) + W.radius_for(W.ROCKY, .003)
    assert w.predict(W.ROCKY, (r, 0, 0), 'orbit', (0, 0, 0), 1)['hit']
    assert w.spawn(W.ROCKY, (r, 0, 0)) is None


def test_forecast_checks_contact_with_non_dominant_body():
    w = W.World()
    w.add_body(W.STAR, 1e9, (100, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, .003, (0, 0, 0), (0, 0, 0))
    assert w.predict(W.ROCKY, (.004, 0, 0), 'orbit', (0, 0, 0), 1)['hit']


def test_display_setting_cannot_change_saved_or_evolved_physics():
    w = W.World(seed=42)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    w.spawn(W.ROCKY, (60, 0, 0))
    data = E.capture(w, E.DEFAULT_CAMERA)
    other = copy.deepcopy(data)
    other['camera']['display_scale'] = 4
    a, _ = E.restore(data)
    b, _ = E.restore(other)
    for world in (a, b):
        world.advance(.2, time.perf_counter() + 5)
    assert S.pack_state(a) == S.pack_state(b)


def test_version_one_save_keeps_original_values_and_future_radius_rules():
    w = W.World(seed=7)
    for kind in W.TYPE_KEYS.values():
        bid = w.add_body(kind, W.DEFAULT_MASS[kind], (kind * 100, 0, 0), (0, 0, 0))
        w.particle(str(bid)).r = W.legacy_radius_for(kind, W.DEFAULT_MASS[kind])
    data = E.capture(w, E.DEFAULT_CAMERA)
    data['version'] = 1
    del data['units']
    del data['camera']['display_scale']
    legacy, camera = E.restore(data)
    assert legacy.units == U.LEGACY and legacy.sim.integrator.min_dt == 1e-4
    for body in data['bodies']:
        p = legacy.particle(str(body['id']))
        assert list(p.xyz) == body['pos'] and p.r == body['radius'] and p.m == body['mass']
        legacy._promote(p.name, p)
        assert p.r == W.legacy_radius_for(legacy.meta[p.name]['type'], p.m)
    current = E.capture(legacy, camera)
    assert current['version'] == 4 and current['units'] == U.LEGACY
    loaded, _ = E.restore(current)
    assert loaded.units == U.LEGACY
    assert np.frombuffer(S.pack_state(loaded), dtype='<f4')[10] == 0
    loaded.clear()
    assert loaded.units == U.SYSTEM and loaded.sim.integrator.min_dt == 0
    assert np.frombuffer(S.pack_state(loaded), dtype='<f4')[10] == 1
    current['units'] = 'unknown'
    with pytest.raises(ValueError, match='units'):
        E.restore(current)


def test_old_protocol_cannot_connect_or_mutate_world():
    import socket
    service = S.Server('127.0.0.1', 0, W.World())
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(2)
            client.sendto(b'{"cmd":"add","type":"star","pos":[0,0,0]}', service.sock.getsockname())
            service.poll()
            assert b'protocol_error' in client.recv(4096)
            assert service.world.sim.N == 0 and service.client is None
    finally:
        service.sock.close()


def test_legacy_tides_and_capture_keep_version_one_rules():
    import ctypes
    from types import SimpleNamespace
    w = W.World(seed=1)
    w.units = U.LEGACY
    w._new_simulation()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, .003, (10, 0, 0), (0, 0, 1))
    w._tidal_check()
    assert W.EV_TIDAL in [e[0] for e in w.events]
    w.clear()
    w.add_body(W.ROCKY, .003, (0, 0, 0), (0, 0, 0))
    hole = w.add_body(W.BLACK_HOLE, 20000, (.001, 0, 0), (-1, 0, 0))
    assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1)) == 1
    w.sim.remove(0)
    w._process_collisions()
    assert w.sim.N == 1 and w.meta[str(hole)]['type'] == W.BLACK_HOLE
    assert w.sim.particles[0].m == pytest.approx(20000.003)
