"""Physical reference problems in G=1 units, independent of playable presets.

Orbital references use small collision radii to isolate point-mass dynamics.
Contact and forecast cases exercise both active bodies and passive tracers.
Accuracy bounds apply to these problems and horizons.
"""
from __future__ import annotations

import math
import time

import numpy as np

from diagnostics import totals
from world import ASTEROID, BLACK_HOLE, ROCKY, World


def pair(position, velocity, masses=(1.0, 0.001)):
    world = World(seed=42)
    total = sum(masses)
    for mass, factor in zip(masses, (-masses[1] / total, masses[0] / total), strict=True):
        bid = world.add_body(ROCKY, mass, np.asarray(position) * factor, np.asarray(velocity) * factor)
        world.particle(str(bid)).r = 1e-5
    world.sim.dt = 0.001
    return world


def samples(world, duration, count=200):
    """Use the live World stepping path, including contact guards and tick limits."""
    deadline = time.perf_counter() + 30
    world.speed = max(10.0, duration / count * 4)
    for target in np.linspace(duration / count, duration, count):
        while world.sim.t < target:
            if time.perf_counter() > deadline:
                raise TimeoutError('Physical reference problem did not finish within 30 seconds')
            world.advance((target - world.sim.t) / world.speed, deadline)
        yield world.snapshot(), totals(world)


def invariant_errors(initial, current, length=1.0):
    # Normalise by characteristic nonzero scales, never by nearly zero net
    # momentum. Report absolute vector norms divided by M*v and M*v*length.
    p_scale = math.sqrt(2 * initial['mass'] * initial['kinetic_energy'])
    return dict(
        mass=abs(current['mass'] - initial['mass']) / initial['mass'],
        momentum=float(np.linalg.norm(np.subtract(current['momentum'], initial['momentum']))) / p_scale,
        angular_momentum=float(np.linalg.norm(np.subtract(current['angular_momentum'], initial['angular_momentum'])))
        / (p_scale * length),
        energy=abs(current['energy'] - initial['energy'])
        / (initial['kinetic_energy'] + abs(initial['potential_energy'])),
    )


def result(name, errors, limits, duration, bodies):
    return dict(name=name, errors=errors, limits=limits, simulated_time=duration, bodies=bodies,
                passed=all(math.isfinite(value) and value <= limits[key] for key, value in errors.items()))


def kepler(eccentricity=0.0, periods=20, epsilon=1e-9):
    mu = 1.001
    period = 2 * math.pi / math.sqrt(mu)  # semimajor axis = 1
    world = pair((1 - eccentricity, 0, 0),
                 (0, math.sqrt(mu * (1 + eccentricity) / (1 - eccentricity)), 0))
    world.configure(dict(epsilon=epsilon))
    initial = totals(world)
    errors = dict(mass=0.0, momentum=0.0, angular_momentum=0.0, energy=0.0, position=0.0)
    for snap, current in samples(world, periods * period, count=400):
        mean = math.sqrt(mu) * world.sim.t % (2 * math.pi)
        anomaly = mean
        for _ in range(15):
            anomaly -= (anomaly - eccentricity * math.sin(anomaly) - mean) / (1 - eccentricity * math.cos(anomaly))
        expected = np.array([math.cos(anomaly) - eccentricity,
                             math.sqrt(1 - eccentricity**2) * math.sin(anomaly), 0])
        actual = snap['xyz'][1] - snap['xyz'][0]
        observed = invariant_errors(initial, current)
        observed['position'] = float(np.linalg.norm(actual - expected))  # divided by a=1
        errors = {key: max(errors[key], observed[key]) for key in errors}
    return result('kepler_circular' if eccentricity == 0 else 'kepler_eccentric', errors,
                  dict(mass=1e-12, momentum=1e-10, angular_momentum=1e-10, energy=1e-10, position=1e-7),
                  world.sim.t, world.sim.N)


