"""Compact homologous ejecta shells coupled to resolved Newtonian bodies.

The angular shape is frozen. The self-potential coefficient and initial force
residual come from the same resolved allocation, not a uniform-shell energy fit.
An omitted-force impulse budget limits this approximation. Native REBOUND direct
summation supplies body/body forces; BS advances one joint ODE for all states.
"""

from dataclasses import dataclass, replace
import ctypes
import math
from itertools import product, combinations
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import rebound

from collision_outcomes import collision_budget
from dynamics import _pairs
import units as U

MAX_SHELLS = 8
MAX_MODEL_VELOCITY_FRACTION = 0.005


def symmetric_directions(minimum):
    """Vertex-transitive shells: finite equal masses expand homologously."""
    count = next((n for n in (4, 6, 8, 12, 20, 30) if n >= minimum), None)
    if count is None:
        raise ValueError("No supported symmetric shell at this fragment count")
    phi = (1 + math.sqrt(5)) / 2
    if count == 4:
        points = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    elif count == 6:
        points = [tuple(sign * int(i == axis) for i in range(3)) for axis in range(3) for sign in (-1, 1)]
    elif count == 8:
        points = list(product((-1, 1), repeat=3))
    else:
        points = list(product((-1, 1), repeat=3)) if count == 20 else []
        for a, b in product((-1, 1), repeat=2):
            lo, hi = (a / phi, b * phi) if count == 20 else (a, b * phi)
            points.extend(((0, lo, hi), (lo, hi, 0), (hi, 0, lo)))
        if count == 30:
            vertices = np.array(points, dtype=float)
            edge = min(np.linalg.norm(a - b) for a, b in combinations(vertices, 2))
            points = [(a + b) / 2 for a, b in combinations(vertices, 2) if math.isclose(np.linalg.norm(a - b), edge)]
    points = np.array(points, dtype=float)
    return points / np.linalg.norm(points, axis=1)[:, None]


@lru_cache(maxsize=6)
def symmetric_coefficient(count):
    points = symmetric_directions(count)
    return math.fsum(1 / math.dist(a, b) for a, b in combinations(points, 2)) / count**2


@dataclass(frozen=True)
class EjectaShell:
    identifier: int
    fragment_count: int
    mass_kg: float
    centre_m: tuple[float, float, float]
    velocity_m_s: tuple[float, float, float]
    radius_m: float
    radial_speed_m_s: float
    fragment_radius_m: float
    self_coefficient: float
    self_binding_j: float
    internal_energy_j: float
    initial_radius_m: float
    initial_speed_m_s: float
    initial_force_residual_m_s2: float
    potential_offset_j: float = 0.0
    omitted_impulse_m_s: float = 0.0
    formed_at_s: float = 0.0
    regime: str = "disruption"

    def __post_init__(self):
        if type(self.identifier) is not int or not 1 <= self.identifier <= 16_000_000:
            raise ValueError("Shell identifier must be a positive integer")
        if type(self.fragment_count) is not int or self.fragment_count not in (4, 6, 8, 12, 20, 30):
            raise ValueError("Unsupported symmetric-shell fragment count")
        for key in ("centre_m", "velocity_m_s"):
            value = tuple(float(x) for x in getattr(self, key))
            if len(value) != 3 or not all(math.isfinite(x) for x in value):
                raise ValueError("Shell vectors must have three finite components")
            object.__setattr__(self, key, value)
        for key in (
            "mass_kg",
            "radius_m",
            "radial_speed_m_s",
            "fragment_radius_m",
            "self_coefficient",
            "initial_radius_m",
            "initial_speed_m_s",
        ):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError("Shell mass, radii, expansion and self-gravity must be positive and finite")
        if self.radius_m <= self.fragment_radius_m:
            raise ValueError("Shell radius must exceed fragment radius")
        if not math.isclose(self.self_coefficient, symmetric_coefficient(self.fragment_count), rel_tol=1e-12):
            raise ValueError("Shell self-gravity coefficient disagrees with its geometry")
        binding = -0.6 * U.G_SI * self.mass_kg**2 / (self.fragment_count * self.fragment_radius_m)
        if not math.isclose(self.self_binding_j, binding, rel_tol=1e-12):
            raise ValueError("Shell fragment self-binding inventory is inconsistent")
        for key in ("internal_energy_j", "initial_force_residual_m_s2", "omitted_impulse_m_s"):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) < 0:
                raise ValueError("Shell inventories and error bounds must be finite and nonnegative")
        if self.omitted_impulse_m_s > MAX_MODEL_VELOCITY_FRACTION * self.initial_speed_m_s:
            raise ValueError("Unresolved shell exceeded its 0.5% omitted-impulse budget")
        if not math.isfinite(self.self_binding_j) or not math.isfinite(self.potential_offset_j):
            raise ValueError("Shell energies must be finite")
        if not math.isfinite(self.formed_at_s) or self.formed_at_s < 0:
            raise ValueError("Shell formation time must be finite and nonnegative")
        if self.regime not in ("disruption", "supercatastrophic_disruption"):
            raise ValueError("Unsupported unresolved-shell impact regime")

    @property
    def self_potential_j(self):
        return -self.self_coefficient * U.G_SI * self.mass_kg**2 / self.radius_m


