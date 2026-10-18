"""Physical reference problems in G=1 units, independent of playable presets.

All reference particles gravitate. Small collision radii deliberately isolate
point-mass dynamics from the sandbox's enlarged bodies. These tests establish
accuracy for these problems and horizons, not arbitrary astrophysical systems.
"""
from __future__ import annotations

import math
import time

import numpy as np

from diagnostics import totals
from world import ROCKY, World


def pair(position, velocity, masses=(1.0, 0.001)):
    world = World(seed=42)
    total = sum(masses)
    for mass, factor in zip(masses, (-masses[1] / total, masses[0] / total), strict=True):
        bid = world.add_body(ROCKY, mass, np.asarray(position) * factor, np.asarray(velocity) * factor)
        world.particle(str(bid)).r = 1e-5
    world.sim.dt = 0.001
    return world


def samples(world, duration, count=200):
    """Use the live World stepping path; compare at actual (possibly overshot) time."""
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


def kepler(eccentricity=0.0, periods=20):
    mu = 1.001
    period = 2 * math.pi / math.sqrt(mu)  # semimajor axis = 1
    world = pair((1 - eccentricity, 0, 0),
                 (0, math.sqrt(mu * (1 + eccentricity) / (1 - eccentricity)), 0))
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


def hierarchical():
    world = pair((1, 0, 0), (0, math.sqrt(1.001), 0))
    planet = world.particle('2')
    pos = np.array([planet.x + 0.02, planet.y, planet.z])
    vel = np.array([planet.vx, planet.vy + math.sqrt(0.001001 / 0.02), planet.vz])
    moon = world.add_body(ROCKY, 1e-6, pos, vel)
    world.particle(str(moon)).r = 1e-5
    world.sim.move_to_com()
    initial = totals(world)
    errors = dict(mass=0.0, momentum=0.0, angular_momentum=0.0, energy=0.0, moon_radius_fraction=0.0)
    for snap, current in samples(world, 20 * 2 * math.pi / math.sqrt(1.001), count=400):
        observed = invariant_errors(initial, current)
        observed['moon_radius_fraction'] = abs(float(np.linalg.norm(snap['xyz'][2] - snap['xyz'][1])) / 0.02 - 1)
        errors = {key: max(errors[key], observed[key]) for key in errors}
    return result('hierarchical_moon', errors,
                  dict(mass=1e-12, momentum=1e-10, angular_momentum=1e-10, energy=1e-9,
                       moon_radius_fraction=0.1), world.sim.t, world.sim.N)


def merger():
    world = pair((0.2, 0, 0), (-0.05, 0, 0), masses=(0.003, 0.002))
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
    return [kepler(), kepler(0.6), scattering(), hierarchical(), merger()]
