"""Forecast outcomes and graceful recovery from failures in the copied simulation."""
import ctypes
from itertools import product
from unittest.mock import Mock

import numpy as np
import pytest
import rebound

import world as W


def star_world():
    w = W.World(seed=1)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    return w


def predict(w, pos=(100, 0, 0), mode='orbit', drag=(0, 0, 0), **kwargs):
    return w.predict(W.ROCKY, pos, mode, drag, 1, **kwargs)


def test_empty_forecast_and_immediate_impact():
    result = predict(W.World(), mode='launch', drag=(20, 0, 0))
    assert result == dict(points=[], hit=False, attractor=-1, vel=(1, 0, 0))
    result = predict(star_world(), pos=(0, 0, 0))
    assert result['hit'] and result['attractor'] == 1
    assert result['points'] == [(0, 0, 0)] and result['vel'] == (0, 0, 0)


def test_escape_trajectory_and_future_collision():
    w = star_world()
    result = predict(w, mode='launch', drag=(100, 0, 0), samples=10, wall_budget=1)
    assert not result['hit']
    assert result['points'][-1][0] > 100
    assert result['vel'][0] > np.sqrt(2 * W.G * 1000.003 / 100)
    result = predict(w, mode='launch', drag=(-25, 0, 0), wall_budget=1)
    assert result['hit']
    assert np.linalg.norm(result['points'][-1]) < 6
    assert w.sim.N == 1 and w.sim.t == 0  # preview never advances the live world


@pytest.mark.parametrize('failure', ['exception', 'nonfinite'])
def test_failed_forecast_returns_only_finite_partial_path(monkeypatch, failure):
    w = star_world()
    original = rebound.Simulation.integrate
    calls = 0
    def integrate(sim, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == 'exception':
                raise RuntimeError('forecast integration failed')
            sim.particles[-1].x = float('nan')
        else:
            original(sim, *args, **kwargs)
    monkeypatch.setattr(rebound.Simulation, 'integrate', integrate)
    result = predict(w, samples=10, wall_budget=1)
    assert calls == 2 and len(result['points']) == 2
    assert np.isfinite(result['points']).all()
    assert w.sim.t == 0 and np.isfinite(w.snapshot()['xyz']).all()


def test_forecast_without_gravitating_attractor():
    w = star_world()
    # Fault boundary: a snapshot can still contain particles after their mass is lost.
    w.sim.particles[0].m = 0
    result = predict(w, mode='launch', drag=(1, 0, 0), samples=2, wall_budget=1)
    assert result['attractor'] == -1 and not result['hit']
    assert len(result['points']) == 3
    assert result['points'][-1][0] > result['points'][0][0]


def test_background_collision_does_not_flag_preview_as_impact(monkeypatch):
    w = star_world()
    w.add_body(W.ROCKY, .003, (50, 0, 0), (0, 0, 0))
    def integrate(sim, *args, **kwargs):
        contact = rebound.CollisionS(p1=0, p2=1)
        assert sim._collision_resolve(ctypes.pointer(sim), contact) == 0
    monkeypatch.setattr(rebound.Simulation, 'integrate', integrate)
    result = predict(w, samples=2, wall_budget=1)
    assert len(result['points']) == 3 and not result['hit']


def test_tied_attractor_is_kept_even_when_sort_places_it_outside_top_twenty(monkeypatch):
    w = W.World(seed=1)
    # 24 distinct integer-coordinate positions on the same radius: exactly equal influence.
    for axis in range(3):
        for signs in product((-1, 1), repeat=3):
            point = [20 * sign for sign in signs]
            point[axis] //= 2
            w.add_body(W.ROCKY, .003, point, (0, 0, 0))
    def reverse_ties(scores):
        assert np.all(scores == scores[0])
        return np.arange(len(scores) - 1, -1, -1)
    monkeypatch.setattr(W.np, 'argsort', reverse_ties)
    # Sorting equal keys is permitted to pick any order. The chosen attractor must
    # still be included, independent of the sort algorithm / NumPy version.
    result = predict(w, pos=(0, 0, 0), samples=220, wall_budget=1)
    assert result['attractor'] == 1
    assert len(result['points']) > 1 and np.isfinite(result['points']).all()


def test_forecast_budget_stops_further_integration(monkeypatch):
    w = star_world()
    integration = Mock()
    monkeypatch.setattr(rebound.Simulation, 'integrate', integration)
    monkeypatch.setattr(W.time, 'perf_counter', Mock(side_effect=[0, 1]))
    result = predict(w, samples=100, wall_budget=.025)
    integration.assert_called_once()
    assert len(result['points']) == 2
