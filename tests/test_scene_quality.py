"""The scene gate must reject implausible transitions and incomplete evidence."""

from copy import deepcopy

import numpy as np
import pytest
import struct
import zlib

import world
from tools.scene_quality import (
    PROMISES,
    audit_scene,
    recording_contracts,
    assembly_check,
    assess_rendered,
    birth_geometry,
    capture_rendered,
    status,
    valid_sample,
)


def test_every_preset_requires_a_quality_contract():
    assert set(PROMISES) == set(world.SCENARIOS)


def local_breakup():
    parent = dict(mass=1.0, radius=1.0, position=(0.0, 0.0, 0.0), velocity=(1.0, 0.0, 0.0))
    children = [dict(mass=0.5, radius=0.5, position=(x, 0.0, 0.0), velocity=(1.0, 0.0, 0.0)) for x in (-0.2, 0.2)]
    return parent, children


def test_geometry_gate_accepts_local_balanced_birth_and_rejects_teleportation():
    parent, children = local_breakup()
    assert not birth_geometry(parent, children)
    moved = deepcopy(children)
    for child in moved:
        child["position"] = tuple(x * 100 for x in child["position"])
    assert "nonlocal_birth" in {i["code"] for i in birth_geometry(parent, moved)}


def test_geometry_gate_rejects_unbalanced_impulses_and_volume_expansion():
    parent, children = local_breakup()
    children[0].update(radius=5.0, velocity=(3.0, 0.0, 0.0), position=(2.0, 0.0, 0.0))
    codes = {i["code"] for i in birth_geometry(parent, children)}
    assert {"source_com_jump", "source_momentum_change", "instant_volume_expansion"} <= codes


def test_parcel_centres_alone_do_not_establish_local_birth():
    parent, children = local_breakup()
    for child, x in zip(children, (-0.8, 0.8), strict=True):
        child["position"] = (x, 0, 0)
    assert "source_volume_escape" in {i["code"] for i in birth_geometry(parent, children)}


def test_point_volume_weights_are_not_solid_extents_but_must_remain_local():
    parent, children = local_breakup()
    for child, x in zip(children, (-0.8, 0.8), strict=True):
        child.update(position=(x, 0, 0), point_sample=True)
    assert not birth_geometry(parent, children)
    children[0]["position"] = (-2, 0, 0)
    assert "nonlocal_birth" in {i["code"] for i in birth_geometry(parent, children)}


def test_independent_pair_collisions_do_not_count_as_multigeneration_formation():
    assert assembly_check({"a": {"a", "b"}, "c": {"c", "d"}})
    assert not assembly_check({"a": {"a", "b", "c"}})


def test_missing_renderer_evidence_is_blocked_not_passed(tmp_path):
    report = capture_rendered(tmp_path, tmp_path / "render", None, "forward_plus")
    assert report["status"] == "BLOCKED"
    assert status([dict(status="BLOCKED")]) == "BLOCKED"
    assert status([dict(status="BLOCKED"), dict(status="FAIL")]) == "FAIL"


def test_nonfinite_transient_cannot_be_hidden_by_a_valid_final_state():
    sample = dict(m=np.array([1.0]), r=np.array([1.0]), xyz=np.zeros((1, 3)), v=np.zeros((1, 3)))
    assert valid_sample(sample)
    sample["v"][0, 0] = float("nan")
    assert not valid_sample(sample)
    parent, children = local_breakup()
    children[0]["position"] = (float("nan"), 0.0, 0.0)
    assert birth_geometry(parent, children)[0]["code"] == "invalid_birth"


def complete_recording():
    contracts = recording_contracts()
    return dict(
        format="scene-render-quality",
        version=2,
        display="x11",
        resolution=[1280, 720],
        renderer="forward_plus",
        engine_version=dict(major=4, minor=7, patch=2),
        controls_passed=True,
        control_evidence=dict(formation_accretion="formation-accretion.png", solar_spin="solar-spin.png", lunar_tides="lunar-tides.png"),
        scenes=[
            dict(
                scene=name,
                issues=[],
                peak_white_fraction=0.001,
                peak_frame=f"{name}/peak.png",
                overlay_frames=0,
                initial_visible_fraction=1.0,
                initial_time=0.0,
                final_time=contract["seconds"] * contract["speed"],
                playback_speed=contract["speed"],
                frames=[
                    dict(
                        path=f"{name}/{i}.png",
                        time_s=i / 10,
                        frame_ms=100.0,
                        sim_time=max(0, min(contract["seconds"], i / 10 - 1)) * contract["speed"],
                        display_time=max(0, min(contract["seconds"], i / 10 - 1)) * contract["speed"],
                        white_fraction=0.001,
                        stage="initial"
                        if i < 10
                        else "watch"
                        if i <= (contract["seconds"] + 1) * 10
                        else "aftermath"
                        if i < (contract["seconds"] + 2) * 10
                        else "save_edit_restart_load",
                    )
                    for i in range((contract["seconds"] + 3) * 10)
                ],
            )
            for name, contract in contracts.items()
        ],
    )


