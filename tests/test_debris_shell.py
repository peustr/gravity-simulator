"""Compact shell evolution against resolved Newtonian references."""

from dataclasses import replace
import math
import time

import numpy as np
import pytest
import rebound

from collision_outcomes import SphereState, collision_budget
from debris_shell import (
    EjectaShell,
    ShellIntegrator,
    form_shell,
    shell_energy,
    shell_potential,
    symmetric_directions,
    approaching_contacts,
    model_defect,
)
from diagnostics import conservation_report
import experiments as E
import units as U
import world as W


def shell_fixture(count=20):
    primary = SphereState(1e22, 1e5, (0, 0, 0), (0, 0, 0))
    states = tuple(
        SphereState(1e22 / count, 1e4, 1e7 * direction, 1e3 * direction) for direction in symmetric_directions(count)
    )
    return primary, states, form_shell(primary, states, 1)


def advance(world, target):
    world.speed = 1
    deadline = time.perf_counter() + 5
    while world.sim.t < target - 1e-12 and not world.paused:
        assert time.perf_counter() < deadline, (world.sim.t, world.notices, world.solver_name())
        world.advance(min(0.01, target - world.sim.t), time.perf_counter() + 0.1)


@pytest.mark.parametrize("count", [4, 6, 8, 12, 20, 30])
def test_symmetric_geometry_is_centred_radial_and_has_closed_budget(count):
    primary, states, shell = shell_fixture(count)
    assert len(states) == count
    assert np.linalg.norm(np.mean([s.position_m for s in states], axis=0)) < 1e-8
    assert shell.initial_force_residual_m_s2 < 1e-12 * U.G_SI * shell.mass_kg / shell.radius_m**2
    before = collision_budget((primary, *states))
    assert shell.mass_kg + primary.mass_kg == pytest.approx(before.mass_kg, rel=1e-14)
    assert shell.self_binding_j + shell_energy((shell,), (primary.mass_kg,), (primary.position_m,)) == pytest.approx(
        before.energy_j - primary.self_binding_j, rel=1e-13
    )


@pytest.mark.parametrize("star", [False, True])
def test_live_smash_capacity_does_not_change_regime_or_lose_inventories(star):
    worlds = []
    for capacity in (32, 3 if star else 2):
        w = W.World(max_bodies=capacity, seed=42)
        w.load_preset("smash")
        if star:
            w.add_body(W.STAR, 1000, (60, 0, 0), (0, 0, 0))
        conservation_report(w)
        advance(w, 0.35)
        assert not w.paused and not w.notices
        worlds.append(w)
    full, compact = worlds
    assert full.sim.N == 21 + star and compact.sim.N == 1 + star
    assert len(compact.shells) == 1
    shell = compact.shells[0]
    primary = full.particle("1")
    excluded = {"1", "3"} if star else {"1"}
    radii = [math.dist(p.xyz, primary.xyz) for p in full.sim.particles if p.name not in excluded]
    assert abs(np.mean(radii) / (shell.radius_m / U.LENGTH_M) - 1) < (1e-5 if star else 1e-10)
    assert shell.fragment_count == 20 and compact.events[-1][0] == W.EV_SHATTER
    report = conservation_report(compact)
    assert abs(report["relative_energy_change"]) < 1e-9
    np.testing.assert_allclose(compact.particle("1").xyz, primary.xyz, atol=1e-6, rtol=0)
    assert report["current"]["mass_kg"] == pytest.approx(conservation_report(full)["current"]["mass_kg"], rel=1e-14)
    data = E.capture(compact, E.DEFAULT_CAMERA)
    restored, _ = E.restore(data)
    assert restored.shells == compact.shells
    assert restored.shell_numerical_energy_error_j == compact.shell_numerical_energy_error_j
    advance(restored, 0.45)
    advance(compact, 0.45)
    assert not restored.paused and not compact.paused
    np.testing.assert_allclose(restored.snapshot()["xyz"], compact.snapshot()["xyz"], atol=1e-10)
    assert restored.shells[0].radius_m == pytest.approx(compact.shells[0].radius_m, rel=1e-10)
    with pytest.raises(ValueError):
        compact.configure(dict(gravity="tracers"))
    assert compact.settings["gravity"] == "full"
    with pytest.raises(ValueError):
        compact.configure(dict(collisions="heuristic"))
    assert compact.settings["collisions"] == "auto"


