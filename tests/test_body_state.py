"""Persistent physical inventories, immutable captures and heuristic boundaries."""
import ctypes
from dataclasses import FrozenInstanceError
import time
from types import SimpleNamespace

import pytest

from body_state import BodyInventory, capture_sphere
import world as W


def add(w, pos=(0, 0, 0), **kwargs):
    return w.add_body(W.ROCKY, .003, pos, (1, 2, 3), **kwargs)


def test_inventory_owns_values_and_motion_and_visual_cooling_leave_it_unchanged():
    spin = [1e30, -2e30, 3e30]
    inventory = BodyInventory(spin, 4e25)
    spin[0] = 0
    with pytest.raises(FrozenInstanceError):
        inventory.internal_energy_j = 0
    w = W.World()
    add(w, heat=1, inventory=inventory)
    before = capture_sphere(w.particle('1'), inventory, w.units)
    w.advance(.01, time.perf_counter() + 1)
    after = capture_sphere(w.particle('1'), w.meta['1']['inventory'], w.units)
    assert after.position_m != before.position_m
    assert after.spin_kg_m2_s == before.spin_kg_m2_s == (1e30, -2e30, 3e30)
    assert after.internal_energy_j == before.internal_energy_j == 4e25
    assert before.position_m == (0, 0, 0)
    assert w.meta['1']['heat'] < 1


@pytest.mark.parametrize('kwargs', [dict(spin_kg_m2_s=(0, 1)),
                                   dict(spin_kg_m2_s=(0, float('nan'), 0)),
                                   dict(internal_energy_j=-1),
                                   dict(internal_energy_j=float('inf'))])
def test_invalid_inventory_is_rejected(kwargs):
    with pytest.raises(ValueError):
        BodyInventory(**kwargs)


def test_invalid_inventory_does_not_add_a_particle_or_consume_its_id():
    w = W.World()
    with pytest.raises(ValueError, match='inventory'):
        add(w, inventory={})
    assert w.sim.N == 0 and w._next_id == 1
    w.units = W.units.LEGACY
    with pytest.raises(ValueError, match='Legacy'):
        add(w, inventory=BodyInventory(internal_energy_j=1))
    assert w.sim.N == 0 and w._next_id == 1
    add(w)
    assert w.meta['1']['inventory'] is None
    assert capture_sphere(w.particle('1'), BodyInventory(), w.units) is None


def test_chained_callbacks_do_not_mistake_unaccounted_merger_for_zero_inventory():
    w = W.World()
    w.configure(dict(collisions='heuristic'))
    inventory = BodyInventory((1e30, 2e30, 3e30), 4e25)
    add(w, inventory=inventory)
    add(w, (1, 0, 0))
    add(w, (2, 0, 0))
    for _ in range(2):
        assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1)) == 2
        w.sim.remove(1)
    first, second = [record['spheres'] for record in w._pending]
    assert first[0].spin_kg_m2_s == inventory.spin_kg_m2_s
    assert first[0].internal_energy_j == inventory.internal_energy_j
    assert second[0] is None and second[1].internal_energy_j == 0
    w._process_collisions()
    assert w.sim.N == 1 and w.meta['1']['inventory'] is None


def test_callback_with_missing_metadata_records_unknown_state_without_failing():
    w = W.World()
    w.configure(dict(collisions='heuristic'))
    add(w)
    add(w, (1, 0, 0))
    del w.meta['1']
    assert w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1)) == 2
    a, b = w._pending[0]['spheres']
    assert a is None and b.mass_kg == .003 * W.units.MASS_KG
    assert w.sim.particles[0].m == .006


def test_type_or_radius_changes_invalidate_inventory_but_noop_promotion_preserves_it():
    w = W.World()
    add(w)
    p = w.particle('1')
    w._promote('1', p)
    assert w.meta['1']['inventory'] == BodyInventory()
    p.r *= 2
    w._promote('1', p)
    assert w.meta['1']['inventory'] is None
    w.meta['1']['inventory'] = BodyInventory()
    p.m = W.ROCKY_TO_GAS
    w._promote('1', p)
    assert w.meta['1']['type'] == W.GAS_GIANT and w.meta['1']['inventory'] is None


def test_supernova_and_tides_do_not_invent_ejecta_inventories():
    w = W.World(seed=42)
    w.add_body(W.STAR, 10000, (0, 0, 0), (0, 0, 0))
    assert w.supernova(1)
    assert all(md['inventory'] is None for md in w.meta.values())
    w = W.World(seed=42)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    add(w, (100, 0, 0))
    w._disrupt('2', '1')
    assert w.sim.N > 2 and w.particle('2') is None
    assert w.meta['1']['inventory'] == BodyInventory()
    assert all(md['inventory'] is None for name, md in w.meta.items() if name != '1')
