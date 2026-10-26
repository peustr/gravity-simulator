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
    assert result == dict(points=[], hit=False, attractor=-1, vel=(1, 0, 0), radius=W.radius_for(W.ROCKY, .003))
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


@pytest.mark.parametrize('failure', ['exception', 'nonfinite', 'stalled'])
def test_failed_forecast_returns_only_finite_partial_path(monkeypatch, failure):
    w = star_world()
    original = rebound.Simulation.steps
    calls = 0
    def step(sim, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == 'exception':
                raise RuntimeError('forecast integration failed')
            if failure == 'nonfinite':
                sim.particles[-1].x = float('nan')
                sim.t += sim.dt
        else:
            original(sim, *args, **kwargs)
    monkeypatch.setattr(rebound.Simulation, 'steps', step)
    result = predict(w, samples=10, wall_budget=1)
    assert calls == 2 and len(result['points']) == 1
    assert not result['complete']
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
    def step(sim, *args, **kwargs):
        sim.t += sim.dt
        contact = rebound.CollisionS(p1=0, p2=1)
        assert sim._collision_resolve(ctypes.pointer(sim), contact) == 0
    monkeypatch.setattr(rebound.Simulation, 'steps', step)
    result = predict(w, samples=2, wall_budget=1)
    assert len(result['points']) == 2 and not result['hit']


def test_physical_background_impact_cannot_stall_native_forecast():
    # A subprocess timeout catches a native IAS15 stall that Python's wall
    # budget cannot interrupt. Both colliding bodies already exist in smash.
    import subprocess
    import sys
    from pathlib import Path
    code = """
import sys
sys.path.insert(0, 'physics_server')
import world as W
w = W.World(seed=42)
w.load_preset('smash')
result = w.predict(W.ROCKY, (400, 50, 0), 'orbit', (0, 0, 0), 1, wall_budget=1)
assert len(result['points']) == 2 and not result['hit']
assert w.sim.t == 0 and w.sim.N == 2
"""
    subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                   check=True, timeout=10, capture_output=True)


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
    monkeypatch.setattr(rebound.Simulation, 'steps', integration)
    monkeypatch.setattr(W.time, 'perf_counter', Mock(side_effect=[0, 1]))
    result = predict(w, samples=100, wall_budget=.025)
    integration.assert_not_called()
    assert len(result['points']) == 1


def test_forecast_budget_interrupts_an_unfinished_sample(monkeypatch):
    w = star_world()
    original = rebound.Simulation.steps
    calls = []

    def step(sim, count):
        calls.append(count)
        original(sim, count)

    monkeypatch.setattr(rebound.Simulation, 'steps', step)
    monkeypatch.setattr(W.time, 'perf_counter', Mock(side_effect=[0, .001, .026]))
    # One distant sample would normally require many adaptive native steps.
    result = predict(w, samples=1, wall_budget=.025)
    assert calls == [1]
    assert len(result['points']) == 2
    assert result['points'][0] != result['points'][1]
    assert not result['hit'] and w.sim.t == 0


def test_forecast_samples_a_complete_kepler_orbit_without_time_reversal(monkeypatch):
    w = star_world()
    original = rebound.Simulation.steps
    times = []

    def step(sim, count):
        original(sim, count)
        times.append(sim.t)

    monkeypatch.setattr(rebound.Simulation, 'steps', step)
    # Eliminate host timing from this numerical accuracy test.
    monkeypatch.setattr(W.time, 'perf_counter', lambda: 0)
    result = predict(w, samples=220)
    assert len(result['points']) == 221
    assert np.all(np.diff(times) > 0)
    theta = np.linspace(0, 2 * np.pi * 1.02, 221)
    expected = np.column_stack([100 * np.cos(theta), np.zeros_like(theta), -100 * np.sin(theta)])
    np.testing.assert_allclose(result['points'], expected, rtol=0, atol=1e-7)
