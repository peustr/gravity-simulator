"""Default dispatch, mixed contacts and independence of other physical processes."""
import math

import numpy as np
import pytest

import experiments as E
import world as W
from test_live_collisions import callback, pair


@pytest.mark.parametrize('preset', W.SCENARIOS)
def test_every_preset_restores_automatic_models_and_full_gravity(preset):
    w = W.World(seed=42)
    w.configure(dict(collisions='heuristic', gravity='tracers'))
    w.load_preset(preset)
    assert w.settings['collisions'] == 'auto' and w.settings['gravity'] == 'full'
    restored, _ = E.restore(E.capture(w,E.DEFAULT_CAMERA))
    assert restored.settings == w.settings


def test_external_unknown_heat_does_not_block_calibrated_pair_or_invent_inventory():
    w = pair(gap=1,capacity=3)
    w.configure(dict(collisions='auto'))
    w.add_body(W.STAR,1000,(60,0,0),(0,0,0),inventory=None)
    callback(w)
    w._process_collisions()
    assert not w.paused and w.sim.N == 2
    assert w.meta['1']['inventory'].internal_energy_j > 0
    assert w.meta['3']['inventory'] is None


def test_automatic_mixed_simultaneous_contacts_never_partially_mutate_world():
    w = pair(gap=1,capacity=4)
    w.configure(dict(collisions='auto'))
    for x in (50,51):
        w.add_body(W.STAR,1000,(x,0,0),(0,0,0))
    before=E.capture(w,E.DEFAULT_CAMERA)
    callback(w,2,3)  # Heuristic encounter arrives first.
    callback(w,0,1)
    assert E.capture(w,E.DEFAULT_CAMERA)==before
    w._process_collisions()
    before['paused']=True
    assert E.capture(w,E.DEFAULT_CAMERA)==before and not w.events
    assert 'simultaneous contacts' in w.notices[-1]['text']


def test_deferred_heuristic_contact_graph_merges_each_body_once():
    w=W.World(seed=42)
    for i in range(3):
        w.add_body(W.ASTEROID,1e-5,(i,0,0),(i,0,0))
    for i,j in ((0,1),(1,2),(0,2),(1,0)):
        assert callback(w,i,j)==0
    assert w.sim.N==3
    w._process_collisions()
    assert not w.paused and w.sim.N==1
    p=w.sim.particles[0]
    assert p.m==pytest.approx(3e-5)
    np.testing.assert_allclose(p.vxyz,(1,0,0),rtol=1e-14)
    assert w.meta[p.name]['inventory'] is None


def test_explicit_tracer_approximation_pauses_unsupported_calibrated_contact():
    w=pair(gap=1)
    w.configure(dict(collisions='auto',gravity='tracers',escape_distance=15000))
    before=E.capture(w,E.DEFAULT_CAMERA)
    callback(w)
    w._process_collisions()
    before['paused']=True
    assert E.capture(w,E.DEFAULT_CAMERA)==before
    assert 'full gravity' in w.notices[-1]['text']


def test_auto_requires_physical_units_and_preserves_legacy_settings_on_failure():
    w=W.World()
    w.configure(dict(collisions='heuristic'))
    w.units=W.units.LEGACY
    before=w.settings.copy()
    with pytest.raises(ValueError,match='physical units'):
        w.configure(dict(collisions='auto'))
    assert w.settings==before


def test_default_automatic_mode_keeps_supernovae_and_removal_available():
    w=W.World(seed=42)
    star=w.add_body(W.STAR,1000,(0,0,0),(0,0,0))
    assert w.supernova(star)
    assert W.EV_SUPERNOVA in [e[0] for e in w.events]
    assert math.isclose(sum(p.m for p in w.sim.particles),1000)
    escaped=w.add_body(W.ASTEROID,1e-5,(16000,0,0),(0,0,0))
    w._post_tick(.001)
    assert w.particle(str(escaped)) is None and w.removed['bodies']==1
