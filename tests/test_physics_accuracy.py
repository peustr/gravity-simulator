"""Analytical accuracy gates and independent inventory/accounting checks."""
from types import SimpleNamespace

import numpy as np
import pytest

from diagnostics import Ledger, difference, totals
import validation as V
import world as W


@pytest.mark.parametrize('check', [V.kepler, lambda: V.kepler(0.6), V.scattering, V.hierarchical, V.merger])
def test_physical_reference_problems(check):
    outcome = check()
    assert outcome['passed'], outcome


def test_inventory_has_independent_hand_calculated_values_and_is_read_only():
    w = W.World(seed=9)
    w.add_body(W.ROCKY, 2, (-1, 0, 0), (0, -3, 0))
    w.add_body(W.ASTEROID, .1, (1, 0, 0), (0, 4, 0))
    before = w.snapshot()
    rng, version, partition = w.rng.getstate(), w.version, w._partition_dirty
    measured = totals(w)
    assert measured['mass'] == 2.1
    assert measured['momentum'] == [0, -5.6, 0]
    assert measured['angular_momentum'] == [0, 0, 6.4]
    assert measured['kinetic_energy'] == 9.8
    assert measured['potential_energy'] == -.1
    assert measured['energy'] == pytest.approx(9.7)
    assert measured['tracers'] == 1
    assert (w.rng.getstate(), w.version, w._partition_dirty) == (rng, version, partition)
    for key in ('m', 'r', 'xyz', 'v'):
        np.testing.assert_array_equal(before[key], w.snapshot()[key])


def test_empty_singular_and_nonfinite_inventory():
    w = W.World()
    assert totals(w)['energy'] == 0
    assert totals(w)['momentum'] == [0, 0, 0]
    w.add_body(W.ROCKY, 1, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, 1, (0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError, match='Coincident'):
        totals(w)
    w.sim.particles[1].x = float('nan')
    with pytest.raises(ValueError, match='Non-finite'):
        totals(w)


def test_escape_ledger_closes_mass_momentum_angular_and_mechanical_energy():
    w = W.World()
    w.add_body(W.ROCKY, 1, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, 2, (W.ESCAPE_DISTANCE + 1, 1, 0), (0, 3, 0))
    initial = totals(w)
    w.ledger = Ledger()
    w._cull_escapers()
    report = w.ledger.report(initial, totals(w))
    assert w.sim.N == 1
    assert report['entries'][0]['reason'] == 'escape_boundary'
    assert report['recorded_losses']['mass'] == 2
    assert report['recorded_losses']['momentum'] == [0, 6, 0]
    assert report['recorded_losses']['angular_momentum'] == [0, 0, 6 * (W.ESCAPE_DISTANCE + 1)]
    for value in report['remaining_change'].values():
        np.testing.assert_allclose(value, 0, atol=1e-12)
    w._cull_escapers()  # no removal -> no ledger entry
    assert len(w.ledger.entries) == 1


def test_black_hole_ledger_records_prescribed_mass_loss_only():
    w = W.World()
    # State immediately after REBOUND merged the pair, before outcome handling.
    bid = w.add_body(W.BLACK_HOLE, 200, (3, 0, 0), (0, 2, 0))
    initial = totals(w)
    w.ledger = Ledger()
    rec = dict(s=str(bid), r='99', ts=W.BLACK_HOLE, tr=W.BLACK_HOLE,
               ms=100, mr=100, rs=.6, rr=.6, vrel=(0, 0, 0), normal=(1, 0, 0), heat_r=0)
    w._handle_collision(rec)
    report = w.ledger.report(initial, totals(w))
    assert report['entries'][0]['reason'] == 'prescribed_black_hole_mass_loss'
    assert report['recorded_losses'] == dict(mass=10, momentum=[0, 20, 0], angular_momentum=[0, 0, 60], energy=20)
    assert report['remaining_change']['mass'] == 0


def test_unrecorded_change_is_not_hidden_by_ledger():
    w = V.pair((1, 0, 0), (0, 1, 0))
    before = totals(w)
    w.sim.particles[0].vx += 1
    report = Ledger().report(before, totals(w))
    assert report['remaining_change']['momentum'][0] == pytest.approx(1)
    assert report['recorded_losses']['mass'] == 0
    assert difference(before, before)['energy'] == 0


def test_invalid_ledger_capture_does_not_prevent_escape_removal():
    w = W.World()
    w.add_body(W.ROCKY, 1, (0, 0, 0), (0, 0, 0))
    for _ in range(2):
        w.add_body(W.ROCKY, 1, (W.ESCAPE_DISTANCE + 1, 0, 0), (0, 0, 0))
    w.ledger = Ledger()
    w._cull_escapers()
    assert w.sim.N == 1
    assert w.ledger.errors and not w.ledger.entries
    w.ledger.record('invalid', None, totals(w))
    w.ledger.record('invalid', totals(w), None)
    assert not w.ledger.entries
    w.clear()
    assert w.ledger is None


def test_accuracy_rejects_bad_results_and_stalled_world(monkeypatch):
    assert not V.result('bad', {'energy': 2}, {'energy': 1}, 1, 2)['passed']
    assert not V.result('bad', {'energy': float('nan')}, {'energy': 1}, 1, 2)['passed']
    clock = iter([0, 31])
    monkeypatch.setattr(V.time, 'perf_counter', lambda: next(clock))
    with pytest.raises(TimeoutError):
        list(V.samples(SimpleNamespace(sim=SimpleNamespace(t=0)), 1))


def test_reference_suite_is_complete():
    results = V.run_accuracy()
    assert {item['name'] for item in results} == {
        'kepler_circular', 'kepler_eccentric', 'hyperbolic_scattering', 'hierarchical_moon', 'inelastic_merger',
        'long_duration_and_convergence', 'contact_detection', 'symplectic_planetary_evaluation', 'forecast_force_consistency'}
    assert all(item['passed'] for item in results)
