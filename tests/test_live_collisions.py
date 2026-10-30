"""Native contact -> conserved merger, or an intact paused encounter."""
import ctypes
import math
import time
from types import SimpleNamespace

import numpy as np
import pytest

from body_state import BodyInventory, capture_sphere
from collision_models import surface_contact
from collision_outcomes import collision_budget
import experiments as E
import units as U
import world as W


MODE = dict(collisions='isolated_mergers', gravity='full', escape_distance=None)


def pair(*, b=0, speed_ratio=.5, gap=1.00001, capacity=2):
    w = W.World(max_bodies=capacity, seed=42)
    w.configure(MODE)
    mass = .5 * 5.9722e24 / U.MASS_KG
    radius = w.radius_for(W.ROCKY, mass)
    speed = speed_ratio * math.sqrt(2 * w.sim.G * mass / radius)
    velocity = np.array([-math.sqrt(1 - b*b), b, 0]) * speed
    for sign in (-1, 1):
        w.add_body(W.ROCKY, mass, (sign * radius * gap, 0, 0), sign * velocity / 2)
    return w


def states(w):
    return tuple(capture_sphere(p, w.meta[p.name]['inventory'], w.units) for p in w.sim.particles)


def callback(w, i=0, j=1):
    return w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=i, p2=j))


def energy_without_sun_binding(w):
    spheres = states(w)
    budget = collision_budget(spheres)
    binding = math.fsum(s.self_binding_j for p,s in zip(w.sim.particles,spheres,strict=True) if p.name != '3')
    return math.fsum((budget.translational_energy_j, budget.rotational_energy_j, binding,
                      budget.mutual_potential_j, budget.internal_energy_j))


@pytest.mark.parametrize('b,speed', [(0, .5), (.6, 1)])
@pytest.mark.parametrize('capacity', [2, 100])
def test_native_mergers_preserve_complete_budgets_and_survive_restart(b, speed, capacity):
    w = pair(b=b, speed_ratio=speed, capacity=capacity)
    initial = states(w)
    before = collision_budget(initial)
    w.advance(.0001, time.perf_counter() + 1)
    assert w.sim.N == 1 and not w.paused and not w.notices
    after = collision_budget(states(w))
    assert after.mass_kg == pytest.approx(before.mass_kg, rel=1e-12)
    momentum_scale = sum(s.mass_kg * math.hypot(*s.velocity_m_s) for s in initial)
    np.testing.assert_allclose(after.momentum_kg_m_s, before.momentum_kg_m_s, rtol=0, atol=1e-12 * momentum_scale)
    np.testing.assert_allclose(after.angular_momentum_kg_m2_s, before.angular_momentum_kg_m2_s,
                               rtol=1e-9, atol=1e15)
    energy_scale = abs(before.self_binding_j) + abs(before.mutual_potential_j) + before.translational_energy_j
    assert abs(after.energy_j - before.energy_j) < 1e-9 * energy_scale
    assert after.internal_energy_j > 0
    if b:
        assert after.rotational_energy_j > 0
    assert w.events[-1][0] == W.EV_MERGE and w.sim.N_active == 1
    saved = E.capture(w, E.DEFAULT_CAMERA)
    restored, _ = E.restore(saved)
    assert restored.settings == w.settings and states(restored) == states(w)
    restored.advance(.001, time.perf_counter() + 1)
    assert states(restored)[0].spin_kg_m2_s == states(w)[0].spin_kg_m2_s
    assert states(restored)[0].internal_energy_j == states(w)[0].internal_energy_j


def test_callback_defers_all_changes_and_deduplicates_reversed_pair():
    w = pair(gap=1)
    before = E.capture(w, E.DEFAULT_CAMERA)
    assert callback(w) == callback(w, 1, 0) == 0
    assert len(w._pending) == 1 and E.capture(w, E.DEFAULT_CAMERA) == before
    w._process_collisions()
    assert w.sim.N == 1 and not w._pending


