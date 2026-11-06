"""Source-volume, momentum and pressureless transport regression checks."""
import math
import time

import numpy as np
import pytest

import experiments as E
import world as W
from tidal_debris import source_samples
from tools.scene_quality import birth_geometry, snapshot


@pytest.mark.parametrize('count', [4, 6, 14, 32])
def test_samples_preserve_centroid_volume_and_local_support(count):
    samples = source_samples(3., count)
    np.testing.assert_allclose(np.sum([p for p, _ in samples], axis=0), 0, atol=1e-15)
    assert math.fsum(r**3 for _, r in samples) == pytest.approx(3.**3, rel=1e-14)
    assert all(math.hypot(*p) + r <= 3. for p, r in samples)
    assert len({p for p, _ in samples}) == count


@pytest.mark.parametrize('radius,count', [(0, 4), (float('nan'), 4), (1, 3), (1, 4.0)])
def test_invalid_sampling_parameters_are_rejected(radius, count):
    with pytest.raises(ValueError):
        source_samples(radius, count)


@pytest.mark.parametrize('kind,mass', [(W.STAR, 1000.), (W.GAS_GIANT, 1.), (W.ROCKY, .003)])
@pytest.mark.parametrize('capacity', [5, 16])
def test_tidal_birth_is_local_and_does_not_inject_bulk_motion(kind, mass, capacity):
    w = W.World(seed=42, max_bodies=capacity)
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(kind, mass, (3, 2, 1), (1, 2, 3))
    parent = snapshot(w)['2']
    w._disrupt('2', '1')
    children = [p for n, p in snapshot(w).items() if n != '1']
    assert not birth_geometry(parent, children)
    assert math.fsum(p['mass'] for p in children) == pytest.approx(mass, rel=1e-15)
    assert math.fsum(p['radius']**3 for p in children) == pytest.approx(parent['radius']**3, rel=1e-14)
    assert all(p['velocity'] == parent['velocity'] for p in children)
    assert all(m['inventory'] is not None for n, m in w.meta.items() if n != '1')
    data = E.capture(w, E.DEFAULT_CAMERA)
    restored, _ = E.restore(data)
    assert restored.meta == w.meta
    np.testing.assert_array_equal(restored.snapshot()['r'], w.snapshot()['r'])


def test_overlapping_gas_parcels_pass_without_merging_or_igniting():
    w = W.World()
    w.sim.G = 0  # Independent force-free transport reference.
    w.speed = 1
    w.add_body(W.PLASMA, 500, (-1, .1, 0), (1, 0, 0))
    w.add_body(W.PLASMA, 500, (1, -.1, 0), (-1, 0, 0))
    for md in w.meta.values():
        md['tidal_sample'] = True
    for _ in range(120):
        w.advance(1/60, time.perf_counter() + .1)
    assert w.sim.t == pytest.approx(2, abs=1e-12)
    assert w.sim.N == 2 and not w.events
    assert w.particle('1').x == pytest.approx(1, abs=1e-12)
    assert w.particle('2').x == pytest.approx(-1, abs=1e-12)
    assert all(md['type'] == W.PLASMA for md in w.meta.values())


def test_parcel_accretion_preserves_density_instead_of_resetting_cloud_radius():
    w = W.World()
    w.add_body(W.PLASMA, 500, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ASTEROID, 1, (.1, 0, 0), (0, 0, 0))
    gas, rock = w.particle('1'), w.particle('2')
    w.meta['1']['tidal_sample'] = True
    gas.r = .01
    w._repartition()
    gas, rock = w.particle('1'), w.particle('2')
    initial_density = gas.m / w.body_radius(gas)**3
    w._merge_heuristic(gas, rock)
    w._promote('1', gas)
    assert gas.r == 0
    assert gas.m / w.body_radius(gas)**3 == pytest.approx(initial_density, rel=1e-14)
    assert w.meta['1']['type'] == W.PLASMA and not w.events