def scattering():
    # Hyperbola: |a|=1, e=1.5; start at r=5 on the incoming branch.
    eccentricity, mu = 1.5, 1.001
    anomaly0 = -math.acosh(6 / eccentricity)
    mean0 = eccentricity * math.sinh(anomaly0) - anomaly0

    def state(anomaly):
        denominator = eccentricity * math.cosh(anomaly) - 1
        return (np.array([eccentricity - math.cosh(anomaly),
                          math.sqrt(eccentricity**2 - 1) * math.sinh(anomaly), 0]),
                math.sqrt(mu) / denominator * np.array([-math.sinh(anomaly),
                          math.sqrt(eccentricity**2 - 1) * math.cosh(anomaly), 0]))

    world = pair(*state(anomaly0))
    initial = totals(world)
    errors = dict(mass=0.0, momentum=0.0, angular_momentum=0.0, energy=0.0, position=0.0, velocity=0.0)
    for snap, current in samples(world, -2 * mean0 / math.sqrt(mu)):
        mean = mean0 + math.sqrt(mu) * world.sim.t
        anomaly = math.asinh(mean / eccentricity)
        for _ in range(15):
            anomaly -= (eccentricity * math.sinh(anomaly) - anomaly - mean) / (eccentricity * math.cosh(anomaly) - 1)
        position, velocity = state(anomaly)
        observed = invariant_errors(initial, current)
        observed['position'] = float(np.linalg.norm(snap['xyz'][1] - snap['xyz'][0] - position))
        observed['velocity'] = float(np.linalg.norm(snap['v'][1] - snap['v'][0] - velocity)) / math.sqrt(mu)
        errors = {key: max(errors[key], observed[key]) for key in errors}
    return result('hyperbolic_scattering', errors,
                  dict(mass=1e-12, momentum=1e-10, angular_momentum=1e-10, energy=1e-10,
                       position=1e-7, velocity=1e-7), world.sim.t, world.sim.N)


def hierarchical_world():
    world = pair((1, 0, 0), (0, math.sqrt(1.001), 0))
    planet = world.particle('2')
    pos = np.array([planet.x + 0.02, planet.y, planet.z])
    vel = np.array([planet.vx, planet.vy + math.sqrt(0.001001 / 0.02), planet.vz])
    moon = world.add_body(ROCKY, 1e-6, pos, vel)
    world.particle(str(moon)).r = 1e-5
    world.sim.move_to_com()
    return world


def hierarchical(periods=20, epsilon=1e-9):
    world = hierarchical_world()
    world.configure(dict(epsilon=epsilon))
    initial = totals(world)
    errors = dict(mass=0.0, momentum=0.0, angular_momentum=0.0, energy=0.0, moon_radius_fraction=0.0)
    for snap, current in samples(world, periods * 2 * math.pi / math.sqrt(1.001), count=400):
        observed = invariant_errors(initial, current)
        observed['moon_radius_fraction'] = abs(float(np.linalg.norm(snap['xyz'][2] - snap['xyz'][1])) / 0.02 - 1)
        errors = {key: max(errors[key], observed[key]) for key in errors}
    outcome = result('hierarchical_moon', errors,
                  dict(mass=1e-12, momentum=1e-10, angular_momentum=1e-10, energy=1e-9,
                       moon_radius_fraction=0.1), world.sim.t, world.sim.N)
    outcome['final_relative_positions'] = (snap['xyz'][1:] - snap['xyz'][0]).tolist()
    return outcome


def merger():
    world = pair((0.2, 0, 0), (-0.05, 0, 0), masses=(0.003, 0.002))
    world.configure(dict(collisions='heuristic'))  # Prescribed perfectly inelastic reference.
    for p in world.sim.particles:
        p.r = 0.01
        p.vz += 0.2
    initial = totals(world)
    current = initial
    for _snap, measured in samples(world, 3.0, count=60):
        current = measured
    measured = invariant_errors(initial, current)
    # A perfectly inelastic merger dissipates mechanical energy. No assertion
    # of energy conservation or of unmodelled spin angular momentum is made.
    errors = dict(mass=measured['mass'], momentum=measured['momentum'], body_count=abs(world.sim.N - 1))
    return result('inelastic_merger', errors, dict(mass=1e-12, momentum=1e-10, body_count=0),
                  world.sim.t, world.sim.N)


def run_accuracy():
    return [kepler(), kepler(0.6), scattering(), hierarchical(), merger(),
            long_duration(), contact_accuracy(), symplectic_evaluation(), forecast_accuracy()]


