"""Physical invariants, capacity boundaries, and recoverable integrator failures."""
import ctypes
import math
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import rebound

from commands import validate
import world as W


def add(w, kind=W.ROCKY, mass=.003, pos=(0, 0, 0), vel=(0, 0, 0)):
    return w.add_body(kind, mass, pos, vel)


def collision(w, i=0, j=1):
    result = w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=i, p2=j))
    assert result in (1, 2)
    w.sim.remove(i if result == 1 else j)
    w._process_collisions()


def record(kind=W.ROCKY, mass=.003, speed=10):
    return dict(s='1', r='2', ts=kind, tr=kind, ms=mass, mr=mass,
                rs=1, rr=1, normal=(1, 0, 0), vrel=(speed, 0, 0), heat_r=0)


def test_capacity_rejection_does_not_consume_ids():
    w = W.World(max_bodies=1)
    assert add(w, mass=0) is None
    assert add(w) == 1
    assert add(w) is None
    assert w.sim.N == 1 and w._next_id == 2
    assert W.radius_for(-1, 1) == 1


def test_invalid_placement_mode_and_nonfinite_mass():
    with pytest.raises(ValueError, match='mode'):
        validate(dict(cmd='add', type='rocky', pos=[0, 0, 0], mode='invalid'))
    w = W.World()
    for multiplier in (0, -1, float('inf'), float('nan')):
        with pytest.raises(ValueError, match='mass'):
            w.spawn(W.ROCKY, (0, 0, 0), mass_mult=multiplier)
    assert w.sim.N == 0


def test_advance_caps_time_debt_and_respects_expired_budget():
    w = W.World()
    add(w)
    w._target_t = 100
    w.advance(1, deadline=-1)
    assert w.sim.t == 0
    assert w._target_t == w.speed * .25
    assert w.perf == 0


@pytest.mark.parametrize('error', [rebound.NoParticles, RuntimeError])
def test_integrator_failure_preserves_a_usable_world(monkeypatch, capsys, error):
    w = W.World()
    add(w)
    original = w.snapshot()['xyz'].copy()
    with monkeypatch.context() as context:
        context.setattr(rebound.Simulation, 'steps', Mock(side_effect=error('injected integrator failure')))
        w.advance(.01, time.perf_counter() + 1)
    np.testing.assert_array_equal(w.snapshot()['xyz'], original)
    if error is rebound.NoParticles:
        assert w.sim.t == pytest.approx(.1)
    else:
        assert w.sim.t == 0
        assert 'injected integrator failure' in capsys.readouterr().err
    w.advance(.01, time.perf_counter() + 1)
    assert w.sim.t > 0


def test_culls_only_escaped_bodies():
    w = W.World()
    near = add(w)
    far = add(w, pos=(W.ESCAPE_DISTANCE + 1, 0, 0))
    w._cull_escapers()
    assert w.particle(str(near)) is not None
    assert w.particle(str(far)) is None
    assert len(w.meta) == w.sim.N == 1


def test_callback_ignores_self_contact_and_reports_failure(capsys):
    w = W.World()
    add(w)
    assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=0)) == 0
    assert not w._pending
    assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=99)) == 0
    assert not w._pending and w.sim.N == 1
    assert 'Traceback' in capsys.readouterr().err


def test_callback_with_zero_mass_does_not_divide_by_zero():
    w = W.World()
    add(w)
    add(w, pos=(1, 0, 0))
    for p in w.sim.particles:
        p.m = 0
    assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1)) == 2
    assert len(w._pending) == 1
    assert np.isfinite(w.snapshot()['xyz']).all()


def test_failed_deferred_collision_does_not_drop_later_records(monkeypatch, capsys):
    w = W.World()
    w._pending = [{'s': 'first'}, {'s': 'second'}]
    handler = Mock(side_effect=[RuntimeError('bad collision'), None])
    monkeypatch.setattr(w, '_handle_collision', handler)
    w._process_collisions()
    assert handler.call_count == 2 and not w._pending
    assert w.sim.did_modify_particles == 1
    assert 'bad collision' in capsys.readouterr().err


def test_black_hole_merger_radiates_five_percent():
    w = W.World()
    add(w, W.BLACK_HOLE, 20000)
    add(w, W.BLACK_HOLE, 10000, pos=(1, 0, 0))
    collision(w)
    p = w.particle('1')
    assert w.sim.N == 1 and p.m == pytest.approx(28500)
    assert p.r == W.radius_for(W.BLACK_HOLE, p.m)
    assert w.events[-1][0] == W.EV_BH_MERGER


def test_fast_star_collision_ejects_gas():
    w = W.World(seed=1)
    add(w, W.STAR, 1000, vel=(1000, 0, 0))
    add(w, W.STAR, 1000, pos=(1, 0, 0), vel=(-1000, 0, 0))
    collision(w)
    assert w.events[0][0] == W.EV_SHATTER
    assert w.sim.N > 1
    assert sum(p.m for p in w.sim.particles) == pytest.approx(2000)
    assert any(md['type'] == W.PLASMA for md in w.meta.values())


def test_shatter_rejects_massless_impactor_and_tolerates_missing_metadata():
    w = W.World(seed=2)
    add(w, mass=.006)
    rec = record()
    rec['mr'] = 0
    assert not w._try_shatter(w.particle('1'), rec, W.ASTEROID)
    assert w.sim.N == 1
    rec['mr'] = .003
    w.meta.pop('1')
    assert w._try_shatter(w.particle('1'), rec, W.ASTEROID)
    assert sum(p.m for p in w.sim.particles) == pytest.approx(.006)
    assert w.events[-1][0] == W.EV_SHATTER