@pytest.mark.parametrize('failure,reason', [
    ('unknown', 'known spin'), ('spin', 'nonrotating'), ('type', 'rocky planets'),
    ('third', 'External tidal'), ('external_invalid', 'External gravity mass'),
    ('gravity', 'Newtonian G'), ('legacy', 'physical units'),
    ('deep', 'shallow surface'), ('fragments', 'Multiple remnants'), ('missing_id', 'body IDs'),
])
def test_rejection_preserves_all_particles_inventories_and_rng(failure, reason):
    w = pair(gap=1, capacity=3, b=.9 if failure == 'fragments' else 0,
             speed_ratio=1.5 if failure == 'fragments' else .5)
    if failure == 'unknown':
        w.meta['1']['inventory'] = None
    elif failure == 'spin':
        w.meta['1']['inventory'] = BodyInventory((0, 0, 1e30))
    elif failure == 'type':
        w.meta['1']['type'] = W.GAS_GIANT
    elif failure == 'third':
        w.add_body(W.STAR, 1000, (1, 0, 0), (0, 0, 0))
    elif failure == 'external_invalid':
        w.add_body(W.STAR, 1000, (60, 0, 0), (0, 0, 0))
        w.particle('3').m = -1
    elif failure == 'gravity':
        w.sim.G = 2
    elif failure == 'legacy':
        w.units = U.LEGACY
    elif failure == 'deep':
        w.particle('1').x *= .99
    before = E.capture(w, E.DEFAULT_CAMERA)
    assert callback(w) == 0
    if failure == 'missing_id':
        w._pending[0]['r'] = '99'
    w._process_collisions()
    assert w.paused and reason in w.notices[-1]['text']
    after = E.capture(w, E.DEFAULT_CAMERA)
    before['paused'] = True
    assert after == before and not w.events
    w.advance(.1, time.perf_counter() + 1)
    assert E.capture(w, E.DEFAULT_CAMERA) == after


def test_native_unsupported_impact_stops_at_contact_before_heuristic_processing():
    w = pair(b=.9, speed_ratio=1.5)
    w.advance(.01, time.perf_counter() + 1)
    assert w.paused and w.sim.N == 2 and w.sim.t < .01 * w.speed
    assert 'Multiple remnants' in w.notices[-1]['text'] and not w.events
    assert all(md['inventory'] == BodyInventory() for md in w.meta.values())
    # The native step stops at the sampled encounter, not the requested end time.
    corrected = surface_contact(*states(w))
    assert math.dist(*(s.position_m for s in corrected)) == pytest.approx(sum(s.radius_m for s in corrected))


def test_survivor_spin_is_preserved_when_a_subsequent_encounter_is_rejected():
    w = pair(b=.6, speed_ratio=1, gap=1)
    callback(w)
    w._process_collisions()
    survivor = w.sim.particles[0]
    radius, mass = survivor.r, survivor.m
    w.add_body(W.ROCKY, mass, (survivor.x + 2*radius, survivor.y, survivor.z), (-1, 0, 0))
    before = E.capture(w, E.DEFAULT_CAMERA)
    callback(w)
    w._process_collisions()
    before['paused'] = True
    assert E.capture(w, E.DEFAULT_CAMERA) == before
    assert 'nonrotating' in w.notices[-1]['text']


def test_successive_head_on_mergers_retain_previously_deposited_internal_energy():
    w = pair(gap=1)
    callback(w)
    w._process_collisions()
    first = states(w)[0]
    p = w.sim.particles[0]
    w.add_body(W.ROCKY, p.m, (p.x + 2*p.r, p.y, p.z), (-.1, 0, 0))
    before = collision_budget(states(w))
    callback(w)
    w._process_collisions()
    assert w.sim.N == 1 and not w.paused
    after = collision_budget(states(w))
    assert after.mass_kg == pytest.approx(before.mass_kg, rel=1e-12)
    assert after.energy_j == pytest.approx(before.energy_j, rel=1e-12)
    np.testing.assert_allclose(after.momentum_kg_m_s, before.momentum_kg_m_s, rtol=1e-12)
    assert after.internal_energy_j > first.internal_energy_j


@pytest.mark.parametrize('changes', [dict(collisions='unknown'), dict(collisions='isolated_mergers'),
                                   MODE | dict(gravity='tracers'), MODE | dict(escape_distance=1)])
