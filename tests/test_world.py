import time
from types import SimpleNamespace

import numpy as np
import pytest

import world as W


def totals(w):
    s = w.snapshot()
    return s['m'].sum(), (s['m'][:, None] * s['v']).sum(axis=0)


def assert_partition(w):
    w._repartition()
    heavy = [not w.is_light(w.meta[p.name]['type'], p.m) for p in w.sim.particles]
    assert heavy == sorted(heavy, reverse=True)
    assert w.sim.N_active == sum(heavy)
    assert set(w.snapshot()['names']) == set(w.meta)


def test_full_spawn_is_atomic():
    w = W.World(max_bodies=1)
    w.add_body(W.ROCKY, .003, (0, 0, 0), (1, 2, 3))
    before = w.snapshot()['v'].copy()
    assert w.spawn(W.STAR, (100, 0, 0)) is None
    np.testing.assert_array_equal(w.snapshot()['v'], before)


@pytest.mark.parametrize('mode', ['orbit', 'launch'])
@pytest.mark.parametrize('fraction', [0, 0.5, 1.0])
def test_overlapping_placement_is_rejected_without_corrupting_world(mode, fraction):
    contact = W.radius_for(W.STAR, 1000) + W.radius_for(W.ROCKY, .003)
    position = (fraction * contact, 0, 0)
    w = W.World(seed=1)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    before = w.snapshot()
    next_id, version = w._next_id, w.version
    assert w.spawn(W.ROCKY, position, mode, (10, 0, 0)) is None
    assert w._next_id == next_id and w.version == version
    assert 'overlapping' in w.notices[-1]['text']
    for key in ('m', 'r', 'xyz', 'v'):
        np.testing.assert_array_equal(w.snapshot()[key], before[key])
    w.advance(1 / 60, time.perf_counter() + 1)
    from server import pack_state
    assert np.isfinite(np.frombuffer(pack_state(w), dtype='<f4')).all()


def test_overlap_check_includes_other_bodies_and_precedes_velocity_kick():
    w = W.World()
    w.add_body(W.ROCKY, .003, (0, 0, 0), (1, 2, 3))
    before = w.snapshot()['v'].copy()
    # A new star would kick this planet into a mutual orbit if accepted.
    assert w.spawn(W.STAR, (.1, 0, 0)) is None
    np.testing.assert_array_equal(w.snapshot()['v'], before)
    w.add_body(W.STAR, 1000, (20, 0, 0), (0, 0, 0))
    # A physical overlap must be rejected even when a different body dominates.
    w.sim.particles[1].m = 1e12
    assert w._dominant((.004, 0, 0), w.snapshot()) == 1
    assert w.spawn(W.ROCKY, (.004, 0, 0)) is None
    assert w.spawn(W.ROCKY, (10, 0, 0)) is not None


@pytest.mark.parametrize('paused', [False, True])
@pytest.mark.parametrize('preset, expected', [
    ('solar', 10), ('binary', 10), ('black_hole', .05), ('smash', .05),
    ('formation', 25), ('galaxies', 8), ('empty', 10),
])
def test_preset_speed_is_independent_of_previous_scene(preset, expected, paused):
    w = W.World(seed=1)
    for previous in W.SCENARIOS:
        w.load_preset(previous)
        w.speed = 640
        w.paused = paused
        hint = w.load_preset(preset)
        assert w.speed == hint['speed'] == expected
        assert w.paused is paused


def test_remove_repartitions_and_preserves_names():
    w = W.World()
    ids = [w.add_body(t, W.DEFAULT_MASS[t], (i * 100, 0, 0), (0, 0, 0))
           for i, t in enumerate([W.ASTEROID, W.STAR, W.ASTEROID, W.ROCKY])]
    assert_partition(w)
    for bid in (ids[1], ids[0], ids[3], ids[2]):
        if w.sim.N == 1:
            with pytest.warns(RuntimeWarning, match="Last particle removed"):
                assert w.remove_body(bid)
        else:
            assert w.remove_body(bid)
        assert_partition(w)
        assert w.particle(str(bid)) is None
    assert not w.remove_body(ids[0])