def test_shell_kernel_matches_shell_theorem_inside_and_outside():
    primary, states, shell = shell_fixture()
    for distance in (0, shell.radius_m / 2, shell.radius_m, 2 * shell.radius_m):
        assert shell_potential(shell, primary.mass_kg, (distance, 0, 0)) == pytest.approx(
            -U.G_SI * shell.mass_kg * primary.mass_kg / max(distance, shell.radius_m)
        )
    with pytest.raises(ValueError, match="intersects"):
        model_defect(shell, [primary.mass_kg], [(shell.radius_m, 0, 0)], [primary.radius_m])
    far = model_defect(shell, [primary.mass_kg], [(10 * shell.radius_m, 0, 0)], [primary.radius_m])
    near = model_defect(shell, [primary.mass_kg], [(shell.radius_m / 2, 0, 0)], [primary.radius_m])
    assert far > 0 and near > far


@pytest.mark.parametrize(
    "change",
    [
        dict(identifier=0),
        dict(fragment_count=3),
        dict(mass_kg=-1),
        dict(radius_m=0),
        dict(radius_m=1),
        dict(internal_energy_j=-1),
        dict(potential_offset_j=math.nan),
        dict(centre_m=(1, 2)),
        dict(centre_m=(0, 0, math.inf)),
        dict(formed_at_s=-1),
        dict(omitted_impulse_m_s=6),
        dict(regime="merging"),
    ],
)
def test_invalid_shell_states_are_rejected(change):
    _, _, shell = shell_fixture()
    with pytest.raises(ValueError):
        replace(shell, **change)


def test_nonhomologous_or_spinning_material_is_not_compressed():
    primary, states, shell = shell_fixture(4)
    with pytest.raises(ValueError, match="four"):
        form_shell(primary, states[:2], 1)
    with pytest.raises(ValueError, match="homologous"):
        form_shell(primary, (replace(states[0], velocity_m_s=(0, 0, 0)), *states[1:]), 1)
    with pytest.raises(ValueError, match="homologous"):
        form_shell(primary, (replace(states[0], spin_kg_m2_s=(1, 0, 0)), *states[1:]), 1)
    with pytest.raises(ValueError):
        symmetric_directions(31)


def test_packet_contains_a_bounded_noninteractive_cloud_and_no_native_ghost_mass():
    import server as S

    w = W.World(max_bodies=2, seed=42)
    w.load_preset("smash")
    advance(w, 0.2)
    data = np.frombuffer(S.pack_state(w), dtype="<f4")
    assert w.sim.N == 1 and data[4] == 2
    records = data[11 : 11 + 24].reshape(2, 12)
    assert records[0, 0] == 1 and records[1, 0] == -2 and records[1, 1] == W.PLASMA
    assert records[:, 8].sum() == pytest.approx(0.0056, rel=1e-6)
    assert records[1, 9] == pytest.approx(w.shells[0].radius_m / U.LENGTH_M, rel=1e-6)