def test_kilonova_at_capacity_keeps_mass_in_remnant():
    w = W.World(max_bodies=2)
    add(w, W.NEUTRON_STAR, 1400)
    add(w, W.NEUTRON_STAR, 1300, pos=(1, 0, 0))
    collision(w)
    assert w.sim.N == 1 and w.particle('1').m == 2700
    assert w.meta['1']['type'] == W.BLACK_HOLE
    assert [e[0] for e in w.events] == [W.EV_KILONOVA, W.EV_COLLAPSE]


@pytest.mark.parametrize('kind,mass,result', [
    (W.ROCKY, W.ROCKY_TO_GAS, W.GAS_GIANT),
    (W.PLASMA, W.PLASMA_TO_STAR, W.STAR),
    (W.ASTEROID, W.ASTEROID_TO_ROCKY, W.ROCKY),
])
def test_promotion_updates_type_radius_and_partition(kind, mass, result):
    w = W.World()
    add(w, kind, mass)
    w._promote('1', w.particle('1'))
    assert w.meta['1']['type'] == result
    assert w.particle('1').r == W.radius_for(result, mass)
    assert w._partition_dirty
    if result == W.STAR:
        assert w.events[-1][0] == W.EV_IGNITION
    else:
        assert not w.events
    w._promote('deleted', None)


def test_massive_star_promotion_triggers_natural_supernova():
    w = W.World(seed=2)
    add(w, W.STAR, W.STAR_COLLAPSE)
    w._promote('1', w.particle('1'))
    assert w._supernova_queue == [1]
    w._post_tick(.01)
    assert not w._supernova_queue
    assert w.meta['1']['type'] == W.BLACK_HOLE
    assert w.events[-1][0] == W.EV_SUPERNOVA


def test_supernova_requires_star_and_room():
    w = W.World(max_bodies=2)
    assert not w.supernova(999)
    add(w)
    assert not w.supernova(1)
    add(w, W.STAR, 1000, pos=(100, 0, 0))
    assert not w.supernova(2)
    assert w.sim.N == 2 and w.particle('2').m == 1000
    assert 'Too many bodies' in w.notices[-1]['text']


def test_tidal_disruption_requires_existing_bodies_and_room():
    w = W.World(max_bodies=2)
    add(w, W.STAR, 1000)
    add(w, W.ROCKY, .003, pos=(100, 0, 0))
    before = w.snapshot()['xyz'].copy()
    w._disrupt('missing', '1')
    w._disrupt('2', 'missing')
    w._disrupt('2', '1')
    np.testing.assert_array_equal(before, w.snapshot()['xyz'])
    assert not w.events


def test_placement_velocities_for_empty_polar_and_interior_positions():
    w = W.World()
    vel, attractor, kick = w.initial_velocity((0, 0, 0), .003, 'launch', (2, 0, 0), w.snapshot())
    assert vel == (.1, 0, 0) and attractor is None and kick == (0, 0, 0)
    add(w, W.STAR, 1000, vel=(1, 2, 3))
    snap = w.snapshot()
    assert w._dominant((100, 0, 0), snap, exclude=0) is None
    vel, attractor, kick = w.initial_velocity((0, 0, 0), .003, 'orbit', (0, 0, 0), snap)
    assert vel == (1, 2, 3) and attractor == 0
    vel, _, _ = w.initial_velocity((0, 100, 0), .003, 'orbit', (0, 0, 0), snap)
    relative = np.array(vel) - [1, 2, 3]
    assert relative[1] == 0
    assert np.linalg.norm(relative) == pytest.approx(math.sqrt(1000.003 / 100))


def test_heavy_placement_gives_attractor_balancing_kick():
    w = W.World()
    add(w, W.STAR, 1000)
    w.spawn(W.STAR, (100, 0, 0), mass_mult=2)
    snap = w.snapshot()
    np.testing.assert_allclose((snap['m'][:, None] * snap['v']).sum(axis=0), 0, atol=1e-12)
    assert np.linalg.norm(snap['v'][0]) > 0


def test_belt_in_empty_space_and_at_capacity():
    w = W.World(max_bodies=3, seed=1)
    assert w.belt((0, 0, 0), count=5) == 3
    assert w.sim.N == 3
    assert np.linalg.norm(w.snapshot()['xyz'], axis=1).max() <= 20
    assert w.belt((0, 0, 0)) == 0
    assert 'no room' in w.notices[-1]['text']


def test_shattering_at_capacity_preserves_merged_mass():
    w = W.World(max_bodies=1)
    add(w, mass=.006)
    assert not w._try_shatter(w.particle('1'), record(), W.ASTEROID)
    assert w.sim.N == 1 and w.particle('1').m == .006
    assert not w.events


def test_chained_collision_skips_survivor_swallowed_in_the_same_step():
    w = W.World()
    add(w, mass=.003)
    add(w, mass=.002, pos=(1, 0, 0))
    star = add(w, W.STAR, 1000, pos=(2, 0, 0))
    # REBOUND can report several contacts before deferred collision handling.
    # First the planets merge; then the star swallows that merged survivor.
    contact = SimpleNamespace(p1=0, p2=1)
    assert w._resolve_collision(ctypes.pointer(w.sim), contact) == 2
    w.sim.remove(1)
    assert w._resolve_collision(ctypes.pointer(w.sim), contact) == 1
    w.sim.remove(0)
    assert len(w._pending) == 2
    w._process_collisions()
    assert w.sim.N == 1 and set(w.meta) == {str(star)}
    assert w.particle(str(star)).m == pytest.approx(1000.005)
    assert not w._pending
    # The stale planet merger must not emit an event or create phantom fragments.
    assert [event[0] for event in w.events] == [W.EV_SWALLOW]
