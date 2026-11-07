"""Symmetric weak-tide kicks around native adaptive gravitational steps.

An implicit midpoint solve in the tidal tensor's low-rank velocity space
exchanges orbit/spin momentum and deposits its exact positive kick dissipation.
Trial states stay separate until the complete step passes its domain/energy gates.
"""

import math
import time
import numpy as np
import rebound

from dynamics import step
from dynamics import _pairs
from equilibrium_tides import linear_response, potential, validate_motion
import units as U


class TidalIntegrator:
    def __init__(self, sim, profiles, epsilon, phase_limit=0.2):
        self.phase_limit = phase_limit
        self.profiles = tuple(profiles)
        self.omegas = np.array([p[2] for p in profiles])
        self.heating = np.zeros(len(profiles))
        self.masses = np.array([p.m for p in sim.particles]) * U.MASS_KG
        self.radii = np.array([p.r for p in sim.particles]) * U.LENGTH_M
        self.inertias = np.array([0.4 * self.masses[i] * self.radii[i] ** 2 for i, _, _ in profiles])
        self.roots = np.sqrt(np.concatenate((np.repeat(self.masses, 3), np.repeat(self.inertias, 3))))
        self.n = sim.N
        i, j = _pairs(self.n)
        active = self.n if sim.N_active < 0 else sim.N_active
        included = (i < active) | (j < active)
        self.pairs = i[included], j[included]
        self.context = rebound.Simulation()
        self.context.G = sim.G
        self.context.integrator = "ias15"
        self.context.integrator.epsilon = epsilon
        for p in sim.particles:
            self.context.add(m=p.m, r=p.r)
        self.context.N_active = sim.N_active
        self.context.testparticle_type = sim.testparticle_type
        self.contact = False

        def stop_at_contact(ptr, collision):
            self.contact = True
            ptr.contents.stop()
            return 0

        self.context.collision = "direct"
        self.context.collision_resolve = stop_at_contact

    def kick(self, positions, velocities, omegas, seconds):
        size = 3 * (self.n + len(self.profiles))
        rows, static, checks = [], np.zeros(size), []
        z = np.concatenate((velocities.reshape(-1), omegas.reshape(-1)))
        for k, (index, material, _) in enumerate(self.profiles):
            mapping, force, coefficient, _, norm = linear_response(
                self.masses, positions, index, self.radii[index], material
            )
            local = np.concatenate((velocities.reshape(-1), omegas[k]))
            validate_motion(self.masses[index], self.radii[index], omegas[k], material.lag_s, mapping @ local, norm)
            checks.append((mapping, norm))
            full = np.zeros((9, size))
            full[:, : 3 * self.n] = mapping[:, : 3 * self.n]
            full[:, 3 * (self.n + k) : 3 * (self.n + k + 1)] = mapping[:, -3:]
            static[: 3 * self.n] += force[: 3 * self.n]
            static[3 * (self.n + k) : 3 * (self.n + k + 1)] += force[-3:]
            rows.append(math.sqrt(coefficient * material.lag_s) * full / self.roots)
        matrix = np.vstack(rows)
        weighted = z * self.roots
        rhs = weighted + 0.5 * seconds * static / self.roots
        solution = np.linalg.solve(np.eye(len(matrix)) + 0.5 * seconds * (matrix @ matrix.T), matrix @ rhs)
        midpoint = rhs - 0.5 * seconds * (matrix.T @ solution)
        derivative = matrix @ midpoint
        weighted += seconds * (static / self.roots - matrix.T @ derivative)
        result = weighted / self.roots
        for k, (index, material, _) in enumerate(self.profiles):
            mapping, norm = checks[k]
            local = np.concatenate((result[: 3 * self.n], result[3 * (self.n + k) : 3 * (self.n + k + 1)]))
            validate_motion(self.masses[index], self.radii[index], local[-3:], material.lag_s, mapping @ local, norm)
        heating = seconds * np.sum(derivative.reshape(-1, 9) ** 2, axis=1)
        return result[: 3 * self.n].reshape(-1, 3), result[3 * self.n :].reshape(-1, 3), heating

    def energy(self, positions, velocities, omegas):
        values = [
            0.5 * float(np.sum(self.masses[:, None] * velocities**2)),
            0.5 * float(np.sum(self.inertias[:, None] * omegas**2)),
        ]
        i, j = self.pairs
        values.append(
            -U.G_SI
            * float(np.sum(self.masses[i] * self.masses[j] / np.linalg.norm(positions[j] - positions[i], axis=1)))
        )
        for index, material, _ in self.profiles:
            values.append(potential(self.masses, positions, index, self.radii[index], material))
        return math.fsum(values), math.fsum(abs(v) for v in values)

    def advance(self, sim, maximum, guard, deadline=math.inf):
        original = np.empty(6 * self.n)
        sim.serialize_particle_data(xyzvxvyvz=original)
        initial = original.reshape(-1, 6)
        positions, velocities = initial[:, :3] * U.LENGTH_M, initial[:, 3:] * U.VELOCITY_M_S
        before, scale = self.energy(positions, velocities, self.omegas)
        for index, _, _ in self.profiles:
            keep = np.arange(self.n) != index
            distance = np.linalg.norm(initial[keep, :3] - initial[index, :3], axis=1)
            rate = np.maximum(
                np.linalg.norm(initial[keep, 3:] - initial[index, 3:], axis=1) / distance,
                np.sqrt(sim.G * (self.masses[index] + self.masses[keep]) / U.MASS_KG / distance**3),
            )
            maximum = min(maximum, float(np.min(self.phase_limit / rate, initial=math.inf)))
        h = maximum
        if h <= 0 or sim.t + h == sim.t:
            raise ArithmeticError("Tidal step is below time resolution")
        clipped = False
        for _ in range(24):
            first, omega1, heat1 = self.kick(positions, velocities, self.omegas, 0.5 * h * U.TIME_S)
            trial = initial.copy()
            trial[:, 3:] = first / U.VELOCITY_M_S
            self.context.set_serialized_particle_data(xyzvxvyvz=trial.reshape(-1))
            self.context.t, self.context.dt = sim.t, min(sim.dt, h)
            self.context.did_modify_particles = 1
            self.contact = False
            guard.reset()
            while self.context.t < sim.t + h:
                previous = self.context.t
                step(self.context, sim.t + h - self.context.t, guard)
                if self.context.t <= previous:
                    raise ArithmeticError("Tidal gravity step did not advance")
                if self.contact or (not clipped and time.perf_counter() >= deadline):
                    break
            actual = self.context.t - sim.t
            if abs(actual - h) > 1e-10 * h:
                h, clipped = actual, True
                guard.reset()
                continue
            state = np.empty_like(original)
            self.context.serialize_particle_data(xyzvxvyvz=state)
            body = state.reshape(-1, 6)
            new_pos = body[:, :3] * U.LENGTH_M
            final, omega2, heat2 = self.kick(new_pos, body[:, 3:] * U.VELOCITY_M_S, omega1, 0.5 * h * U.TIME_S)
            after, _ = self.energy(new_pos, final, omega2)
            # The quaternion's average-omega update also bounds noncommutation.
            attitude_error = (
                np.max(np.linalg.norm(np.cross(self.omegas, omega2), axis=1), initial=0.0) * (h * U.TIME_S) ** 2 / 12
            )
            if abs(after + float(np.sum(heat1 + heat2)) - before) > 1e-11 * max(scale, 1e-300) or attitude_error > 1e-8:
                h *= 0.5
                guard.reset()
                continue
            body[:, 3:] = final / U.VELOCITY_M_S
            sim.set_serialized_particle_data(xyzvxvyvz=state)
            sim.t, self.heating, self.omegas = self.context.t, heat1 + heat2, omega2
            sim.dt = self.context.dt
            sim.did_modify_particles = 1
            guard.reset()
            return
        raise ArithmeticError("Tidal step failed its domain/energy or attitude budget")