def test_full_store_refuses_new_material_atomically_but_allows_a_supported_merger():
    from copy import deepcopy
    from debris_shell import MAX_SHELLS

    _, _, template = shell_fixture()
    w = W.World(max_bodies=2, seed=42)
    w.load_preset("smash")
    a, b = w.sim.particles
    contact = a.r + b.r
    a.xyz = (-contact / 2, 0, 0)
    b.xyz = (contact / 2, 0, 0)
    w.shells = tuple(
        replace(template, identifier=i + 1, centre_m=((i + 1) * 1000 * U.LENGTH_M, 0, 0)) for i in range(MAX_SHELLS)
    )
    w._next_shell_id = MAX_SHELLS + 1
    record = w._collision_record(a, b)[2]
    before = deepcopy(E.capture(w, E.DEFAULT_CAMERA))
    with pytest.raises(ValueError, match="reservoir capacity"):
        w._apply_isolated_collision(record)
    assert E.capture(w, E.DEFAULT_CAMERA) == before
    a.vxyz = (0.05, 0, 0)
    b.vxyz = (-0.05, 0, 0)
    record = w._collision_record(a, b)[2]
    mass = conservation_report(w)["current"]["mass_kg"]
    w._apply_isolated_collision(record)
    assert w.sim.N == 1 and len(w.shells) == MAX_SHELLS
    assert conservation_report(w)["current"]["mass_kg"] == pytest.approx(mass, rel=1e-14)
    assert w._next_shell_id == MAX_SHELLS + 1


def test_exhausted_model_budget_keeps_live_states_and_inventories_unchanged():
    w = W.World(max_bodies=2, seed=42)
    w.load_preset("smash")
    advance(w, 0.2)
    shell = w.shells[0]
    w.shells = (replace(shell, initial_force_residual_m_s2=1e6),)
    w._shell_integrator = None
    before = w.snapshot()
    time_before = w.sim.t
    shells_before = w.shells
    inventories = [md["inventory"] for md in w.meta.values()]
    w.advance(0.01, time.perf_counter() + 1)
    assert w.paused and "omitted-impulse" in w.notices[-1]["text"]
    assert w.sim.t == time_before and w.shells == shells_before
    np.testing.assert_array_equal(w.snapshot()["xyz"], before["xyz"])
    np.testing.assert_array_equal(w.snapshot()["v"], before["v"])
    assert [md["inventory"] for md in w.meta.values()] == inventories
    assert w.shell_error_history['refused_steps'] == 1
    assert 'omitted-impulse' in w.shell_error_history['last_refusal']
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert restored.shell_error_history == w.shell_error_history


def test_cloud_only_motion_and_whole_shell_boundary_removal_close_budgets():
    from diagnostics import totals
    from server import Server

    w = W.World(max_bodies=2, seed=42)
    w.load_preset("smash")
    advance(w, 0.2)
    service = Server("127.0.0.1", 0, w)
    service.send_json = lambda *args: None
    try:
        conservation_report(w, reset=True)
        with pytest.warns(RuntimeWarning, match="Last particle removed"):
            service.handle(dict(cmd="remove", id=1), ("127.0.0.1", 1234))
        initial_radius = w.shells[0].radius_m
        advance(w, 0.3)
        assert not w.paused and w.sim.N == 0 and w.shells[0].radius_m > initial_radius
        report = conservation_report(w)
        assert abs(report["conservation_residual"]["mass_kg"]) < 1e-12 * report["baseline"]["mass_kg"]
        assert abs(report["relative_conservation_residual"]) < 1e-9
        restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
        assert restored.shells == w.shells
        assert restored.physical_loss_ledger.state() == w.physical_loss_ledger.state()
        assert totals(w)["mass"] == pytest.approx(w.shells[0].mass_kg / U.MASS_KG)
        w.configure(dict(escape_distance=0.1))
        w._cull_escapers()
        assert not w.shells and w.removed["bodies"] == 20
        restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
        assert restored.shell_error_history == w.shell_error_history
        report = conservation_report(w)
        assert report["current"]["mass_kg"] == 0
        assert abs(report["conservation_residual"]["mass_kg"]) < 1e-12 * report["baseline"]["mass_kg"]
        assert abs(report["relative_conservation_residual"]) < 1e-9
    finally:
        service.sock.close()