def form_shell(primary, fragments, identifier):
    """Compress an equal-radius antipodal, nonrotating radial allocation."""
    states = tuple(fragments)
    if len(states) < 4:
        raise ValueError("Compact shells require at least four fragments")
    m = np.array([s.mass_kg for s in states])
    total = float(m.sum())
    x = np.array([s.position_m for s in states]) - primary.position_m
    v = np.array([s.velocity_m_s for s in states]) - primary.velocity_m_s
    radii = np.linalg.norm(x, axis=1)
    radius = float(np.mean(radii))
    radial = np.einsum("ij,ij->i", x, v) / radii
    speed = float(np.mean(radial))
    if (
        not np.allclose(radii, radius, rtol=1e-10, atol=0)
        or speed <= 0
        or not np.allclose(m, total / len(states), rtol=1e-12, atol=0)
        or not np.allclose([s.radius_m for s in states], states[0].radius_m, rtol=1e-12, atol=0)
        or not np.allclose(v, x * (speed / radius), rtol=0, atol=1e-10 * abs(speed))
        or np.linalg.norm((m[:, None] * x).sum(axis=0)) > 1e-10 * total * radius
        or not np.allclose(x.T @ (m[:, None] * x) / (total * radius**2), np.eye(3) / 3, rtol=0, atol=1e-10)
        or any(any(s.spin_kg_m2_s) for s in states)
    ):
        raise ValueError("Compact shells require centred, nonrotating homologous ejecta")
    budget = collision_budget(states)
    acceleration = np.zeros_like(x)
    for i in range(len(states)):
        others = np.arange(len(states)) != i
        delta = x[others] - x[i]
        distance = np.linalg.norm(delta, axis=1)
        acceleration[i] = U.G_SI * np.sum(m[others, None] * delta / distance[:, None] ** 3, axis=0)
    coefficient = -budget.mutual_potential_j * radius / (U.G_SI * total**2)
    projected = -coefficient * U.G_SI * total * x / radius**3
    residual = float(np.max(np.linalg.norm(acceleration - projected, axis=1)))
    return EjectaShell(
        identifier,
        len(states),
        total,
        primary.position_m,
        primary.velocity_m_s,
        radius,
        speed,
        max(s.radius_m for s in states),
        coefficient,
        budget.self_binding_j,
        budget.internal_energy_j,
        radius,
        speed,
        residual,
    )


def shell_potential(shell, mass_kg, position_m):
    distance = math.dist(shell.centre_m, position_m)
    return -U.G_SI * shell.mass_kg * mass_kg / max(shell.radius_m, distance)


def other_shell_defect(shell, others):
    result = 0.0
    for other in others:
        if other.identifier == shell.identifier:
            continue
        distance = math.dist(shell.centre_m, other.centre_m)
        width = shell.fragment_radius_m + other.fragment_radius_m
        if distance > shell.radius_m + other.radius_m + width:
            gap = distance - shell.radius_m - other.radius_m
            result += (
                2 * U.G_SI * other.mass_kg * shell.radius_m / gap**3
                + 6 * U.G_SI * other.mass_kg * other.radius_m**2 / gap**4
            )
        elif distance + shell.radius_m + width < other.radius_m:
            gap = other.radius_m - distance - shell.radius_m
            result += 6 * U.G_SI * other.mass_kg * (distance + shell.radius_m) ** 2 / gap**4
        elif distance + other.radius_m + width < shell.radius_m:
            gap = shell.radius_m - distance - other.radius_m
            result += (
                2 * U.G_SI * other.mass_kg * distance / gap**3 + 6 * U.G_SI * other.mass_kg * other.radius_m**2 / gap**4
            )
        else:
            raise ValueError("Intersecting unresolved shells require a different debris model")
    return result