def test_renderer_gate_requires_every_scene_and_the_target_path():
    data = complete_recording()
    assert assess_rendered(data)["status"] == "PASS"
    data = complete_recording()
    data["scenes"].pop()
    assert assess_rendered(data)["status"] == "BLOCKED"
    data = complete_recording()
    data["renderer"] = "gl_compatibility"
    assert assess_rendered(data)["status"] == "BLOCKED"


def test_peak_failure_or_missing_sequence_cannot_be_approved():
    data = complete_recording()
    data["scenes"][0]["issues"] = ["viewport_whiteout"]
    assert assess_rendered(data)["status"] == "FAIL"
    data = complete_recording()
    data["scenes"][0]["frames"] = []
    assert assess_rendered(data)["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_scene",
        "short_formation",
        "stalled_physics",
        "nonfinite_time",
        "nonfinite_peak",
        "whiteout_without_issue",
        "overlay_without_issue",
        "inconsistent_peak",
        "missing_frames",
        "reused_path",
        "missing_metrics",
        "old_schema",
        "invalid_resolution",
        "wrong_speed",
        "nonfinite_clock",
    ],
)
def test_inconsistent_or_incomplete_evidence_cannot_pass(fault):
    data = complete_recording()
    scene = data["scenes"][0]
    if fault == "duplicate_scene":
        data["scenes"].append(deepcopy(scene))
    elif fault == "short_formation":
        scene = next(s for s in data["scenes"] if s["scene"] == "formation")
        scene["frames"] = [f for f in scene["frames"] if f["stage"] != "watch" or f["time_s"] < 12]
    elif fault == "stalled_physics":
        scene["final_time"] = 0.01
    elif fault == "nonfinite_time":
        scene["frames"][0]["time_s"] = float("nan")
    elif fault == "nonfinite_peak":
        scene["peak_white_fraction"] = float("nan")
    elif fault == "whiteout_without_issue":
        scene["peak_white_fraction"] = 0.9
    elif fault == "overlay_without_issue":
        scene["overlay_frames"] = 1
    elif fault == "inconsistent_peak":
        scene["frames"][0]["white_fraction"] = 0.9
    elif fault == "missing_frames":
        scene["frames"] = scene["frames"][::30]
    elif fault == "reused_path":
        scene["frames"][1]["path"] = scene["frames"][0]["path"]
    elif fault == "old_schema":
        data["version"] = 1
    elif fault == "invalid_resolution":
        data["resolution"] = [0, 0]
    elif fault == "wrong_speed":
        scene["playback_speed"] *= 0.1
    elif fault == "nonfinite_clock":
        scene["final_time"] = float("inf")
    else:
        del scene["peak_white_fraction"]
    assert assess_rendered(data)["status"] != "PASS"
    if fault in ("whiteout_without_issue", "overlay_without_issue", "inconsistent_peak"):
        assert assess_rendered(data)["scenes"][0]["status"] == "FAIL"


def test_frozen_worlds_do_not_satisfy_orbital_or_tidal_promises(monkeypatch):
    def clock_only(w, dt, _deadline):
        w.sim.t += dt * w.speed

    monkeypatch.setattr(world.World, "advance", clock_only)
    binary = audit_scene("binary")
    tidal = audit_scene("galaxies")
    feeding = audit_scene("black_hole")
    assert "missing_binary_orbits" in {i["code"] for i in binary["issues"]}
    assert {"missing_disk_encounter", "missing_tidal_tails"} <= {i["code"] for i in tidal["issues"]}
    assert "missing_disruption" in {i["code"] for i in feeding["issues"]}


def test_breakup_mass_is_checked_independently_of_geometry():
    parent, children = local_breakup()
    for child in children:
        child["mass"] *= 0.5
    assert "birth_mass_change" in {i["code"] for i in birth_geometry(parent, children)}
    assert birth_geometry(parent, [])[0]["code"] == "missing_debris"


def test_missing_empty_or_external_png_evidence_is_blocked(tmp_path):
    data = complete_recording()

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(720 * (1 + 1280 * 3))))
        + chunk(b"IEND", b"")
    )
    for scene in data["scenes"]:
        for relative in [scene["peak_frame"], *[f["path"] for f in scene["frames"]]]:
            file = tmp_path / relative
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(png)
    (tmp_path / "formation-accretion.png").write_bytes(png)
    (tmp_path / "solar-spin.png").write_bytes(png)
    (tmp_path / "lunar-tides.png").write_bytes(png)
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "PASS"
    data["resolution"] = [1024, 576]  # Logical viewport size can differ from the framebuffer.
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
    data["resolution"] = [1280, 720]
    target = tmp_path / data["scenes"][0]["frames"][0]["path"]
    target.write_bytes(b"")
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
    target.write_bytes(png)
    (tmp_path / "formation-accretion.png").unlink()
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
    (tmp_path / "formation-accretion.png").write_bytes(png)
    (tmp_path / "solar-spin.png").unlink()
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
    (tmp_path / "solar-spin.png").write_bytes(png)
    (tmp_path / "lunar-tides.png").unlink()
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
    (tmp_path / "lunar-tides.png").write_bytes(png)
    data["scenes"][0]["frames"][0]["path"] = "../outside.png"
    assert assess_rendered(data, evidence_root=tmp_path)["status"] == "BLOCKED"