def test_clear_discards_old_events_and_notices():
    w = W.World()
    w._event(W.EV_MERGE, (0, 0, 0), 1, 1)
    w.notice('old scene')
    w.load_preset('empty')
    assert not w.events and not w.notices and not w.meta
    assert_partition(w)


def test_unknown_preset_preserves_scene():
    w = W.World()
    w.load_preset('binary')
    before = w.snapshot()['xyz'].copy()
    with pytest.raises(ValueError):
        w.load_preset('typo')
    np.testing.assert_array_equal(before, w.snapshot()['xyz'])


@pytest.mark.parametrize('cap', [0, -1, 1322, True, 2.5])
def test_invalid_capacity(cap):
    with pytest.raises(ValueError):
        W.World(max_bodies=cap)


def test_supernova_conserves_mass_and_momentum():
    w = W.World(seed=6)
    bid = w.add_body(W.STAR, 10000, (0, 0, 0), (1, 2, 3))
    mass, momentum = totals(w)
    assert w.supernova(bid)
    after_mass, after_momentum = totals(w)
    assert after_mass == pytest.approx(mass)
    np.testing.assert_allclose(after_momentum, momentum, rtol=1e-12)
    assert_partition(w)


def test_shattering_multiple_mergers_preserves_current_mass():
    w = W.World(seed=4)
    bid = w.add_body(W.ROCKY, .009, (0, 0, 0), (1, 2, 3))
    # The record describes an earlier pair; another body merged in the same C step.
    rec = dict(s=str(bid), r='999', ts=W.ROCKY, tr=W.ROCKY, ms=.003, mr=.003,
               rs=1, rr=1, vrel=(10, 0, 0), normal=(1, 0, 0), heat_r=0)
    mass, momentum = totals(w)
    w._handle_collision(rec)
    assert W.EV_SHATTER in [e[0] for e in w.events]
    assert totals(w)[0] == pytest.approx(mass)
    np.testing.assert_allclose(totals(w)[1], momentum, rtol=1e-12)
    p = w.particle(str(bid))
    assert p.r == pytest.approx(W.radius_for(w.meta[str(bid)]['type'], p.m))
    assert_partition(w)


def test_kilonova_promotes_actual_particle_after_array_growth():
    w = W.World(seed=8)
    a = w.add_body(W.NEUTRON_STAR, 1400, (-5, 0, 0), (0, 0, 0))
    w.add_body(W.NEUTRON_STAR, 1300, (5, 0, 0), (0, 0, 0))
    # Exercise the callback/deferred handler boundary without relying on wall time.
    import ctypes
    result = w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1))
    assert result == 2
    w.sim.remove(1)
    w._process_collisions()
    p = w.particle(str(a))
    assert w.meta[str(a)]['type'] == W.BLACK_HOLE
    assert p.r == pytest.approx(W.radius_for(W.BLACK_HOLE, p.m))
    assert totals(w)[0] == pytest.approx(2700)
    assert_partition(w)


def test_prediction_does_not_mutate_live_world():
    w = W.World(seed=2)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    before = w.snapshot()
    version, rng = w.version, w.rng.getstate()
    result = w.predict(W.STAR, (100, 0, 0), 'orbit', (0, 0, 0), 3, wall_budget=1)
    assert len(result['points']) > 50
    for key in ('m', 'r', 'xyz', 'v'):
        np.testing.assert_array_equal(before[key], w.snapshot()[key])
    assert w.version == version and w.rng.getstate() == rng


def test_pause_and_resume():
    w = W.World()
    w.paused = True
    w.advance(1, time.perf_counter() + 1)
    assert w.sim.t == 0
    w.paused = False
    w.advance(.01, time.perf_counter() + 1)
    assert w.sim.t == pytest.approx(.1)


def test_physics_selftest(monkeypatch):
    from server import selftest
    original = W.World.predict

    def slow_forecast(self, *args, **kwargs):
        # Model 1 ms per forecast sample without sleeping or replacing physics.
        # The interactive 25 ms budget truncates this otherwise valid orbit.
        from itertools import count
        clock = count(step=.001)
        with monkeypatch.context() as context:
            context.setattr(W.time, 'perf_counter', lambda: next(clock))
            return original(self, *args, **kwargs)

    monkeypatch.setattr(W.World, 'predict', slow_forecast)
    assert selftest() == 0