def model_defect(shell, masses, positions, radii):
    """Instantaneous force-defect envelope on the assumed spherical shape."""
    result = shell.initial_force_residual_m_s2 * (shell.initial_radius_m / shell.radius_m) ** 2
    for mass, position, radius in zip(masses, positions, radii, strict=True):
        distance = math.dist(position, shell.centre_m)
        clearance = abs(distance - shell.radius_m) - radius - shell.fragment_radius_m
        if clearance <= 0:
            raise ValueError("A resolved body intersects the unresolved ejecta shell")
        if distance < shell.radius_m:
            result += 2 * U.G_SI * mass * distance / (shell.radius_m - distance) ** 3
            result += 6 * U.G_SI * (mass + shell.mass_kg) * distance**2 / (shell.radius_m - distance) ** 4
        else:
            result += 2 * U.G_SI * mass * shell.radius_m / (distance - shell.radius_m) ** 3
            result += 6 * U.G_SI * (mass + shell.mass_kg) * shell.radius_m**2 / (distance - shell.radius_m) ** 4
    return result


def shell_potential_energy(shells, masses, positions):
    terms = []
    for shell in shells:
        terms.append(shell.self_potential_j)
        terms.extend(shell_potential(shell, m, p) for m, p in zip(masses, positions, strict=True))
    for i, a in enumerate(shells):
        for b in shells[i + 1 :]:
            distance = math.dist(a.centre_m, b.centre_m)
            width = a.fragment_radius_m + b.fragment_radius_m
            if abs(a.radius_m - b.radius_m) - width <= distance <= a.radius_m + b.radius_m + width:
                raise ValueError("Intersecting unresolved shells require a different debris model")
            terms.append(-U.G_SI * a.mass_kg * b.mass_kg / max(distance, a.radius_m, b.radius_m))
    return math.fsum(terms)


def shell_energy(shells, masses, positions):
    return math.fsum(
        [shell_potential_energy(shells, masses, positions)]
        + [
            0.5 * s.mass_kg * (math.fsum(v * v for v in s.velocity_m_s) + s.radial_speed_m_s**2) + s.potential_offset_j
            for s in shells
        ]
    )


def approaching_contacts(sim):
    state = np.empty(6 * sim.N)
    radii = np.empty(sim.N)
    sim.serialize_particle_data(xyzvxvyvz=state, r=radii)
    body = state.reshape(-1, 6)
    i, j = _pairs(sim.N)
    dx, dv = body[j, :3] - body[i, :3], body[j, 3:] - body[i, 3:]
    hit = (np.linalg.norm(dx, axis=1) < radii[i] + radii[j]) & (np.einsum("ij,ij->i", dx, dv) < 0)
    return zip(i[hit], j[hit], strict=True)