def long_duration():
    """Long-horizon drift and tolerance convergence through the live solver."""
    circular, eccentric = kepler(periods=1000), kepler(0.6, periods=1000)
    loose = kepler(0.8, periods=100, epsilon=1e-6)
    normal = kepler(0.8, periods=100)
    tight = kepler(0.8, periods=100, epsilon=1e-12)
    hierarchy = hierarchical(periods=100)
    reference = hierarchical(periods=100, epsilon=1e-12)
    separation = float(np.max(np.linalg.norm(np.subtract(hierarchy['final_relative_positions'],
                                                         reference['final_relative_positions']), axis=1)))
    errors = dict(circular_position=circular['errors']['position'], eccentric_position=eccentric['errors']['position'],
                  energy=max(circular['errors']['energy'], eccentric['errors']['energy'], hierarchy['errors']['energy']),
                  normal_position=normal['errors']['position'], tight_position=tight['errors']['position'],
                  hierarchy_difference=separation,
                  convergence=max(normal['errors']['position'], tight['errors']['position']) / max(loose['errors']['position'], 1e-8))
    outcome = result('long_duration_and_convergence', errors,
                     dict(circular_position=1e-6, eccentric_position=1e-6, energy=1e-9,
                          normal_position=1e-7, tight_position=1e-7, hierarchy_difference=1e-6, convergence=1.0),
                     circular['simulated_time'], 3)
    outcome['tolerance_sweep'] = [dict(epsilon=epsilon, position=case['errors']['position'], energy=case['errors']['energy'])
                                   for epsilon, case in ((1e-6, loose), (1e-9, normal), (1e-12, tight))]
    return outcome


def forecast_accuracy():
    """Compare all-body forecasts to the live world with matching force settings.

    The deadline is generous here to isolate physical fidelity. Latency is
    measured separately by the interactive-budget benchmark workloads.
    """
    rows = []
    for gravity, limit in (('tracers', 0), ('full', 0), ('full', 20)):
        w = World(seed=42)
        w.configure(dict(gravity=gravity, forecast_limit=limit, escape_distance=None))
        w.add_body(ROCKY, 1, (0, 0, 0), (0, 0, 0))
        w.add_body(ROCKY, .001, (1, 0, 0), (0, math.sqrt(1.001), 0))
        # Collective debris deliberately large enough to make the force choice
        # measurable; distinct, distant bodies avoid contacts during this test.
        for k in range(24):
            angle = k * 2 * math.pi / 24
            w.add_body(ASTEROID, .0001, (3 * math.cos(angle), 3 * math.sin(angle), .2), (0, 0, 0))
        position = (1.02, 0, 0)
        preview = w.predict(ASTEROID, position, 'orbit', (0, 0, 0), .05, samples=80, wall_budget=10)
        attractor = str(preview['attractor'])
        origin = np.array(w.particle(attractor).xyz)
        bid = w.spawn(ASTEROID, position, mass_mult=.05)
        worst = 0.0
        w.speed = 10
        for t, predicted in zip(preview['times'][1:], preview['points'][1:], strict=True):
            w.advance((t - w.sim.t) / w.speed, time.perf_counter() + 10)
            relative = np.array(w.particle(str(bid)).xyz) - w.particle(attractor).xyz + origin
            worst = max(worst, float(np.linalg.norm(relative - predicted)))
        rows.append(dict(gravity=gravity, forecast_limit=limit, position_error=worst,
                         complete=preview['complete'], omitted_bodies=preview['omitted_bodies'],
                         omitted_active_mass=preview['omitted_active_mass']))
    errors = dict(full_state_error=max(row['position_error'] for row in rows[:2]),
                  incomplete=sum(not row['complete'] for row in rows))
    outcome = result('forecast_force_consistency', errors, dict(full_state_error=1e-7, incomplete=0), w.sim.t, w.sim.N)
    outcome['cases'] = rows
    outcome['domain'] = 'One moon orbit in a perturbed system. The limited forecast error is measured, not bounded in general; paths stop at first contact.'
    return outcome


def symplectic_evaluation():
    """WHFast evaluation only; no live solver switching or close encounters."""
    rows = []
    period = 2 * math.pi / math.sqrt(1.001)
    for solver, subdivisions in (('ias15', 0), ('whfast', 40), ('whfast', 80)):
        world = pair((1, 0, 0), (0, math.sqrt(1.001), 0))
        world.add_body(ROCKY, 3e-4, (1.8, 0, 0), (0, math.sqrt(1 / 1.8), 0))
        world.sim.move_to_com()
        world._repartition()
        sim = world.sim
        sim.collision = 'none'
        sim.integrator = solver
        if subdivisions:
            sim.dt = period / subdivisions
        initial = totals(world)
        worst = 0.0
        start = time.perf_counter()
        for target in np.arange(1, 201) * period:
            sim.integrate(float(target), exact_finish_time=0)
            worst = max(worst, invariant_errors(initial, totals(world))['energy'])
        elapsed = time.perf_counter() - start
        rows.append(dict(solver=solver, steps_per_inner_orbit=subdivisions, energy=worst,
                         wall_seconds=elapsed, simulated_time=sim.t))
    # Energy-error convergence is the gate; timing is a machine-specific measurement.
    errors = dict(ias15_energy=rows[0]['energy'], whfast_energy=rows[2]['energy'],
                  refinement=rows[2]['energy'] / max(rows[1]['energy'], 1e-20))
    outcome = result('symplectic_planetary_evaluation', errors,
                     dict(ias15_energy=1e-10, whfast_energy=1e-5, refinement=0.5), rows[0]['simulated_time'], 3)
    outcome['runs'] = rows
    outcome['domain'] = 'Two well-separated planets for 200 inner orbits; no collisions, moons or close encounters. IAS15 remains the live solver.'
    return outcome


