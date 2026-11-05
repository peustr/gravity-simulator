"""The scene gate must reject implausible transitions and incomplete evidence."""

from copy import deepcopy

import numpy as np

import world
from tools.scene_quality import (
    PROMISES,
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
    for child, x in zip(children, (-.8, .8), strict=True):
        child['position'] = (x, 0, 0)
    assert 'source_volume_escape' in {i['code'] for i in birth_geometry(parent, children)}


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
    return dict(
        display="x11",
        renderer="forward_plus",
        engine_version=dict(major=4, minor=7, patch=2),
        controls_passed=True,
        scenes=[
            dict(
                scene=name,
                issues=[],
                frames=[
                    dict(path=f"{name}/{i}.png", time_s=t, stage=s)
                    for i, (t, s) in enumerate(
                        ((0, "initial"), (1, "watch"), (12, "watch"), (13, "aftermath"), (14, "save_edit_restart_load"))
                    )
                ],
            )
            for name in PROMISES
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