class ShellIntegrator:
    """One adaptive joint solve; trial evaluations never mutate the live world.

    REBOUND's additional ODE state is not exposed to its N-body force callback
    at the same trial stage. Therefore a dedicated BS ODE owns the joint state,
    and a separate REBOUND context evaluates the usual native direct gravity.
    """

    def __init__(self, sim, shells, epsilon):
        self.context = rebound.Simulation()
        self.context.G = sim.G
        for p in sim.particles:
            self.context.add(m=p.m, r=p.r)
        self.context.N_active = self.context.N
        self.n = sim.N
        self.epsilon = epsilon
        self.shells = tuple(shells)
        self.masses = np.array([p.m for p in sim.particles])
        self.radii = np.array([p.r for p in sim.particles])
        self.engine = rebound.Simulation()
        self.engine.integrator = "bs"
        self.engine.integrator.eps_rel = min(epsilon, 0.0000000001)
        self.engine.integrator.eps_abs = min(epsilon * 0.001, 0.000000000001)
        self.engine.t = sim.t
        self.engine.dt = 0.001
        self.ode = self.engine.create_ode(6 * self.n + 9 * len(shells), needs_nbody=False)

        def callback(ptr, d, y, t):
            try:
                self._derivatives(ptr, d, y, t)
            except (ValueError, ArithmeticError) as exc:
                self.failure = str(exc)
                np.ctypeslib.as_array(d, shape=(self.ode.length,))[:] = 0

        self.callback = callback
        self.ode.derivatives = self.callback
        self.failure = None
        self.gravity = rebound.clibrebound.reb_simulation_update_acceleration
        self.gravity.argtypes = [ctypes.POINTER(rebound.Simulation)]
        self.gravity.restype = None
        self.acceleration = np.empty((self.n, 3))
        if self.n:
            dtype = np.dtype(
                dict(
                    names=["ax", "ay", "az"],
                    formats=["f8"] * 3,
                    offsets=[getattr(rebound.Particle, k).offset for k in ("ax", "ay", "az")],
                    itemsize=ctypes.sizeof(rebound.Particle),
                )
            )
            buffer = (ctypes.c_char * (self.n * ctypes.sizeof(rebound.Particle))).from_address(
                ctypes.addressof(self.context.particles[0])
            )
            self.native_acceleration = np.ndarray((self.n,), dtype=dtype, buffer=buffer)
        self.sync(sim, shells)

    def sync(self, sim, shells):
        self.engine.t = sim.t
        state = np.ctypeslib.as_array(self.ode.y, shape=(self.ode.length,))
        sim.serialize_particle_data(xyzvxvyvz=state[: 6 * self.n])
        for i, shell in enumerate(shells):
            state[6 * self.n + 9 * i : 6 * self.n + 9 * (i + 1)] = (
                *np.array(shell.centre_m) / U.LENGTH_M,
                *np.array(shell.velocity_m_s) / U.VELOCITY_M_S,
                shell.radius_m / U.LENGTH_M,
                shell.radial_speed_m_s / U.VELOCITY_M_S,
                shell.omitted_impulse_m_s / U.VELOCITY_M_S,
            )
        self.shells = tuple(shells)

    def _derivatives(self, ptr, destination, source, t):
        state = np.ctypeslib.as_array(source, shape=(self.ode.length,))
        derivative = np.ctypeslib.as_array(destination, shape=(self.ode.length,))
        derivative[:] = 0
        body = state[: 6 * self.n].reshape(-1, 6)
        output = derivative[: 6 * self.n].reshape(-1, 6)
        if self.n:
            self.context.set_serialized_particle_data(xyzvxvyvz=state[: 6 * self.n])
            self.gravity(ctypes.byref(self.context))
            output[:, :3] = body[:, 3:]
            for axis, name in enumerate(("ax", "ay", "az")):
                output[:, 3 + axis] = self.native_acceleration[name]
        stage_shells = [
            SimpleNamespace(
                **(
                    dict(vars(shell))
                    | dict(
                        centre_m=tuple(state[6 * self.n + 9 * i : 6 * self.n + 9 * i + 3] * U.LENGTH_M),
                        radius_m=state[6 * self.n + 9 * i + 6] * U.LENGTH_M,
                    )
                )
            )
            for i, shell in enumerate(self.shells)
        ]
        for i, shell in enumerate(self.shells):
            offset = 6 * self.n + 9 * i
            cloud = state[offset : offset + 9]
            delta = body[:, :3] - cloud[:3]
            distance = np.linalg.norm(delta, axis=1)
            radius = cloud[6]
            if not np.isfinite(cloud).all() or radius <= 0:
                raise ValueError("Unresolved shell left its numerical domain")
            outside = distance > radius
            force = np.zeros((self.n, 3))
            force[outside] = (
                -self.context.G * (shell.mass_kg / U.MASS_KG) * delta[outside] / distance[outside, None] ** 3
            )
            output[:, 3:] += force
            derivative[offset : offset + 3] = cloud[3:6]
            derivative[offset + 3 : offset + 6] = -np.sum(self.masses[:, None] * force, axis=0) / (
                shell.mass_kg / U.MASS_KG
            )
            derivative[offset + 6] = cloud[7]
            derivative[offset + 7] = (
                -self.context.G
                * (shell.self_coefficient * shell.mass_kg / U.MASS_KG + float(self.masses[~outside].sum()))
                / radius**2
            )
            defect = model_defect(
                stage_shells[i], self.masses * U.MASS_KG, body[:, :3] * U.LENGTH_M, self.radii * U.LENGTH_M
            )
            defect += other_shell_defect(stage_shells[i], stage_shells)
            derivative[offset + 8] = defect * U.TIME_S / U.VELOCITY_M_S
        for i, a in enumerate(self.shells):
            ia = 6 * self.n + 9 * i
            for j, b in enumerate(self.shells[i + 1 :], i + 1):
                ib = 6 * self.n + 9 * j
                delta = state[ib : ib + 3] - state[ia : ia + 3]
                distance = np.linalg.norm(delta)
                ra, rb = state[ia + 6], state[ib + 6]
                if distance > ra + rb:
                    field = self.context.G * delta / distance**3
                    derivative[ia + 3 : ia + 6] += b.mass_kg / U.MASS_KG * field
                    derivative[ib + 3 : ib + 6] -= a.mass_kg / U.MASS_KG * field
                else:  # other_shell_defect already excludes intersecting surfaces.
                    outer, inner = (ia, b) if ra > rb else (ib, a)
                    derivative[outer + 7] -= self.context.G * inner.mass_kg / U.MASS_KG / state[outer + 6] ** 2

    def step_limit(self, sim, shells, maximum):
        for shell in shells:
            positions = np.array([p.xyz for p in sim.particles]) * U.LENGTH_M
            masses = self.masses * U.MASS_KG
            radii = self.radii * U.LENGTH_M
            model_defect(shell, masses, positions, radii)
            for p in sim.particles:
                distance = math.dist(p.xyz, np.array(shell.centre_m) / U.LENGTH_M)
                gap = abs(distance - shell.radius_m / U.LENGTH_M) - p.r - shell.fragment_radius_m / U.LENGTH_M
                speed = math.dist(p.vxyz, np.array(shell.velocity_m_s) / U.VELOCITY_M_S)
                speed += shell.radial_speed_m_s / U.VELOCITY_M_S
                speed += math.sqrt(
                    2 * sim.G * (p.m + shell.mass_kg / U.MASS_KG) / max(distance, shell.radius_m / U.LENGTH_M)
                )
                maximum = min(maximum, 0.25 * gap / speed)
        for i, a in enumerate(shells):
            other_shell_defect(a, shells)
            for b in shells[i + 1 :]:
                distance = math.dist(a.centre_m, b.centre_m)
                gap = min(abs(distance - a.radius_m - b.radius_m), abs(distance - abs(a.radius_m - b.radius_m)))
                gap -= a.fragment_radius_m + b.fragment_radius_m
                speed = math.dist(a.velocity_m_s, b.velocity_m_s) + a.radial_speed_m_s + b.radial_speed_m_s
                speed += math.sqrt(2 * U.G_SI * (a.mass_kg + b.mass_kg) / max(a.radius_m, b.radius_m, distance))
                maximum = min(maximum, 0.25 * gap / speed / U.TIME_S)
        return maximum

    def advance(self, sim, shells, maximum, guard=None):
        self.sync(sim, shells)
        self.failure = None
        maximum = self.step_limit(sim, shells, maximum)
        if guard is not None:
            extra = np.zeros(sim.N)
            for shell in shells:
                distance = np.array([math.dist(p.xyz, np.array(shell.centre_m) / U.LENGTH_M) for p in sim.particles])
                outside = distance > shell.radius_m / U.LENGTH_M
                extra[outside] += 4 * sim.G * shell.mass_kg / U.MASS_KG / distance[outside] ** 2
            maximum = guard.limit(sim, maximum, extra_acceleration=extra)
        self.engine.dt = min(self.engine.dt, maximum)
        for _ in range(32):
            self.engine.steps(1)
            if self.failure:
                raise ValueError(self.failure)
            if self.engine.t > sim.t:
                break
        else:
            raise ArithmeticError("Adaptive unresolved-ejecta step did not advance")
        state = np.ctypeslib.as_array(self.ode.y, shape=(self.ode.length,))
        updated = []
        for i, shell in enumerate(shells):
            values = state[6 * self.n + 9 * i : 6 * self.n + 9 * (i + 1)]
            new = replace(
                shell,
                centre_m=tuple(values[:3] * U.LENGTH_M),
                velocity_m_s=tuple(values[3:6] * U.VELOCITY_M_S),
                radius_m=float(values[6] * U.LENGTH_M),
                radial_speed_m_s=float(values[7] * U.VELOCITY_M_S),
                omitted_impulse_m_s=max(0.0, float(values[8] * U.VELOCITY_M_S)),
            )
            positions = state[: 6 * self.n].reshape(-1, 6)[:, :3] * U.LENGTH_M
            model_defect(new, self.masses * U.MASS_KG, positions, self.radii * U.LENGTH_M)
            updated.append(new)
        positions = state[: 6 * self.n].reshape(-1, 6)[:, :3] * U.LENGTH_M
        potential = shell_potential_energy(updated, self.masses * U.MASS_KG, positions)
        self.context.set_serialized_particle_data(xyzvxvyvz=state[: 6 * self.n])
        native_scale = U.MASS_KG * U.VELOCITY_M_S**2
        old_positions = np.array([p.xyz for p in sim.particles]) * U.LENGTH_M
        before = sim.energy() * native_scale + shell_energy(shells, self.masses * U.MASS_KG, old_positions)
        after = self.context.energy() * native_scale + shell_energy(updated, self.masses * U.MASS_KG, positions)
        scale = max(abs(before), abs(after), abs(potential), 1e-300)
        if not math.isfinite(after) or abs(after - before) > 1e-9 * scale:
            raise ValueError("Unresolved coupled step exceeded its numerical energy budget")
        sim.set_serialized_particle_data(xyzvxvyvz=state[: 6 * self.n])
        sim.t = self.engine.t
        sim.did_modify_particles = 1
        return tuple(updated)
