"""Rodrigues rotation references, live inventories and orientation transport."""

from copy import deepcopy
import math
import time

import numpy as np
import pytest

from body_state import BodyInventory
from rotation import Rotation, angular_velocity
import experiments as E
import server as S
import units as U
import world as W


def rotated(q, v):
    xyz = np.array(q[:3])
    return np.array(v) + 2 * np.cross(xyz, np.cross(xyz, v) + q[3] * np.array(v))


@pytest.mark.parametrize("axis", [(1, 0, 0), (0, -1, 0), (1, 2, 3)])
def test_one_hundred_rotations_match_rodrigues_without_accumulated_drift(axis):
    axis = np.array(axis, dtype=float) / np.linalg.norm(axis)
    rate = 0.037
    state = Rotation(omega_rad_s=tuple(rate * axis))
    v = np.array([0.3, 0.4, 0.5])
    for theta in np.linspace(0, 200 * math.pi + 0.7, 201):
        reference = (
            v * math.cos(theta) + np.cross(axis, v) * math.sin(theta) + axis * np.dot(axis, v) * (1 - math.cos(theta))
        )
        np.testing.assert_allclose(rotated(state.at(theta / rate), v), reference, atol=1e-12, rtol=0)
    assert math.hypot(*state.at(1e7)) == pytest.approx(1, abs=1e-15)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(orientation=(0, 0, 0)),
        dict(orientation=(0, 0, 0, 2)),
        dict(orientation=(0, 0, float("nan"), 1)),
        dict(epoch_s=-1),
        dict(epoch_s=float("inf")),
        dict(omega_rad_s=(1, 2)),
    ],
)
def test_invalid_rotation_states_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Rotation(**kwargs)


def test_zero_spin_and_nonfinite_query():
    assert Rotation().at(12345) == (0, 0, 0, 1)
    with pytest.raises(ValueError):
        Rotation().at(float("nan"))


@pytest.mark.parametrize("period", [0, -1, float("inf")])
def test_invalid_initial_spin_is_refused_without_losing_heat(period):
    w = spinning_world()
    with pytest.raises(ValueError, match="Spin initial conditions"):
        w.seed_rotation(1, period)
    w.meta["1"]["inventory"] = BodyInventory(internal_energy_j=123)
    w.seed_rotation(1, 10000)
    assert w.meta["1"]["inventory"].internal_energy_j == 123
    p = w.particle("1")
    del w.meta["1"]
    assert w.rotation(p) == (None, False)


def spinning_world():
    w = W.World(seed=42)
    w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
    w.seed_rotation(1, 86164.0905, math.radians(23.44))
    w.speed = 0.1
    return w


def test_pause_rates_and_restart_preserve_physical_attitude_and_spin():
    w = spinning_world()
    initial, _ = w.rotation(w.particle("1"))
    w.advance(0.25, time.perf_counter() + 1)
    pose = w.rotation(w.particle("1"))[0].at(w.sim.t * U.TIME_S)
    np.testing.assert_allclose(pose, initial.at(0.025 * U.TIME_S), atol=1e-13)
    data = E.capture(w, E.DEFAULT_CAMERA)
    assert data["version"] == 9
    restored, _ = E.restore(data)
    assert restored.meta == w.meta
    restored.paused = True
    restored.advance(100, time.perf_counter() + 1)
    assert restored.rotation(restored.particle("1"))[0].at(restored.sim.t * U.TIME_S) == pose
    restored.paused = False
    restored.speed = 0.2
    for _ in range(4):
        restored.advance(0.125, time.perf_counter() + 1)
    np.testing.assert_allclose(
        restored.rotation(restored.particle("1"))[0].at(restored.sim.t * U.TIME_S),
        initial.at(0.125 * U.TIME_S),
        atol=1e-13,
    )


def test_edit_rebases_orientation_using_old_inertia_before_applying_new_rate():
    w = spinning_world()
    w.advance(0.25, time.perf_counter() + 1)
    p = w.particle("1")
    state, _ = w.rotation(p)
    pose = state.at(w.sim.t * U.TIME_S)
    old_rate = np.array(state.omega_rad_s)
    p.r *= 2
    changed, _ = w.rotation(p)
    np.testing.assert_allclose(changed.omega_rad_s, old_rate / 4, rtol=1e-14)
    assert changed.orientation == pose
    assert (
        angular_velocity(w.meta["1"]["inventory"].spin_kg_m2_s, p.m * U.MASS_KG, p.r * U.LENGTH_M)
        == changed.omega_rad_s
    )


