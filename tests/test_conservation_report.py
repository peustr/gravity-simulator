"""Live SI budgets, unavailable inventories and persistent comparison baselines."""
import copy
import json
import math
import time

import numpy as np
import pytest

from body_state import BodyInventory, capture_sphere
from collision_outcomes import collision_budget
from diagnostics import conservation_report, physical_totals, validate_baseline
from commands import validate
import experiments as E
import server as S
import units as U
import world as W


def test_report_has_independent_si_values_including_spin_and_heat():
    w = W.World()
    w.add_body(W.ROCKY, 1e20/U.MASS_KG, np.array([1e6,2e6,3e6])/U.LENGTH_M,
               np.array([10,-20,30])/U.VELOCITY_M_S,
               inventory=BodyInventory((4e25,0,0),1e22))
    w.sim.particles[0].r = 1e4/U.LENGTH_M
    result = physical_totals(w)
    assert result['mass_kg'] == pytest.approx(1e20)
    np.testing.assert_allclose(result['momentum_kg_m_s'], [1e21,-2e21,3e21], rtol=1e-14)
    np.testing.assert_allclose(result['orbital_angular_momentum_kg_m2_s'], [1.2e28,0,-4e27], atol=1e13)
    np.testing.assert_allclose(result['angular_momentum_kg_m2_s'], [1.204e28,0,-4e27], atol=1e13)
    assert result['translational_energy_j'] == pytest.approx(7e22)
    assert result['rotational_energy_j'] == pytest.approx(2e23)
    assert result['self_binding_j'] == pytest.approx(-.6*U.G_SI*1e40/1e4)
    assert result['mutual_potential_j'] == 0
    assert result['internal_energy_j'] == 1e22
    assert result['energy_j'] == pytest.approx(2.8e23-.6*U.G_SI*1e36)


@pytest.mark.parametrize('gravity', ['full', 'tracers'])
def test_report_agrees_with_sphere_budget_and_leaves_dynamics_untouched(gravity):
    w = W.World(seed=42)
    w.load_preset('solar')
    # This reference compares spherical budgets without deformational energy.
    for i,_,_ in w.tidal_profiles():
        w.set_tide(int(w.sim.particles[i].name),0,0)
    w.configure(dict(gravity=gravity))
    saved = E.capture(w,E.DEFAULT_CAMERA)
    result = physical_totals(w)
    budget = collision_budget([capture_sphere(p,w.meta[p.name]['inventory'],w.units) for p in w.sim.particles])
    assert result['energy_j'] == pytest.approx(budget.energy_j,rel=1e-14)
    np.testing.assert_allclose(result['angular_momentum_kg_m2_s'], budget.angular_momentum_kg_m2_s,
                               rtol=0,atol=1e-14*np.linalg.norm(budget.angular_momentum_kg_m2_s))
    assert (result['tracers'] > 0) == (gravity == 'tracers')
    assert E.capture(w,E.DEFAULT_CAMERA) == saved


def test_smash_full_energy_closes_while_heat_grows_and_baseline_survives_restart():
    w = W.World(seed=42)
    w.load_preset('smash')
    first = conservation_report(w)
    assert first['relative_energy_change'] == 0
    w.speed = 1
    w.advance(.2,time.perf_counter()+3)
    after = conservation_report(w)
    assert not w.paused and w.sim.N > 2
    assert after['current']['internal_energy_j'] > first['current']['internal_energy_j']
    assert abs(after['relative_energy_change']) < 1e-10
    assert abs(after['changes']['mass_kg']) < first['current']['mass_kg']*1e-12
    data = E.capture(w,E.DEFAULT_CAMERA)
    restored,_ = E.restore(data)
    assert conservation_report(restored) == after
    restored.conservation_baseline['momentum_kg_m_s'][0] = 99
    assert data['conservation_baseline'] == first['baseline']
    reset = conservation_report(restored,reset=True)
    assert reset['relative_energy_change'] == 0
    del data['conservation_baseline']
    older,_ = E.restore(data)
    assert older.conservation_baseline is None
    assert conservation_report(older)['relative_energy_change'] == 0
    w.clear()
    assert w.conservation_baseline is None


