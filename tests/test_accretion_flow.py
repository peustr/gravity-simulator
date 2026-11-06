"""Point-sample transport, absorbing surfaces and complete unresolved inventories."""

from dataclasses import replace
import math
import time

import numpy as np
import pytest

from body_state import BodyInventory, GravitySource
from collision_models import gentle_rebound, couple_external_gravity
from diagnostics import conservation_report
from dynamics import GAS_SINK_RADII
import experiments as E
import units as U
import world as W
from test_collision_models import rocky_pair, assert_closed
from tidal_debris import source_samples


def test_ballistic_nodes_react_on_resolved_bodies_without_mutual_node_forces():
    w = W.World()
    w.speed = 1
    w.add_body(W.ROCKY, 1, (10, 0, 0), (0, 0, 0))
    for x in (-1, 1):
        bid = w.add_body(W.PLASMA, 1, (x, 0, 0), (0, 0, 0))
        w.meta[str(bid)]["tidal_sample"] = True
    w.advance(1e-6, time.perf_counter() + 1)
    assert w.sim.N_active == 1 and w.sim.testparticle_type == 1
    assert w.particle("2").vx / 1e-6 == pytest.approx(1 / 11**2, rel=1e-8)
    assert w.particle("3").vx / 1e-6 == pytest.approx(1 / 9**2, rel=1e-8)
    assert w.particle("2").r == w.particle("3").r == 0
    assert np.linalg.norm(np.sum(w.snapshot()["m"][:, None] * w.snapshot()["v"], axis=0)) < 1e-18


def test_singular_capture_refuses_before_mutation():
    w = W.World()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.PLASMA, 1, (0, 0, 0), (0, 0, 0))
    w.meta["2"]["tidal_sample"] = True
    w._repartition()
    before = E.capture(w, E.DEFAULT_CAMERA)
    w._pending.append(w._collision_record(w.particle("1"), w.particle("2"))[2])
    w._process_collisions()
    assert w.paused and w.notices and not w.accretion_flows
    assert E.capture(w, E.DEFAULT_CAMERA)["bodies"] == before["bodies"]


def test_unknown_source_inventory_is_not_reconstructed_during_sampling():
    w = W.World()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.STAR, 1000, (3, 0, 0), (0, 1, 0), inventory=None)
    w._disrupt("2", "1")
    assert all(md["inventory"] is None for name, md in w.meta.items() if name != "1")
    assert conservation_report(w)["current"]["energy_j"] is None


def test_rotating_source_pauses_the_live_step_before_any_tidal_replacement():
    w = W.World()
    w.speed = 1
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.STAR, 1000, (0.7, 0, 0), (0, 0, 0), inventory=BodyInventory((0, 0, 1e30)))
    w.advance(0.1, time.perf_counter() + 1)
    assert w.paused and w.sim.N == 2 and w.sim.t < 0.1
    assert len(w.notices) == 1 and not w.events


def test_legacy_clouds_keep_finite_contact_radii_and_no_inner_flow_scale():
    w = W.World()
    w.units = U.LEGACY
    w.configure(dict(collisions="heuristic", gravity="tracers"))
    w.add_body(W.PLASMA, 1, (0, 0, 0), (0, 0, 0))
    w.meta["1"]["tidal_sample"] = True
    radius = w.particle("1").r
    w._repartition()
    assert not w.is_ballistic("1") and w.particle("1").r == radius > 0
    assert w.gravity_summary()["gas_capture_radius_rs"] == 0
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert restored.particle("1").r == radius and restored.meta == w.meta


@pytest.mark.parametrize("impact_b,impact_speed,regime", [(0, 0.5, "gentle_sticking"), (0.9, 1.5, "contact_rebound")])
def test_local_contacts_close_budgets_in_a_nonisolated_field(impact_b, impact_speed, regime):
    from test_live_collisions import pair, callback

    w = pair(b=impact_b, speed_ratio=impact_speed, gap=1, capacity=3)
    w.configure(dict(collisions="auto"))
    w.add_body(W.STAR, 1000, (1, 0, 0), (0, 0, 0))
    before = w.snapshot()["xyz"].copy()
    conservation_report(w, reset=True)
    callback(w)
    w._process_collisions()
    assert not w.paused and not w.notices
    assert w.last_impact["regime"] == regime
    assert w.sim.N == (2 if regime == "gentle_sticking" else 3)
    if regime == "contact_rebound":
        np.testing.assert_allclose(w.snapshot()["xyz"], before, rtol=0, atol=1e-15)
    assert abs(conservation_report(w)["relative_conservation_residual"]) < 1e-12