@pytest.mark.parametrize("version", [1, 3, 4, 7])
def test_prior_save_formats_choose_reference_pose_without_inventing_spin(version):
    w = spinning_world()
    data = E.capture(w, E.DEFAULT_CAMERA)
    data["version"] = version
    restored, _ = E.restore(data)
    state, known = restored.rotation(restored.particle("1"))
    assert state.orientation == (0, 0, 0, 1)
    assert known == (version >= 4)
    if known:
        assert restored.meta["1"]["inventory"] == w.meta["1"]["inventory"]


@pytest.mark.parametrize("fault", ["quaternion", "rate", "epoch", "missing", "nonsolid", "shape", "boolean", "fields"])
def test_inconsistent_saved_pose_cannot_replace_live_physics(fault):
    data = E.capture(spinning_world(), E.DEFAULT_CAMERA)
    body = data["bodies"][0]
    if fault == "quaternion":
        body["rotation"]["orientation"] = [0, 0, 0, 2]
    elif fault == "rate":
        body["rotation"]["omega_rad_s"] = [0, 0, 0]
    elif fault == "epoch":
        body["rotation"]["epoch_s"] = 1e9
    elif fault == "missing":
        del body["rotation"]
    elif fault == "shape":
        body["rotation"]["omega_rad_s"] = [1, 2]
    elif fault == "boolean":
        body["rotation"]["epoch_s"] = True
    elif fault == "fields":
        body["rotation"]["extra"] = 0
    else:
        body["type"] = W.STAR
    with pytest.raises((ValueError, KeyError)):
        E.restore(data)


def test_rotation_packet_is_bounded_and_preserves_physical_units_and_unknowns():
    w = spinning_world()
    w.add_body(W.ASTEROID, 0.0001, (1, 0, 0), (0, 0, 0), inventory=None)
    w.add_body(W.STAR, 1000, (100, 0, 0), (0, 0, 0))
    f = np.frombuffer(S.pack_rotation(w), dtype="<f4")
    assert f[0] == S.ROTATION_KIND and f[4] == 2 and len(f) == 25
    row = f[5:15]
    assert row[1] == 1 and row[9] == pytest.approx(86164.0905, rel=1e-7)
    np.testing.assert_allclose(row[6:9] / U.TIME_S, w.rotation(w.particle("1"))[0].omega_rad_s, rtol=1e-7, atol=1e-12)
    assert f[16] == 0
    w.meta["1"]["inventory"] = BodyInventory((1e100, 0, 0))
    assert np.frombuffer(S.pack_rotation(w), dtype="<f4")[6] == 2
    w.meta["1"]["inventory"] = BodyInventory((1e-200, 0, 0))
    assert np.frombuffer(S.pack_rotation(w), dtype="<f4")[6] == 2
    w.meta["1"]["inventory"] = BodyInventory((1e308, 0, 0))
    reference = w.rotation(w.particle("1"))[0].orientation
    # Unsupported rates keep a reference pose rather than aliasing or overflowing.
    w.sim.t = 1e35
    f = np.frombuffer(S.pack_rotation(w), dtype="<f4")
    assert np.isfinite(f).all() and f[6] == 2
    np.testing.assert_allclose(f[7:11], reference, atol=1e-7)
    assert (S.ROTATION_HEADER_FLOATS + S.ROTATION_BODY_FLOATS * W.MAX_BODIES) * 4 <= 65507


def test_solar_solid_spins_are_physical_and_include_retrograde_venus():
    w = W.World(seed=42)
    w.load_preset("solar")
    planets = sorted([p for p in w.sim.particles if w.meta[p.name]["type"] == W.ROCKY], key=lambda p: p.m, reverse=True)
    earth, venus = planets[:2]
    earth_state, _ = w.rotation(earth)
    assert 2 * math.pi / math.hypot(*earth_state.omega_rad_s) == pytest.approx(86164.0905)
    assert earth_state.omega_rad_s[1] > 0 and w.rotation(venus)[0].omega_rad_s[1] < 0
    np.testing.assert_allclose(
        rotated(earth_state.orientation, (0, 1, 0)),
        np.array(earth_state.omega_rad_s) / math.hypot(*earth_state.omega_rad_s),
        atol=1e-14,
    )
    baseline = deepcopy(E.capture(w, E.DEFAULT_CAMERA))
    assert baseline["bodies"][int(earth.name) - 1]["rotation"] is not None
