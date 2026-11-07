"""Published CTL limits, tensor cross terms, coupled conservation and migration."""

from copy import deepcopy
import math
import time

import numpy as np
import pytest

import experiments as E
from diagnostics import physical_totals
from equilibrium_tides import Tide, response
import units as U
import world as W


def sample():
    masses = np.array([5.97e24, 7.35e22, 1.2e23])
    positions = np.array([[0.0, 0, 0], [3.844e8, 0, 0], [0, 6e8, 1e8]])
    velocities = np.array([[0.0, 0, 0], [0, 1020, 0], [-600, 0, 100]])
    return masses, positions, velocities, 6.37e6, np.array([1e-5, 7e-5, 2e-6])


def test_isolated_force_matches_mignard_including_conservative_bulge():
    masses, x, v, radius, omega = sample()
    masses, x, v = masses[:2], x[:2], v[:2]
    material = Tide(0.299, 100)
    force, torque, power, potential = response(masses, x, v, 0, radius, omega, material)
    r, vel = x[1] - x[0], v[1] - v[0]
    d = np.linalg.norm(r)
    scale = 3 * material.k2 * U.G_SI * masses[1] ** 2 * radius**5 / d**10
    reference = -scale * (d * d * r + material.lag_s * (2 * r * np.dot(r, vel) + d * d * (np.cross(r, omega) + vel)))
    np.testing.assert_allclose(force[1], reference, rtol=1e-13, atol=1e-8)
    np.testing.assert_allclose(torque, -np.cross(r, reference), rtol=1e-13, atol=1)
    assert potential == pytest.approx(-0.5 * material.k2 * U.G_SI * masses[1] ** 2 * radius**5 / d**6, rel=1e-13)
    slip = vel - np.cross(omega, r)
    assert power == pytest.approx(
        scale * material.lag_s * (2 * np.dot(r, vel) ** 2 + d * d * np.dot(slip, slip)), rel=1e-13
    )


def test_three_body_cross_terms_are_a_potential_gradient_and_close_work_budgets():
    masses, x, v, radius, omega = sample()
    force, torque, power, _ = response(masses, x, v, 0, radius, omega, Tide(0.3, 100))
    np.testing.assert_allclose(force.sum(axis=0), 0, atol=1e-6)
    np.testing.assert_allclose(np.cross(x, force).sum(axis=0) + torque, 0, atol=10)
    static = response(masses, x, v, 0, radius, omega, Tide(0.3, 0))[0]
    for body in range(3):
        for axis in range(3):
            dx = np.zeros_like(x)
            dx[body, axis] = 1000
            gradient = (
                -(
                    response(masses, x + dx, v, 0, radius, omega, Tide(0.3, 0))[3]
                    - response(masses, x - dx, v, 0, radius, omega, Tide(0.3, 0))[3]
                )
                / 2000
            )
            assert static[body, axis] == pytest.approx(gradient, rel=2e-7, abs=0.1)
    derivative = (
        response(masses, x + 10 * v, v, 0, radius, omega, Tide(0.3, 100))[3]
        - response(masses, x - 10 * v, v, 0, radius, omega, Tide(0.3, 100))[3]
    ) / 20
    assert np.sum(force * v) + np.dot(torque, omega) + derivative == pytest.approx(-power, rel=1e-7)
    # The full response includes terms missing from independent pair forces.
    pairwise = sum(response(masses[[0, j]], x[[0, j]], v[[0, j]], 0, radius, omega, Tide(0.3, 0))[3] for j in [1, 2])
    full = response(masses, x, v, 0, radius, omega, Tide(0.3, 0))[3]
    assert abs(full - pairwise) > 0.01 * abs(full)


@pytest.mark.parametrize("field,value", [("k2", True), ("k2", -1), ("k2", 2), ("lag_s", float("nan")), ("heat_j", -1)])
def test_material_validation(field, value):
    values = dict(k2=0.3, lag_s=100, heat_j=0)
    values[field] = value
    with pytest.raises(ValueError):
        Tide(**values)


def test_domain_refusal_and_zero_response():
    m, x, v, r, omega = sample()
    assert response(m, x, v, 0, r, omega, Tide(0, 100))[2:] == (0, 0)
    for radius, spin, lag in [
        (r * 100, omega, 100),
        (r, omega * 1000, 100),
        (r, omega, 1e6),
        (x[1, 0] * 2, omega, 100),
    ]:
        with pytest.raises(ValueError):
            response(m, x, v, 0, radius, spin, Tide(0.3, lag))