def test_forecast_evolves_unresolved_gravity_without_mutating_the_live_shell():
    w = W.World(max_bodies=2, seed=42)
    w.load_preset("smash")
    advance(w, 0.2)
    before = E.capture(w, E.DEFAULT_CAMERA)
    result = w.predict(W.ROCKY, (10, 0, 0), "launch", (-0.1, 0, 0), 0.0001, samples=10, wall_budget=1)
    assert result["points"] and len(result["points"]) > 1
    assert E.capture(w, E.DEFAULT_CAMERA) == before


def test_packet_with_maximum_bodies_and_reservoirs_defers_events_instead_of_oversizing():
    import server as S
    from debris_shell import MAX_SHELLS

    w = W.World(max_bodies=W.MAX_BODIES)
    for i in range(W.MAX_BODIES):
        w.add_body(W.ASTEROID, 0.00001, (i + 1, 0, 0), (0, 0, 0))
    _, _, shell = shell_fixture()
    w.shells = tuple(replace(shell, identifier=i + 1, centre_m=(0, (i + 1) * 1e10, 0)) for i in range(MAX_SHELLS))
    w.events = [(W.EV_SHATTER, 0, 0, 0, 1, 1, 1, 2)] * 64
    packet = S.pack_state(w)
    header = np.frombuffer(packet, dtype="<f4")[:11]
    assert len(packet) <= 65507 and header[4] == W.MAX_BODIES + MAX_SHELLS
    assert int(header[5]) + len(w.events) == 64 and w.events


@pytest.mark.parametrize("nested", [False, True])
def test_joint_shell_gravity_has_reaction_and_preserves_dynamic_energy(nested):
    _, _, a = shell_fixture()
    if nested:
        b = replace(
            a,
            identifier=2,
            radius_m=100 * a.radius_m,
            initial_radius_m=100 * a.radius_m,
            initial_force_residual_m_s2=a.initial_force_residual_m_s2 / 10000,
        )
    else:
        b = replace(a, identifier=2, centre_m=(1e11, 0, 0))
    sim = rebound.Simulation()
    driver = ShellIntegrator(sim, (a, b), 1e-9)
    before = shell_energy((a, b), [], [])
    shells = (a, b)
    while sim.t < 0.003 - 1e-15:
        shells = driver.advance(sim, shells, 0.003 - sim.t)
    after = shell_energy(shells, [], [])
    assert after == pytest.approx(before, rel=1e-10)
    momentum = sum((s.mass_kg * np.array(s.velocity_m_s) for s in shells), np.zeros(3))
    assert np.linalg.norm(momentum) < 1e10
    if nested:
        assert shells[0].centre_m == shells[1].centre_m
    else:
        assert shells[0].velocity_m_s[0] > 0 > shells[1].velocity_m_s[0]


def test_intersecting_shells_are_refused_before_advancing_either_owner():
    _, _, a = shell_fixture()
    b = replace(a, identifier=2, centre_m=(a.radius_m, 0, 0))
    sim = rebound.Simulation()
    driver = ShellIntegrator(sim, (a, b), 1e-9)
    with pytest.raises(ValueError, match="Intersecting"):
        driver.advance(sim, (a, b), 0.001)
    assert sim.t == 0 and a.centre_m == (0, 0, 0)
    with pytest.raises(ValueError, match="Intersecting"):
        shell_energy((a, b), [], [])


def test_nonadvancing_or_corrupted_solver_trials_never_commit_to_native_particles(monkeypatch):
    primary, _, shell = shell_fixture()
    sim = rebound.Simulation()
    sim.add(m=primary.mass_kg / U.MASS_KG, r=primary.radius_m / U.LENGTH_M)
    driver = ShellIntegrator(sim, (shell,), 1e-9)
    with monkeypatch.context() as context:
        context.setattr(rebound.Simulation, "steps", lambda owner, n: None)
        with pytest.raises(ArithmeticError, match="did not advance"):
            driver.advance(sim, (shell,), 0.001)
    assert sim.t == 0 and sim.particles[0].x == 0
    driver = ShellIntegrator(sim, (shell,), 1e-9)
    native_step = rebound.Simulation.steps

    def corrupt(owner, n):
        native_step(owner, n)
        driver.ode.y[0] += 1

    monkeypatch.setattr(rebound.Simulation, "steps", corrupt)
    with pytest.raises(ValueError, match="numerical energy"):
        driver.advance(sim, (shell,), 0.001)
    assert sim.t == 0 and sim.particles[0].x == 0


