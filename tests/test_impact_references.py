"""Runnable examples exercise all published live collision domains."""

import pytest

from tools.impact_references import export_references, reference_world, PLANET_CASES
import experiments as E
import world as W


def test_exported_references_run_each_regime_and_preserve_material_across_capacity(tmp_path):
    records = export_references(tmp_path)
    assert len(records) == 15
    assert {r["regime"] for r in records} == {
        "merging",
        "graze_and_merge",
        "hit_and_run",
        "partial_accretion",
        "erosion",
        "disruption",
        "supercatastrophic_disruption",
    }
    for record in records:
        data, w, camera = E.load(record["path"])
        assert w.paused and w.settings["collisions"] == "auto" and w.settings["gravity"] == "full"
        assert data["version"] == 6 and camera == data["camera"]
        assert abs(record["relative_energy_change"]) < 1e-8
    for prefix in ("planet", "small-body"):
        full = next(r for r in records if r["name"] == prefix + "-supercatastrophic_disruption")
        compact = next(r for r in records if r["name"] == prefix + "-supercatastrophic_disruption-compact")
        assert full["bodies"] == compact["bodies"] + compact["unresolved_fragments"] == 21
        assert full["regime"] == compact["regime"]
    _, unsupported, _ = E.load(tmp_path / "planet-unsupported-spin.gravity.json")
    assert unsupported.meta["1"]["inventory"].spin_kg_m2_s != (0, 0, 0)


@pytest.mark.parametrize("material", ["bad", None, True])
def test_invalid_material_selection_is_atomic(material):
    w = W.World()
    before = w.settings.copy()
    with pytest.raises(ValueError):
        w.configure(dict(impact_material=material))
    assert w.settings == before


def test_old_setting_payloads_get_planet_law_and_presets_restore_default():
    w, _, _ = reference_world(PLANET_CASES[0])
    data = E.capture(w, E.DEFAULT_CAMERA)
    data["version"] = 4
    del data["physics"]["impact_material"]
    old, _ = E.restore(data)
    assert old.settings["impact_material"] == "fluid_planets"
    w.configure(dict(impact_material="planetesimals"))
    w.load_preset("formation")
    assert w.settings["impact_material"] == "fluid_planets"