def lunar_world():
    w = W.World(seed=42)
    w.load_tidal_demo()
    w.configure({"escape_distance": None, "epsilon": 1e-12})
    return w


def test_lunar_variant_spin_heating_conservation_and_restart():
    w = lunar_world()
    initial = physical_totals(w)
    before = w.tidal_info()[0]
    w.speed = 0.05
    for _ in range(20):
        w.advance(0.25, time.perf_counter() + 1)
    assert not w.paused and w.sim.t == pytest.approx(0.25)
    final = physical_totals(w)
    after = w.tidal_info()[0]
    assert after["spin_ratio"] < before["spin_ratio"] and after["heat_j"] > 0
    w.set_tide(after["id"], 0.024, 100)
    assert w.tidal_info()[0]["heat_j"] == after["heat_j"]
    assert final["internal_energy_j"] - initial["internal_energy_j"] == pytest.approx(after["heat_j"], rel=1e-12)
    scale = np.linalg.norm(initial["orbital_angular_momentum_kg_m2_s"]) + np.linalg.norm(
        initial["spin_angular_momentum_kg_m2_s"]
    )
    assert (
        np.linalg.norm(np.array(final["angular_momentum_kg_m2_s"]) - initial["angular_momentum_kg_m2_s"])
        < 1e-10 * scale
    )
    assert abs(final["energy_j"] - initial["energy_j"]) < 1e-8 * initial["energy_scale_j"]
    data = E.capture(w, E.DEFAULT_CAMERA)
    restored, _ = E.restore(data)
    assert restored.meta == w.meta
    assert restored.tidal_info() == w.tidal_info()
    restored.paused = True
    stopped = deepcopy(restored.meta)
    restored.advance(100, time.perf_counter() + 1)
    assert restored.meta == stopped
    old = deepcopy(data)
    old["version"] = 8
    migrated, _ = E.restore(old)
    assert not migrated.tidal_profiles()


def test_orbit_averaged_small_eccentricity_rate_matches_hut_limit():
    w = lunar_world()
    earth, moon = sorted(w.sim.particles, key=lambda p: p.m, reverse=True)
    masses = np.array([earth.m, moon.m]) * U.MASS_KG
    radius = moon.r * U.LENGTH_M
    a = 6 * earth.r * U.LENGTH_M
    e = 0.001
    mu = U.G_SI * float(masses.sum())
    n = math.sqrt(mu / a**3)
    material = Tide(0.024, 100)
    reference = -10.5 * material.k2 * material.lag_s * (masses[0] / masses[1]) * (radius / a) ** 5 * n * n * e
    for samples in [128, 256]:
        rates = []
        for anomaly in np.arange(samples) * math.tau / samples:
            c, s = math.cos(anomaly), math.sin(anomaly)
            r = a * np.array([c - e, math.sqrt(1 - e * e) * s, 0])
            v = n * a / (1 - e * c) * np.array([-s, math.sqrt(1 - e * e) * c, 0])
            force, *_ = response(
                masses, np.array([np.zeros(3), r]), np.array([np.zeros(3), v]), 1, radius, (0, 0, n), material
            )
            acceleration = force[1] / masses[1] - force[0] / masses[0]
            h = np.cross(r, v)
            derivative = (np.cross(acceleration, h) + np.cross(v, np.cross(r, acceleration))) / mu
            rates.append(derivative[0] * (1 - e * c))
        assert np.mean(rates) == pytest.approx(reference, rel=0.0001)


def test_live_eccentricity_damping_converges_under_smaller_tidal_steps():
    errors = []
    for phase in [0.2, 0.1]:
        w = W.World(seed=42)
        earth_id = w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
        earth = w.particle(str(earth_id))
        a = 6 * earth.r
        pos, vel = w.orbit(earth.xyz, earth.vxyz, earth.m + 3.7e-5, a * 1.001, 0, ecc=0.001)
        moon_id = w.add_body(W.ROCKY, 3.7e-5, pos, vel)
        earth, moon = w.particle(str(earth_id)), w.particle(str(moon_id))
        period = math.tau * math.sqrt(a**3 / (w.sim.G * (earth.m + moon.m)))
        w.seed_rotation(moon_id, period * U.TIME_S)
        w.set_tide(moon_id, 0.024, 100.0)
        w.configure({"escape_distance": None, "epsilon": 1e-12, "tidal_phase": phase})
        initial = w.tidal_info()[0]["eccentricity"]
        reference = (
            -10.5
            * 0.024
            * 100
            * (earth.m / moon.m)
            * (moon.r / a) ** 5
            * (math.tau / (period * U.TIME_S)) ** 2
            * initial
        )
        target = 20 * period
        while w.sim.t < target:
            w._advance_tides(target - w.sim.t)
        measured = (w.tidal_info()[0]["eccentricity"] - initial) / (target * U.TIME_S)
        error = abs(measured / reference - 1)
        errors.append(error)
    assert errors[1] < errors[0]
    assert errors[1] < 0.01