def test_bs_fallback_advances_a_zero_ias15_step_with_unchanged_force_law():
    from dynamics import ContactGuard, step

    sim = rebound.Simulation()
    sim.add(m=1, r=0.01, x=-1)
    sim.add(m=1, r=0.01, x=1)
    sim.dt = 0
    step(sim, 0.01, ContactGuard())
    assert str(sim.integrator) == "bs" and sim.t > 0
    reference = rebound.Simulation()
    reference.integrator = "bs"
    reference.integrator.eps_rel = 1e-13
    reference.integrator.eps_abs = 1e-15
    reference.add(m=1, r=0.01, x=-1)
    reference.add(m=1, r=0.01, x=1)
    reference.integrate(sim.t)
    assert sim.particles[0].x == pytest.approx(reference.particles[0].x, rel=1e-11)
    assert sim.particles[0].vx == pytest.approx(reference.particles[0].vx, rel=1e-10)


def test_native_contact_scan_matches_approaching_overlaps_and_ignores_separation():
    sim = rebound.Simulation()
    sim.add(m=1, r=1, x=-0.5, vx=1)
    sim.add(m=1, r=1, x=0.5, vx=-1)
    assert list(approaching_contacts(sim)) == [(0, 1)]
    sim.particles[1].vx = 2
    assert not list(approaching_contacts(sim))


@pytest.mark.parametrize(
    "field,value",
    [
        ("identifier", True),
        ("fragment_count", 5),
        ("self_coefficient", 0.9),
        ("self_binding_j", 0),
        ("internal_energy_j", math.inf),
        ("initial_speed_m_s", 0),
    ],
)
def test_saved_shell_geometry_and_inventories_are_validated_together(field, value):
    from dataclasses import asdict

    _, _, shell = shell_fixture()
    data = asdict(shell)
    data[field] = value
    with pytest.raises(ValueError):
        EjectaShell(**data)


@pytest.mark.parametrize('fault', ['radius', 'body_surface', 'shell_surface'])
def test_invalid_native_trial_stages_are_refused_without_committing(fault, monkeypatch):
    primary, _, shell = shell_fixture()
    sim = rebound.Simulation()
    sim.add(m=primary.mass_kg / U.MASS_KG, r=primary.radius_m / U.LENGTH_M)
    shells = (shell, replace(shell, identifier=2, centre_m=(1e11, 0, 0))) if fault == 'shell_surface' else (shell,)
    driver = ShellIntegrator(sim, shells, 1e-9)
    derivative = driver._derivatives

    def invalid_trial(ptr, destination, source, t):
        index = 12 if fault == 'radius' else (0 if fault == 'body_surface' else 15)
        previous = source[index]
        source[index] = -1 if fault == 'radius' else shell.radius_m / U.LENGTH_M
        try:
            derivative(ptr, destination, source, t)
        finally:
            source[index] = previous

    monkeypatch.setattr(driver, '_derivatives', invalid_trial)
    with pytest.raises(ValueError, match='domain|intersects|Intersecting'):
        driver.advance(sim, shells, 0.001)
    assert sim.t == 0 and sim.particles[0].xyz == [0, 0, 0]