def test_forecast_stops_when_background_gas_enters_the_inner_flow():
    w = W.World()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    surface = w.particle("1").r * GAS_SINK_RADII
    w.add_body(W.PLASMA, 10, (1.2 * surface, 0, 0), (-1000, 300, 0))
    w.meta["2"]["tidal_sample"] = True
    result = w.predict(W.ROCKY, (20, 0, 0), "rest", (0, 0, 0), 1, wall_budget=1)
    assert not result["hit"] and not result["complete"]
    assert 0 < result["times"][-1] < result["horizon"] and w.sim.t == 0 and w.sim.N == 2


@pytest.mark.parametrize("peri_ratio", [0.8, 1.2])
def test_capture_matches_keplerian_loss_cone(peri_ratio):
    w = W.World()
    w.speed = 1
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    surface = w.particle("1").r * GAS_SINK_RADII
    apo, peri = 10 * surface, peri_ratio * surface
    mass = 1e-8
    mu = w.sim.G * (20000 + mass)
    semi = (apo + peri) / 2
    speed = math.sqrt(mu * (2 / apo - 1 / semi))
    w.add_body(W.PLASMA, mass, (apo, 0, 0), (0, speed, 0))
    w.meta["2"]["tidal_sample"] = True
    w.advance(math.pi * math.sqrt(semi**3 / mu), time.perf_counter() + 2)
    assert not w.paused and not w.notices
    assert (w.sim.N == 1) == (peri_ratio < 1)


def test_point_volume_quadrature_converges_to_uniform_sphere_and_capture_cross_section():
    errors = []
    for count in (56, 224, 4096):
        points = np.array([p for p, r in source_samples(1.0, count, point=True)])
        error = float(np.max(np.abs((points * points).mean(axis=0) - 0.2)))
        errors.append(error)
        assert np.linalg.norm(points, axis=1).max() <= 1
    assert errors[0] < 0.012 and errors[1] < 0.007 and errors[2] < 0.001
    assert errors[0] > errors[1] > errors[2]
    # Exact volume fraction of a uniform sphere inside a straight loss cylinder.
    points = np.array([p for p, r in source_samples(1.0, 4096, point=True)])
    captured_fraction = float(np.mean(points[:, 1] ** 2 + points[:, 2] ** 2 < 0.3**2))
    assert abs(captured_fraction - (1 - (1 - 0.3**2) ** 1.5)) < 0.01


def captured(radius=0.1):
    w = W.World(seed=42)
    w.speed = 1
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    surface = w.particle("1").r * GAS_SINK_RADII
    w.add_body(W.PLASMA, 10, (1.2 * surface, 0, 0), (-1000, 300, 0))
    w.meta["2"]["tidal_sample"] = True
    w.particle("2").r = radius
    conservation_report(w, reset=True)
    w.advance(surface / 1000, time.perf_counter() + 2)
    assert not w.paused and not w.notices and w.sim.N == 1
    return w


def test_capture_uses_centres_and_retains_energy_and_angular_momentum_in_inner_flow():
    a, b = captured(0.00001), captured(0.1)
    np.testing.assert_allclose(a.snapshot()["xyz"], b.snapshot()["xyz"], rtol=1e-12, atol=1e-14)
    for w in (a, b):
        report = conservation_report(w)
        assert report["current"]["unknown_inventories"] == 0
        assert abs(report["relative_conservation_residual"]) < 1e-12
        np.testing.assert_allclose(
            report["current"]["angular_momentum_kg_m2_s"], report["baseline"]["angular_momentum_kg_m2_s"], rtol=1e-12
        )
        assert w.meta["1"]["inventory"] == BodyInventory()  # No invented hole temperature or spin.
        assert w.accretion_flows["1"]["mass_kg"] == pytest.approx(10 * U.MASS_KG)
        assert w.accretion_flows["1"]["energy_j"] != 0
        restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
        assert restored.accretion_flows == w.accretion_flows
        assert restored.tidal_potential_offset_j == w.tidal_potential_offset_j
        assert conservation_report(restored)["current"] == report["current"]
    with pytest.warns(RuntimeWarning, match="Last particle"):
        assert a.remove_body(1)
    assert not a.accretion_flows