def test_invalid_mode_settings_leave_world_unchanged(changes):
    w = W.World()
    before = E.capture(w, E.DEFAULT_CAMERA)
    with pytest.raises(ValueError):
        w.configure(changes)
    assert E.capture(w, E.DEFAULT_CAMERA) == before


def test_mode_compatibility_and_heuristic_transformations():
    w = pair()
    before = states(w)
    w._supernova_queue = [1]
    assert not w.supernova(1)
    w._tidal_check()
    w._post_tick(1)
    assert states(w) == before and w._supernova_queue == [1]
    w.units = U.LEGACY
    with pytest.raises(ValueError, match='physical units'):
        w.configure(MODE)


@pytest.mark.parametrize('version', [3, 4])
def test_earlier_scene_settings_default_to_heuristic_mode(version):
    data = E.capture(W.World(), E.DEFAULT_CAMERA)
    data['version'] = version
    del data['physics']['collisions']
    restored, _ = E.restore(data)
    assert restored.settings['collisions'] == 'heuristic'


@pytest.mark.parametrize('capacity', [21, 600])
def test_unchanged_smash_preset_runs_calibrated_disruption_and_closes_budgets(capacity):
    w = W.World(max_bodies=capacity, seed=42)
    w.load_preset('smash')
    initial = states(w)
    before = collision_budget(initial)
    # Initial COM shifts are the existing preset behavior, not new initial conditions.
    assert tuple(w.snapshot()['m']) == (.003, .0026)
    assert w.particle('2').x - w.particle('1').x == pytest.approx(.8)
    assert w.particle('1').vx - w.particle('2').vx == 5
    for _ in range(240):
        w.advance(1/60, time.perf_counter()+1)
    assert not w.paused and not w.notices and w.sim.N == w.sim.N_active == 21
    after = collision_budget(states(w))
    assert max(p.m for p in w.sim.particles)/.0056 == pytest.approx(.04804214216, rel=1e-8)
    assert after.mass_kg == pytest.approx(before.mass_kg, rel=1e-12)
    momentum_scale = sum(s.mass_kg*math.hypot(*s.velocity_m_s) for s in initial)
    np.testing.assert_allclose(after.momentum_kg_m_s, before.momentum_kg_m_s, rtol=0, atol=1e-12*momentum_scale)
    angular_scale = momentum_scale * sum(s.radius_m for s in initial)
    np.testing.assert_allclose(after.angular_momentum_kg_m2_s, before.angular_momentum_kg_m2_s,
                               rtol=0, atol=1e-12*angular_scale)
    assert after.energy_j == pytest.approx(before.energy_j, rel=1e-10)
    assert after.internal_energy_j > 0
    assert [e[0] for e in w.events] == [W.EV_SHATTER]
    restored,_ = E.restore(E.capture(w,E.DEFAULT_CAMERA))
    assert states(restored) == states(w)
    w.load_preset('solar')
    assert w.settings['collisions'] == 'auto'


def test_smash_insufficient_capacity_preserves_the_unapplied_encounter():
    w = W.World(max_bodies=20,seed=42)
    w.load_preset('smash')
    for _ in range(240):
        w.advance(1/60,time.perf_counter()+1)
    assert w.paused and w.sim.N == 2 and not w.events
    assert 'Insufficient body capacity' in w.notices[-1]['text']
    assert sorted(p.m for p in w.sim.particles) == [.0026,.003]
    assert all(md['inventory'] == BodyInventory() for md in w.meta.values())