def test_weak_tides_refuse_a_strong_planetary_encounter_without_changing_bodies():
    w = W.World(seed=42)
    w.load_preset("solar")
    target = next(p for p in w.sim.particles if p.m == 0.003)
    mass, radius, position, velocity = target.m, target.r, tuple(target.xyz), tuple(target.vxyz)
    gap = (radius + w.radius_for(W.ROCKY, mass / 2)) * 1.00001
    w.add_body(W.ROCKY, mass / 2, (position[0] + gap, *position[1:]), (velocity[0] - 0.5, *velocity[1:]))
    before = w.snapshot()
    w.advance(0.0001, time.perf_counter() + 1)
    assert w.paused and "deformation" in w.notices[-1]["text"]
    after = w.snapshot()
    for key in ["m", "r", "xyz", "v"]:
        np.testing.assert_array_equal(after[key], before[key])
    assert "error" in w.tidal_info()[0]


def test_quasistatic_limit_is_independent_of_material_lag():
    m, x, v, r, omega = sample()
    with pytest.raises(ValueError, match="quasistatic"):
        response(m, x, v * 1e5, 0, r, omega, Tide(0.3, 0))


@pytest.mark.parametrize("fault", ["fields", "zero", "negative_heat", "missing", "outside_domain"])
def test_invalid_tidal_save_is_rejected_atomically(fault):
    data = E.capture(lunar_world(), E.DEFAULT_CAMERA)
    body = next(b for b in data["bodies"] if b["tide"])
    if fault == "fields":
        body["tide"]["unexpected"] = 0
    elif fault == "zero":
        body["tide"]["k2"] = 0
    elif fault == "negative_heat":
        body["tide"]["heat_j"] = -1
    elif fault == "missing":
        del body["tide"]
    else:
        body["tide"]["lag_s"] = 1e6
    with pytest.raises((ValueError, KeyError)):
        E.restore(data)


def test_material_and_storage_capacity_and_backreaction_are_explicit():
    w = W.World()
    for i in range(17):
        w.add_body(W.ROCKY, 0.003, (100.0 * i, 0, 0), (0, 0, 0))
    for bid in range(1, 17):
        w.set_tide(bid, 0.3, 100)
    with pytest.raises(ValueError, match="At most"):
        w.set_tide(17, 0.3, 100)
    data = E.capture(w, E.DEFAULT_CAMERA)
    data["bodies"][-1]["tide"] = dict(k2=0.3, lag_s=100, heat_j=0)
    with pytest.raises(ValueError, match="Too many"):
        E.restore(data)
    with pytest.raises(ValueError, match="backreaction"):
        w.configure({"gravity": "tracers"})
    with pytest.raises(ValueError, match="known solid"):
        w.set_tide(999, 0.3, 100)
    w.meta["1"]["inventory"] = None
    with pytest.raises(ValueError, match="inventory"):
        w.tidal_profiles()
    assert "error" in w.tidal_info()[0]
    w.set_tide(1, 0, 0)
    assert len(w.tidal_profiles()) == 15


def test_single_body_and_unbound_orbits_are_not_reported_as_synchronised():
    from equilibrium_tides import orbit

    w = W.World()
    bid = w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
    w.set_tide(bid, 0.3, 100)
    assert w.tidal_info()[0]["spin_ratio"] is None
    w.advance(0.01, time.perf_counter() + 1)
    assert w.sim.t > 0 and w.tidal_info()[0]["heat_j"] == 0
    m = np.array([1.0, 1.0])
    x = np.array([[0.0, 0, 0], [100.0, 0, 0]])
    assert orbit(m, x, np.array([[0.0, 0, 0], [0, 1e5, 0]]), 1) is None


