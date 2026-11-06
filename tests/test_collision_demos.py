"""Selectable encounters exercise the shared live engine and physical view."""

import time
import math

import numpy as np
import pytest

from commands import validate
from diagnostics import conservation_report
from encounters import DEMO_CASES
from encounters import demo_initial_conditions
import experiments as E
import server as S
import world as W


@pytest.mark.parametrize("case", DEMO_CASES)
@pytest.mark.parametrize("capacity", [2, 40])
def test_live_encounters_have_requested_outcomes_and_preserve_all_material(case, capacity):
    w = W.World(max_bodies=capacity, seed=42)
    hint = w.load_collision_demo(case)
    assert w.paused and w.speed == 0.005 and hint["camera"]["display_scale"] == 0
    assert hint["camera"]["distance"] < 1.5
    baseline = conservation_report(w)
    w.paused = False
    w.speed = 1
    deadline = time.perf_counter() + 3
    while w.sim.t < 0.02 - 1e-12 and not w.paused:
        assert time.perf_counter() < deadline
        w.advance(min(0.001, 0.02 - w.sim.t), time.perf_counter() + 0.1)
    assert not w.paused and not w.notices
    report = w.gravity_summary()["last_impact"]
    assert report["regime"] == ("supercatastrophic_disruption" if case == "disruption" else case)
    assert sum(report["remnant_masses_kg"]) == pytest.approx(baseline["current"]["mass_kg"], rel=1e-14)
    assert abs(conservation_report(w)["relative_conservation_residual"]) < 1e-9
    restored, _ = E.restore(E.capture(w, hint["camera"]))
    assert restored.last_impact == w.last_impact and restored.collision_demo == w.collision_demo
    assert report["angle_deg"] == pytest.approx(hint["collision_demo"]["angle_deg"], abs=0.01)
    assert report["speed_m_s"] == pytest.approx(hint["collision_demo"]["speed_m_s"], rel=1e-3)
    if case == "disruption":
        assert report["unresolved_fragments"] == (20 if capacity == 2 else 0)
    else:
        assert w.sim.N == (1 if case == "merging" else 2)


def test_demo_restart_endpoint_and_close_slow_state_round_trip():
    w = W.World(seed=42)
    service = S.Server("127.0.0.1", 0, w)
    replies = []
    service.send_json = lambda message, addr=None: replies.append(message)
    addr = ("127.0.0.1", 1234)
    try:
        service.handle(dict(cmd="collision_demo", case="merging", play=True), addr)
        assert not w.paused and service.checkpoint["paused"]
        assert replies[-1]["collision_demo"]["case"] == "merging"
        restored, cam = E.restore(service.checkpoint)
        np.testing.assert_array_equal(restored.snapshot()["xyz"], w.snapshot()["xyz"])
        assert cam["distance"] < 1.5 and restored.speed == 0.005
        service.handle(dict(cmd="speed", value=0.00001), addr)
        restored, _ = E.restore(E.capture(w, cam))
        assert restored.speed == 0.00001
        before = E.capture(w, cam)
        for bad in ("unknown", None, False):
            with pytest.raises(ValueError):
                w.load_collision_demo(bad)
            assert E.capture(w, cam) == before
    finally:
        service.sock.close()


@pytest.mark.parametrize("payload", [dict(case="bad"), dict(case="merging", play=1)])
def test_bad_demo_commands_are_rejected_before_mutation(payload):
    with pytest.raises(ValueError):
        validate(dict(cmd="collision_demo", **payload))


def test_demo_builder_and_capacity_refuse_before_changing_the_world():
    with pytest.raises(ValueError):
        demo_initial_conditions("unknown", [1, 1], [1, 1])
    w = W.World(max_bodies=1)
    w.add_body(W.STAR, 1000, (0, 0, 0), (0, 0, 0))
    before = E.capture(w, E.DEFAULT_CAMERA)
    with pytest.raises(ValueError, match="two body slots"):
        w.load_collision_demo("merging")
    assert E.capture(w, E.DEFAULT_CAMERA) == before