def test_stellar_tidal_threshold_is_not_the_circular_fluid_roche_limit():
    w = W.World()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.STAR, 1000, (3, 0, 0), (0, 1, 0))
    threshold = w.particle('2').r * 20**(1/3)
    w.particle('2').x = threshold*1.1
    w._tidal_check()
    assert w.particle('2') is not None and not w.events
    w.particle('2').x = threshold*.9
    w._tidal_check()
    assert w.particle('2') is None and w.events[-1][0] == W.EV_TIDAL


def test_insufficient_parcel_capacity_preserves_the_source():
    w = W.World(max_bodies=3)
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.STAR, 1000, (3, 0, 0), (0, 1, 0))
    before = snapshot(w)
    w._disrupt('2', '1')
    assert snapshot(w) == before and not w.events


def test_coalescing_solid_tidal_debris_does_not_restart_a_disruption_cycle():
    w = W.World()
    w.add_body(W.ASTEROID, .003, (1, 0, 0), (0, 0, 0))
    w.add_body(W.ASTEROID, .001, (1.001, 0, 0), (0, 0, 0))
    w.meta['2']['tidal_sample'] = True
    left, right = w.particle('1'), w.particle('2')
    w._merge_heuristic(left, right)
    w._promote('1', left)
    assert w.meta['1']['type'] == W.ASTEROID and w.meta['1']['tidal_sample']
    assert not w.events


@pytest.mark.parametrize('capacity', [1, 2])
@pytest.mark.parametrize('preset', ['black_hole','galaxies'])
def test_encounter_framing_survives_replacement_and_limited_capacity(capacity,preset):
    w = W.World(max_bodies=capacity)
    w.add_body(W.ASTEROID, 1, (10, 0, 0), (0, 0, 0))
    hint = w.load_preset(preset)
    assert hint['speed'] == W.PRESET_SPEEDS[preset]
    assert all(math.dist(p.xyz, hint['camera']['focus']) < hint['camera']['distance']*.5
               for p in w.sim.particles)


def test_forecast_continues_through_overlapping_background_samples():
    w = W.World()
    for x, y, vx in ((-1, .1, 1), (1, -.1, -1)):
        bid = w.add_body(W.PLASMA, .001, (x, y, 0), (vx, 0, 0))
        w.meta[str(bid)]['tidal_sample'] = True
        w.particle(str(bid)).r = 1.2
    forecast = w.predict(W.ROCKY, (0, 10, 0), 'rest', (0, 0, 0), 1, wall_budget=.1)
    assert not forecast['hit'] and len(forecast['points']) > 1
    assert forecast['times'][-1] > 0 and w.sim.t == 0


def test_stellar_capture_of_gas_does_not_ignite_or_invent_surface_heating():
    w = W.World()
    w.speed = 1
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0), heat=.25)
    w.add_body(W.PLASMA, 1, (.1, 0, 0), (0, 0, 0))
    w.particle('2').r = .01
    w.advance(.0001, time.perf_counter() + 1)
    assert w.sim.N == 1 and w.meta['1']['type'] == W.STAR
    assert w.meta['1']['heat'] <= .25
    assert W.EV_IGNITION not in [e[0] for e in w.events]


@pytest.mark.parametrize('change', ['false', 'number', 'solid', 'old_version'])
def test_invalid_parcel_identity_is_rejected_on_restore(change):
    w = W.World()
    w.add_body(W.PLASMA, 1, (0, 0, 0), (0, 0, 0))
    data = E.capture(w, E.DEFAULT_CAMERA)
    data['bodies'][0]['tidal_sample'] = True
    if change == 'false':
        data['bodies'][0]['tidal_sample'] = False
    elif change == 'number':
        data['bodies'][0]['tidal_sample'] = 1
    elif change == 'solid':
        data['bodies'][0]['type'] = W.ROCKY
    else:
        data['version'] = 5
    with pytest.raises(ValueError, match='tidal volume sample'):
        E.restore(data)