@pytest.mark.parametrize('fault', [
    'units', 'solver', 'model', 'storage_type', 'storage_full', 'record_type', 'record_fields',
    'duplicate_owner', 'next_owner', 'tracer', 'heuristic', 'history_missing', 'refusal_type',
    'refusal_length', 'history_too_small', 'losses_missing', 'future_formation',
])
def test_corrupt_shell_saves_are_rejected_without_changing_the_source_world(fault):
    _, _, shell = shell_fixture()
    w = W.World()
    w.shells = (shell,)
    w._next_shell_id = 2
    before = E.capture(w, E.DEFAULT_CAMERA)
    from copy import deepcopy
    data = deepcopy(before)
    if fault in ('solver', 'units'):
        data[fault] = 'unknown'
    elif fault == 'model':
        data['shell_model'] = 'unknown'
    elif fault == 'storage_type':
        data['ejecta_shells'] = None
    elif fault == 'storage_full':
        data['ejecta_shells'] *= 9
    elif fault == 'record_type':
        data['ejecta_shells'] = [None]
    elif fault == 'record_fields':
        del data['ejecta_shells'][0]['mass_kg']
    elif fault == 'duplicate_owner':
        data['ejecta_shells'] *= 2
    elif fault == 'next_owner':
        data['next_shell_id'] = 1
    elif fault in ('tracer', 'heuristic'):
        data['physics']['gravity' if fault == 'tracer' else 'collisions'] = 'tracers' if fault == 'tracer' else 'heuristic'
    elif fault == 'history_missing':
        del data['shell_error_history']
    elif fault in ('refusal_type', 'refusal_length'):
        data['shell_error_history']['last_refusal'] = None if fault == 'refusal_type' else 'x' * 301
    elif fault == 'history_too_small':
        data['ejecta_shells'][0]['omitted_impulse_m_s'] = 1
    elif fault == 'losses_missing':
        del data['physical_loss_ledger']
    else:
        data['ejecta_shells'][0]['formed_at_s'] = 1
    with pytest.raises(ValueError):
        E.restore(data)
    assert E.capture(w, E.DEFAULT_CAMERA) == before


def test_supported_merger_inside_a_shell_runs_through_live_contact_and_forecast():
    from tools.impact_references import reference_world, PLANET_CASES
    w, _, lead = reference_world(PLANET_CASES[0])
    _, _, shell = shell_fixture()
    w.shells = (replace(shell, radius_m=1e12, initial_radius_m=1e12,
                        initial_force_residual_m_s2=shell.initial_force_residual_m_s2 * 1e-10),)
    w._next_shell_id = 2
    w.paused = False
    baseline = conservation_report(w)
    advance(w, lead + 0.001)
    assert not w.paused and w.sim.N == 1 and len(w.shells) == 1
    assert w.events[-1][0] == W.EV_MERGE and not w.notices
    report = conservation_report(w)
    assert report['current']['mass_kg'] == pytest.approx(baseline['current']['mass_kg'], rel=1e-14)
    assert abs(report['relative_conservation_residual']) < 1e-9
    p = w.sim.particles[0]
    forecast = w.predict(W.ROCKY, (3*p.r, 0, 0), 'launch', (-10, 0, 0), .01, samples=10, wall_budget=1)
    assert forecast['hit'] and np.isfinite(forecast['points']).all()
    assert w.sim.N == 1 and len(w.shells) == 1


def test_removing_a_shell_with_unknown_body_inventories_retains_known_losses():
    from diagnostics import Ledger
    _, _, shell = shell_fixture()
    w = W.World()
    w.shells = (shell,)
    w.add_body(W.ROCKY, .003, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, .003, (0, 0, 0), (0, 0, 0))
    w.meta['1']['inventory'] = None
    w.ledger = Ledger()
    w.configure(dict(escape_distance=0.0001))
    w._cull_escapers()
    assert not w.shells and w.sim.N == 2 and not w.removed['energy_defined']
    assert w.removed['mass'] == pytest.approx(shell.mass_kg/U.MASS_KG)
    assert w.physical_loss_ledger.totals['mass_kg'] == pytest.approx(shell.mass_kg)
    assert w.physical_loss_ledger.totals['energy_j'] is None and w.ledger.errors