def test_unknown_intrinsic_state_and_overlaps_keep_affected_values_unavailable():
    w = W.World()
    w.add_body(W.ROCKY,1,(0,0,0),(0,0,0),inventory=None)
    first = conservation_report(w)
    assert first['current']['unknown_inventories'] == 1
    assert first['current']['spin_angular_momentum_kg_m2_s'] is None
    assert first['current']['angular_momentum_kg_m2_s'] is None
    assert first['current']['internal_energy_j'] is None
    assert first['current']['rotational_energy_j'] is None
    assert first['current']['mass_kg'] == U.MASS_KG
    assert first['relative_energy_change'] is None
    w.meta['1']['inventory'] = BodyInventory()
    assert conservation_report(w)['changes']['energy_j'] is None
    assert conservation_report(w,reset=True)['relative_energy_change'] == 0
    w.add_body(W.ROCKY,1,(0,0,0),(0,0,0))
    overlapping = conservation_report(w)
    assert overlapping['current']['mutual_potential_j'] is None
    assert overlapping['relative_energy_change'] is None
    json.dumps(overlapping,allow_nan=False)
    assert validate_baseline({**overlapping['baseline'],'angular_momentum_kg_m2_s':None})['angular_momentum_kg_m2_s'] is None


@pytest.mark.parametrize('failure', ['legacy','gravity','position','mass','radius'])
def test_invalid_report_does_not_replace_an_existing_baseline(failure):
    w = W.World()
    w.add_body(W.ROCKY,1,(1,0,0),(0,0,0))
    conservation_report(w)
    before = copy.deepcopy(w.conservation_baseline)
    if failure == 'legacy':
        w.units = U.LEGACY
    elif failure == 'gravity':
        w.sim.G = 2
    elif failure == 'position':
        w.sim.particles[0].x = math.nan
    elif failure == 'mass':
        w.sim.particles[0].m = 0
    else:
        w.sim.particles[0].r = 0
    with pytest.raises(ValueError):
        conservation_report(w,reset=True)
    assert w.conservation_baseline == before


@pytest.mark.parametrize('bad', [False, {}, {'energy_j':0}])
def test_invalid_baseline_schema_is_rejected(bad):
    with pytest.raises(ValueError):
        validate_baseline(bad)


@pytest.mark.parametrize('key,value', [('momentum_kg_m_s',[]),('momentum_kg_m_s',1),
    ('energy_j',True),('energy_j',math.inf),('mass_kg',-1),('removed_bodies',.5),
    ('energy_j',None),('energy_scale_j',None)])
def test_malformed_saved_baselines_are_rejected(key,value):
    w = W.World()
    conservation_report(w)
    data = E.capture(w,E.DEFAULT_CAMERA)
    data['conservation_baseline'][key] = value
    with pytest.raises(ValueError):
        E.restore(data)


def test_udp_report_and_reset_validate_before_mutation_and_respond_to_requester():
    w = W.World()
    service = S.Server('127.0.0.1',0,w)
    replies = []
    service.send_json = lambda value,addr=None: replies.append((value,addr))
    addr = ('127.0.0.1',1234)
    try:
        for invalid in (1,'true',None):
            with pytest.raises(ValueError):
                service.handle(dict(cmd='conservation',reset=invalid),addr)
        assert w.conservation_baseline is None
        validate(dict(cmd='conservation'))
        service.handle(dict(cmd='conservation'),addr)
        assert replies[-1][1] == addr
        assert replies[-1][0]['ok'] and replies[-1][0]['current']['bodies'] == 0
        w.add_body(W.ROCKY,1,(1,0,0),(0,0,0))
        service.handle(dict(cmd='conservation'),addr)
        assert replies[-1][0]['changes']['mass_kg'] == U.MASS_KG
        with pytest.warns(RuntimeWarning,match='Last particle removed'):
            w.remove_body(1)
        service.handle(dict(cmd='conservation',reset=True),addr)
        assert replies[-1][0]['relative_energy_change'] == 0
        w.units = U.LEGACY
        service.handle(dict(cmd='conservation'),addr)
        assert not replies[-1][0]['ok'] and 'physical units' in replies[-1][0]['error']
    finally:
        service.sock.close()