def test_sampling_preserves_known_inventories_and_separates_quadrature_reference_from_heat():
    w = W.World()
    w.add_body(W.BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
    w.add_body(W.STAR, 1000, (3, 2, 1), (1, 2, 3), inventory=BodyInventory(internal_energy_j=1e30))
    before = conservation_report(w, reset=True)["current"]
    w._disrupt("2", "1")
    after = conservation_report(w)
    assert after["current"]["unknown_inventories"] == 0
    assert abs(after["relative_conservation_residual"]) < 1e-12
    assert after["current"]["internal_energy_j"] == pytest.approx(before["internal_energy_j"])
    np.testing.assert_allclose(
        after["current"]["angular_momentum_kg_m2_s"], before["angular_momentum_kg_m2_s"], rtol=1e-12
    )
    assert w.tidal_potential_offset_j != 0
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert restored.tidal_potential_offset_j == w.tidal_potential_offset_j
    w.meta["1"]["inventory"] = BodyInventory((0, 0, 1))
    w.add_body(W.STAR, 1000, (4, 0, 0), (0, 1, 0), inventory=BodyInventory((0, 0, 1)))
    count = w.sim.N
    w._disrupt(str(w._next_id - 1), "1")
    assert w.paused and w.sim.N == count and w.notices


@pytest.mark.parametrize("change", ["owner", "fields", "mass", "vector", "component", "energy", "storage", "offset"])
def test_invalid_flow_or_sampling_reference_cannot_be_restored(change):
    data = E.capture(captured(), E.DEFAULT_CAMERA)
    flow = data["accretion_flows"]["1"]
    if change == "owner":
        data["accretion_flows"]["2"] = data["accretion_flows"].pop("1")
    elif change == "fields":
        flow["extra"] = 0
    elif change == "mass":
        flow["mass_kg"] = 1e99
    elif change == "vector":
        flow["angular_momentum_kg_m2_s"] = []
    elif change == "component":
        flow["angular_momentum_kg_m2_s"][0] = float("nan")
    elif change == "energy":
        flow["energy_j"] = float("nan")
    elif change == "storage":
        data["accretion_flows"] = []
    else:
        data["tidal_potential_offset_j"] = float("nan")
    with pytest.raises(ValueError):
        E.restore(data)


def test_grazing_rebound_is_a_central_elastic_impulse_without_mass_or_spin_loss():
    incoming = rocky_pair(0.95, 0.9)
    result = gentle_rebound(*incoming, material="fluid_planets", body_types=(0, 0))
    assert result.classification.regime == "gentle_rebound"
    assert result.classification.interacting_fraction is None
    assert_closed(incoming, result.remnants)
    dx = np.subtract(incoming[1].position_m, incoming[0].position_m)
    before = np.subtract(incoming[1].velocity_m_s, incoming[0].velocity_m_s)
    after = np.subtract(result.remnants[1].velocity_m_s, result.remnants[0].velocity_m_s)
    assert np.dot(dx, after) == pytest.approx(-np.dot(dx, before), rel=1e-12)
    external = (GravitySource(1e30, 1e6, (1e9, 0, 0)),)
    assert couple_external_gravity(incoming, result.remnants, external, contact_impulse=True) == result.remnants
    with pytest.raises(ValueError, match="sampled positions"):
        couple_external_gravity(
            incoming, (replace(result.remnants[0], radius_m=1), result.remnants[1]), external, contact_impulse=True
        )
    with pytest.raises(ValueError):
        gentle_rebound(*rocky_pair(0.95, 2), material="fluid_planets", body_types=(0, 0))