@pytest.mark.parametrize("fault", ["fields", "case", "regime", "masses", "speed", "angle", "unresolved"])
def test_bad_saved_encounter_history_is_rejected(fault):
    w = W.World()
    hint = w.load_collision_demo("merging")
    data = E.capture(w, hint["camera"])
    data["last_impact"] = dict(
        regime="merging", speed_m_s=1000.0, angle_deg=0.0, remnant_masses_kg=[1e24], unresolved_fragments=0
    )
    if fault == "fields":
        data["collision_demo"] = {}
    elif fault == "case":
        data["collision_demo"]["case"] = "unknown"
    else:
        key = {
            "regime": "regime",
            "masses": "remnant_masses_kg",
            "speed": "speed_m_s",
            "angle": "angle_deg",
            "unresolved": "unresolved_fragments",
        }[fault]
        data["last_impact"][key] = {"regime": "unknown", "masses": [], "speed": -1, "angle": 91, "unresolved": 2}[fault]
    with pytest.raises(ValueError):
        E.restore(data)


@pytest.mark.parametrize("seed", [1, 42, 2026])
def test_formation_initial_conditions_and_follow_survive_restart(seed):
    w = W.World(seed=seed)
    w.load_preset("binary")  # Body IDs continue across scenario switches.
    hint = w.load_preset("formation")
    camera = hint["camera"]
    assert camera['follow'] == -1 and camera["display_scale"] == 0
    assert all(math.dist(p.xyz, camera['focus']) < camera['distance']*math.sin(math.radians(27.5))
               for p in w.sim.particles)
    followed = next(p.name for p in w.sim.particles if w.meta[p.name]['type'] == W.ROCKY)
    camera = dict(camera, follow=int(followed))  # Follow a selected embryo before saving.
    initial_mass = sum(p.m for p in w.sim.particles if w.meta[p.name]["type"] == W.ROCKY)
    assert all(math.dist(a.xyz,b.xyz)>a.r+b.r for i,a in enumerate(w.sim.particles) for b in list(w.sim.particles)[i+1:])
    initial_count = w.sim.N
    radius = w.particle(followed).r
    conservation_report(w, reset=True)
    w, camera = E.restore(E.capture(w, camera))
    assert str(camera["follow"]) == followed
    assert initial_count == 65 and not w.paused
    assert w.particle(followed).r == radius
    assert sum(p.m for p in w.sim.particles if w.meta[p.name]["type"] == W.ROCKY) == initial_mass


def test_cold_disk_grows_across_generations_with_closed_budgets():
    w = W.World(seed=42)
    w.load_preset('formation')
    lineages = {p.name: {p.name} for p in w.sim.particles if w.meta[p.name]['type'] == W.ROCKY}
    initial_mass = sum(p.m for p in w.sim.particles)
    conservation_report(w, reset=True)
    deadline = time.perf_counter() + 90
    while w.sim.t < 40 - 1e-9:
        assert time.perf_counter() < deadline
        w.advance(min(1/60, max(0., (40-w._target_t)/w.speed)), time.perf_counter()+.05)
        for e in w.events:
            if e[0] == W.EV_MERGE:
                a,b = str(int(e[6])),str(int(e[7]))
                if a in lineages and b in lineages:
                    lineages[a] |= lineages.pop(b)
        w.events.clear()
        assert not w.paused and not w.notices
    assert max(len(s) for n,s in lineages.items() if w.particle(n) is not None) >= 3
    assert sum(p.m for p in w.sim.particles) == pytest.approx(initial_mass, rel=1e-14)
    assert abs(conservation_report(w)["relative_conservation_residual"]) < 1e-8
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert restored.meta == w.meta and restored.last_impact == w.last_impact
    np.testing.assert_array_equal(restored.snapshot()['m'],w.snapshot()['m'])


@pytest.mark.parametrize("follow", [True, -2, 1.5])
def test_invalid_camera_follow_is_rejected(follow):
    with pytest.raises(ValueError):
        E.camera_state(dict(E.DEFAULT_CAMERA, follow=follow))


def test_body_limit_does_not_produce_a_missing_camera_target():
    w = W.World(max_bodies=1)
    hint = w.load_preset("formation")
    assert w.sim.N == 1 and hint["camera"]["follow"] == -1