def contact_accuracy():
    """Ballistic contact geometry and analytic radial free fall, at varied dt/tolerance."""
    errors = dict(missed=0, false_contacts=0, penetration=0.0, timing=0.0, capture_speed=0.0)
    cases = []
    for epsilon in (1e-9, 1e-12):
        for initial_dt in (1e-6, 1.0):
            for geometry in ('head_on', 'grazing', 'near_miss', 'capture', 'receding_capture'):
                w = World(seed=42)
                w.configure(dict(epsilon=epsilon, escape_distance=None, gravity='tracers'))
                if geometry in ('capture', 'receding_capture'):
                    outward = 10.0 if geometry == 'receding_capture' else 0.0
                    w.add_body(BLACK_HOLE, 20000, (0, 0, 0), (0, 0, 0))
                    w.add_body(ASTEROID, 2e-5, (20, 0, 0), (outward, 0, 0))
                    radius = sum(p.r for p in w.sim.particles)
                    apocentre = 1 / (1 / 20 - outward**2 / 40000)
                    def fall_time(distance, apocentre=apocentre):
                        ratio = distance / apocentre
                        return math.sqrt(apocentre**3 / 40000) * (math.acos(math.sqrt(ratio)) + math.sqrt(ratio * (1 - ratio)))
                    expected_time = fall_time(radius) + fall_time(20)
                    expected_speed = math.sqrt(40000 * (1 / radius - 1 / apocentre))
                    duration = 1.2
                else:
                    # Two passive tracers have exactly rectilinear motion.
                    speed = 10000.0
                    radius = 0.02
                    offset = radius * dict(head_on=0.0, grazing=0.999, near_miss=1.001)[geometry]
                    w.add_body(ASTEROID, 1e-8, (0, 0, 0), (0, 0, 0))
                    w.add_body(ASTEROID, 1e-8, (-1, offset, 0), (speed, 0, 0))
                    for particle in w.sim.particles:
                        particle.r = radius / 2
                    expected_time = (1 - math.sqrt(max(0, radius**2 - offset**2))) / speed
                    expected_speed = speed
                    duration = 2 / speed
                contacts = []
                original = w._resolve_collision
                def record(ptr, collision, contacts=contacts, original=original):
                    sim = ptr.contents
                    a, b = sim.particles[collision.p1], sim.particles[collision.p2]
                    contacts.append((sim.t, math.dist(a.xyz, b.xyz), math.dist(a.vxyz, b.vxyz)))
                    return original(ptr, collision)
                w.sim.collision_resolve = record
                w.sim.dt = initial_dt
                w.speed = 10
                w.advance(duration / w.speed, time.perf_counter() + 10)
                hit = geometry != 'near_miss'
                errors['missed'] += int(hit and not contacts)
                errors['false_contacts'] += int(not hit and bool(contacts))
                if contacts:
                    t, separation, speed = contacts[0]
                    errors['penetration'] = max(errors['penetration'], abs(separation / radius - 1))
                    # Time error scaled by the surface-crossing time, including grazing cases.
                    errors['timing'] = max(errors['timing'], abs(t - expected_time) * expected_speed / radius)
                    if geometry in ('capture', 'receding_capture'):
                        errors['capture_speed'] = max(errors['capture_speed'], abs(speed / expected_speed - 1))
                cases.append(dict(geometry=geometry, epsilon=epsilon, initial_dt=initial_dt, contacts=len(contacts)))
    outcome = result('contact_detection', errors,
                     dict(missed=0, false_contacts=0, penetration=1e-4, timing=0.002, capture_speed=1e-4), 1.0, 2)
    outcome['cases'] = cases
    return outcome