@pytest.mark.parametrize('capacity', [21, 22, 600])
def test_existing_smash_with_added_sun_runs_or_refuses_without_discarding_material(capacity):
    w = W.World(max_bodies=capacity, seed=42)
    w.load_preset('smash')
    # Add a solar mass at 1 AU through the same body-creation path as the editor.
    w.add_body(W.STAR, 1000, (0, 60, 0), (0, 0, 0))
    initial = states(w)
    before = collision_budget(initial)
    energy_before = energy_without_sun_binding(w)
    for _ in range(240):
        w.advance(1/60, time.perf_counter()+1)
    if capacity == 21:
        assert w.paused and w.sim.N == 3 and not w.events
        assert 'Insufficient body capacity' in w.notices[-1]['text']
        return
    assert not w.paused and not w.notices and w.sim.N == w.sim.N_active == 22
    after = collision_budget(states(w))
    # Do not let the Sun's constant self-binding energy hide a collision error.
    impact_scale = sum(abs(s.self_binding_j) + .5*s.mass_kg*math.hypot(*s.velocity_m_s)**2
                       for s in initial[:2])
    assert abs(energy_without_sun_binding(w)-energy_before) < 1e-9*impact_scale
    assert after.mass_kg == pytest.approx(before.mass_kg, rel=1e-14)
    momentum_scale = sum(s.mass_kg*math.hypot(*s.velocity_m_s) for s in initial)
    np.testing.assert_allclose(after.momentum_kg_m_s, before.momentum_kg_m_s, atol=1e-12*momentum_scale, rtol=0)
    np.testing.assert_allclose(after.angular_momentum_kg_m2_s, before.angular_momentum_kg_m2_s,
                               atol=1e-12*momentum_scale*U.LENGTH_M, rtol=0)
    assert [e[0] for e in w.events] == [W.EV_SHATTER]
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert states(restored) == states(w)
    for simulation in (w, restored):
        simulation.advance(1/60, time.perf_counter()+1)
    np.testing.assert_allclose(w.snapshot()['xyz'], restored.snapshot()['xyz'], rtol=1e-10, atol=1e-12)


def test_successive_mergers_with_external_gravity_preserve_inventories_and_source_state():
    w = pair(gap=1, capacity=4)
    w.add_body(W.STAR, 1000, (0,60,0), (0,0,0))
    sun = states(w)[2]
    for encounter in range(2):
        if encounter:
            p = w.particle('1')
            new_id = w.add_body(W.ROCKY, p.m, (p.x+2*p.r,0,0), (-.1,0,0))
        else:
            new_id = 2
        before = energy_without_sun_binding(w)
        w._refresh_names()
        callback(w, w._index['1'], w._index[str(new_id)])
        w._process_collisions()
        assert not w.paused and w.sim.N == 2
        assert energy_without_sun_binding(w) == pytest.approx(before, rel=1e-13)
        assert capture_sphere(w.particle('3'), w.meta['3']['inventory'], w.units) == sun


def test_calibrated_merger_in_existing_solar_system_keeps_all_surrounding_bodies():
    w = W.World(seed=42)
    w.load_preset('solar')
    assert w.settings['collisions'] == 'auto'
    target = next(p for p in w.sim.particles if p.m == .003)
    name, mass, radius = target.name, target.m, target.r
    position, velocity = tuple(target.xyz), tuple(target.vxyz)
    projectile_radius = w.radius_for(W.ROCKY, mass/2)
    gap = (radius+projectile_radius)*1.00001
    projectile = w.add_body(W.ROCKY, mass/2, (position[0]+gap,*position[1:]),
                            (velocity[0]-.5,*velocity[1:]))
    surroundings = set(w.meta)-{name,str(projectile)}
    w.advance(.0001,time.perf_counter()+2)
    assert not w.paused and not w.notices and w.sim.N == 73
    assert set(w.meta) == surroundings|{name}
    assert w.particle(name).m == pytest.approx(1.5*mass)
    assert w.meta[name]['inventory'].internal_energy_j > 0
    assert [e[0] for e in w.events] == [W.EV_MERGE]
    restored,_ = E.restore(E.capture(w,E.DEFAULT_CAMERA))
    assert states(restored) == states(w)


@pytest.mark.parametrize('shared', [True, False])
def test_simultaneous_contacts_pause_before_any_calibrated_mutation(shared):
    w = pair(gap=1, capacity=4)
    for x in (10, 20):
        w.add_body(W.ROCKY, .001, (x,0,0), (0,0,0))
    before = E.capture(w, E.DEFAULT_CAMERA)
    callback(w)
    callback(w, 1 if shared else 2, 3)
    w._process_collisions()
    before['paused'] = True
    assert E.capture(w,E.DEFAULT_CAMERA) == before and not w.events
    assert 'simultaneous contacts' in w.notices[-1]['text']