def test_tidal_step_failures_preserve_live_particles(monkeypatch):
    import tidal_integrator as TI

    w = lunar_world()
    solver = TI.TidalIntegrator(w.sim, w.tidal_profiles(), 1e-12)
    original = w.snapshot()
    with pytest.raises(ArithmeticError, match="time resolution"):
        solver.advance(w.sim, 0, w._contact_guard)
    with monkeypatch.context() as patch:
        patch.setattr(TI, "step", lambda *_: None)
        with pytest.raises(ArithmeticError, match="did not advance"):
            solver.advance(w.sim, 0.01, w._contact_guard)
    calls = [0]

    def inconsistent_energy(*_):
        calls[0] += 1
        return (0.0 if calls[0] == 1 else 1.0, 1.0)

    monkeypatch.setattr(solver, "energy", inconsistent_energy)
    with pytest.raises(ArithmeticError, match="budget"):
        solver.advance(w.sim, 0.01, w._contact_guard)
    assert w.sim.t == 0
    for key in ["m", "r", "xyz", "v"]:
        np.testing.assert_array_equal(w.snapshot()[key], original[key])


def test_lunar_capacity_and_unresolved_ejecta_are_refused_before_evolution():
    w = W.World(max_bodies=1)
    with pytest.raises(ValueError, match="capacity"):
        w.load_tidal_demo()
    w = lunar_world()
    w.shells = (object(),)
    with pytest.raises(ValueError, match="unresolved ejecta"):
        w._advance_tides(0.1)


def test_tidal_commands_and_stream_include_inspector_state():
    import server as S
    import commands

    w = W.World(seed=42)
    server = S.Server("127.0.0.1", 0, w)
    messages = []
    server.send_json = lambda msg, *_: messages.append(msg)
    address = ("127.0.0.1", 1)
    try:
        server.handle({"cmd": "tidal_demo"}, address)
        mid = next(int(p.name) for p in w.sim.particles if p.m < 0.001)
        server.handle({"cmd": "tide", "id": mid, "k2": 0.025, "lag_s": 100}, address)
        assert w.tidal_info()[0]["k2"] == 0.025
        server.handle({"cmd": "tide", "id": 999, "k2": 0.3, "lag_s": 100}, address)
        assert "known solid" in messages[-1]["text"]
        assert messages[0]["tidal_demo"]
        for field, value in [("id", True), ("k2", 2), ("lag_s", -1)]:
            command = dict(cmd="tide", id=mid, k2=0.3, lag_s=100)
            command[field] = value
            with pytest.raises(ValueError):
                commands.validate(command)
    finally:
        server.sock.close()


@pytest.mark.parametrize("capacity", [1, 5])
def test_clipped_solar_presets_only_configure_existing_solids(capacity):
    w = W.World(max_bodies=capacity)
    w.load_preset("solar")
    assert w.sim.N == capacity
    assert len(w.tidal_profiles()) == int(capacity == 5)


def test_background_contact_is_reported_by_live_and_forecast_tidal_steps():
    w = lunar_world()
    radius = w.radius_for(W.ASTEROID, 1e-7)
    w.add_body(W.ASTEROID, 1e-7, (100.0, 0, 0), (1, 0, 0))
    w.add_body(W.ASTEROID, 1e-7, (100.0 + 2 * radius * 0.999, 0, 0), (-1, 0, 0))
    w._repartition()
    prediction = w.predict(W.ASTEROID, (200, 0, 0), "launch", (0, 0, 0), mass_mult=1e-6, wall_budget=1)
    assert not prediction["complete"]
    w._advance_tides(0.01)
    assert w._pending


def test_tidal_energy_matches_native_omission_of_sample_sample_gravity():
    from tidal_integrator import TidalIntegrator

    w = lunar_world()
    for position in [(100.0, 0, 0), (100.0, 1, 0)]:
        bid = w.add_body(W.PLASMA, 1e-8, position, (0, 0, 0))
        w.meta[str(bid)]["tidal_sample"] = True
        w.meta[str(bid)]["volume_radius"] = w.particle(str(bid)).r
        w.particle(str(bid)).r = 0
    w._repartition()
    solver = TidalIntegrator(w.sim, w.tidal_profiles(), 1e-12)
    assert len(solver.pairs[0]) == 5
    before = physical_totals(w)
    w._advance_tides(0.001)
    after = physical_totals(w)
    assert abs(after["energy_j"] - before["energy_j"]) < 1e-8 * before["energy_scale_j"]
    # An all-active native context uses all pairs, including its default -1 flag.
    w.sim.N_active = -1
    all_active = TidalIntegrator(w.sim, w.tidal_profiles(), 1e-12)
    assert len(all_active.pairs[0]) == 6


@pytest.mark.parametrize("phase", [True, 0.001, 0.3, float("nan")])
def test_invalid_tidal_step_controls_do_not_mutate_the_live_configuration(phase):
    w = lunar_world()
    initial = w.settings.copy()
    with pytest.raises(ValueError, match="phase"):
        w.configure({"tidal_phase": phase})
    assert w.settings == initial
