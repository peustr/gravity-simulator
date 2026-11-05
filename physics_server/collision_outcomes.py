"""Isolated uniform-sphere collision budgets and conditional outcomes (SI).

No material equation of state, calibrated ejecta model or live particle mutation.
See docs/collision-budgets.md for the energy convention and model limits.
"""
from dataclasses import dataclass, replace
from itertools import combinations
import math

import numpy as np

from impacts import _cross
from units import G_SI


def _vector(values):
    result = tuple(float(x) for x in values)
    if len(result) != 3 or not all(math.isfinite(x) for x in result):
        raise ValueError('Vectors require three finite components')
    return result


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


@dataclass(frozen=True)
class SphereState:
    mass_kg: float
    radius_m: float
    position_m: tuple[float, float, float]
    velocity_m_s: tuple[float, float, float]
    spin_kg_m2_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    internal_energy_j: float = 0.0

    def __post_init__(self):
        for name in ('mass_kg', 'radius_m', 'internal_energy_j'):
            object.__setattr__(self, name, float(getattr(self, name)))
        if not all(math.isfinite(x) for x in (self.mass_kg, self.radius_m, self.internal_energy_j)):
            raise ValueError('Mass, radius and internal energy must be finite')
        if self.mass_kg <= 0 or self.radius_m <= 0 or self.internal_energy_j < 0:
            raise ValueError('Mass/radius must be positive; internal energy must be nonnegative')
        for name in ('position_m', 'velocity_m_s', 'spin_kg_m2_s'):
            object.__setattr__(self, name, _vector(getattr(self, name)))
        if not 0 < self.inertia_kg_m2 < math.inf:
            raise ValueError('Sphere inertia is outside numerical range')
        if not all(math.isfinite(x) for x in (self.self_binding_j, self.rotational_energy_j)):
            raise ValueError('Sphere energy is outside numerical range')

    @property
    def inertia_kg_m2(self):
        return (2 / 5) * self.mass_kg * self.radius_m * self.radius_m

    @property
    def self_binding_j(self):
        return -(3 / 5) * G_SI * self.mass_kg / self.radius_m * self.mass_kg

    @property
    def rotational_energy_j(self):
        # L is angular momentum, not angular velocity.
        spin = math.hypot(*self.spin_kg_m2_s)
        return (0.5 * spin / self.inertia_kg_m2) * spin


@dataclass(frozen=True)
class CollisionBudget:
    mass_kg: float
    momentum_kg_m_s: tuple[float, float, float]
    angular_momentum_kg_m2_s: tuple[float, float, float]
    translational_energy_j: float
    rotational_energy_j: float
    self_binding_j: float
    mutual_potential_j: float
    internal_energy_j: float

    @property
    def energy_j(self):
        return math.fsum((self.translational_energy_j, self.rotational_energy_j,
                          self.self_binding_j, self.mutual_potential_j, self.internal_energy_j))


def _mutual_potential(a, b):
    distance = math.dist(a.position_m, b.position_m)
    if distance < (a.radius_m + b.radius_m) * (1 - 1e-12):
        raise ValueError('Mutual potential requires non-overlapping spheres')
    return -G_SI * a.mass_kg / distance * b.mass_kg


def collision_budget(bodies, *, origin_m=(0, 0, 0), frame_velocity_m_s=(0, 0, 0)) -> CollisionBudget:
    """Inventory in an explicitly chosen inertial frame, including body spin.

    Pair potential is exact for non-overlapping spherical mass distributions.
    The internal-energy zero is a fixed material reference, excluding binding.
    """
    bodies = tuple(bodies)
    origin, frame_velocity = _vector(origin_m), _vector(frame_velocity_m_s)
    positions = [tuple(x - o for x, o in zip(b.position_m, origin, strict=True)) for b in bodies]
    velocities = [tuple(v - u for v, u in zip(b.velocity_m_s, frame_velocity, strict=True)) for b in bodies]
    momenta = [tuple(b.mass_kg * v for v in velocity) for b, velocity in zip(bodies, velocities, strict=True)]
    orbital = [_cross(x, p) for x, p in zip(positions, momenta, strict=True)]
    result = CollisionBudget(
        math.fsum(b.mass_kg for b in bodies),
        tuple(math.fsum(p[i] for p in momenta) for i in range(3)),
        tuple(math.fsum(angular[i] + b.spin_kg_m2_s[i]
                        for b, angular in zip(bodies, orbital, strict=True)) for i in range(3)),
        math.fsum(.5 * b.mass_kg * _dot(v, v) for b, v in zip(bodies, velocities, strict=True)),
        math.fsum(b.rotational_energy_j for b in bodies),
        math.fsum(b.self_binding_j for b in bodies),
        math.fsum(_mutual_potential(a, b) for a, b in combinations(bodies, 2)),
        math.fsum(b.internal_energy_j for b in bodies))
    if not all(math.isfinite(x) for x in (result.energy_j, *result.momentum_kg_m_s,
                                         *result.angular_momentum_kg_m2_s)):
        raise ValueError('Collision budget is outside numerical range')
    return result


def merge_spheres(a: SphereState, b: SphereState) -> SphereState:
    """Construct an isolated single remnant, or reject an infeasible merger.

    Preserve volume, mass, centre of mass, momentum and total angular momentum.
    Account for binding, relative kinetic and rotational energy in the remaining
    internal energy. Inputs must touch and must not be separating. This is a
    feasibility calculation, not a rule for selecting the collision regime.
    """
    distance = math.dist(a.position_m, b.position_m)
    if not math.isclose(distance, a.radius_m + b.radius_m, rel_tol=1e-12, abs_tol=0):
        raise ValueError('Merger requires surface contact')
    dx = tuple(y - x for x, y in zip(a.position_m, b.position_m, strict=True))
    dv = tuple(v - u for u, v in zip(a.velocity_m_s, b.velocity_m_s, strict=True))
    if _dot(dx, dv) > 0:
        raise ValueError('Merger contact must not be separating')
    total = a.mass_kg + b.mass_kg
    fraction = b.mass_kg / total
    reduced_mass = a.mass_kg * fraction
    r_big, r_small = max(a.radius_m, b.radius_m), min(a.radius_m, b.radius_m)
    radius = r_big * (1 + (r_small / r_big)**3)**(1 / 3)
    angular = _cross(dx, dv)
    remnant = SphereState(
        total, radius,
        tuple(x + fraction * offset for x, offset in zip(a.position_m, dx, strict=True)),
        tuple(v + fraction * delta for v, delta in zip(a.velocity_m_s, dv, strict=True)),
        tuple(math.fsum((a.spin_kg_m2_s[i], b.spin_kg_m2_s[i], reduced_mass * angular[i])) for i in range(3)))
    # Necessary spherical surface-retention screen: centrifugal acceleration
    # must remain below GM/R^2. This does not establish fluid-shape stability.
    spin_limit = remnant.inertia_kg_m2 * math.sqrt(G_SI * total / radius) / radius
    if math.hypot(*remnant.spin_kg_m2_s) >= spin_limit:
        raise ValueError('Single spherical remnant exceeds the spin limit')
    internal = math.fsum((a.internal_energy_j, b.internal_energy_j,
                          .5 * reduced_mass * _dot(dv, dv),
                          a.rotational_energy_j, b.rotational_energy_j,
                          a.self_binding_j, b.self_binding_j, _mutual_potential(a, b),
                          -remnant.rotational_energy_j, -remnant.self_binding_j))
    if not math.isfinite(internal) or internal < 0:
        raise ValueError('Insufficient or non-finite energy for the proposed remnant')
    return replace(remnant, internal_energy_j=internal)


@dataclass(frozen=True)
class RemnantSpec:
    """Requested mass/radius and a relative layout offset, all in SI units."""
    mass_kg: float
    radius_m: float
    offset_m: tuple[float, float, float]

    def __post_init__(self):
        state = SphereState(self.mass_kg, self.radius_m, self.offset_m, (0, 0, 0))
        object.__setattr__(self, 'mass_kg', state.mass_kg)
        object.__setattr__(self, 'radius_m', state.radius_m)
        object.__setattr__(self, 'offset_m', state.position_m)


def allocate_remnants(a: SphereState, b: SphereState, layout, *, expansion_fraction: float) -> tuple[SphereState, ...]:
    """Allocate an isolated pair's budgets to a proposed multi-body layout.

    The minimum-kinetic-energy rotation carries the required angular momentum;
    radial expansion carries no additional angular momentum. Remaining internal
    energy is shared per unit mass. Masses/radii/spacing and the energy split
    are caller choices, not a calibrated fragment prescription. Bound fragments
    are allowed; passing this calculation does not establish an escaping runner.
    """
    specs = tuple(layout)
    if len(specs) < 2:
        raise ValueError('Multiple-remnant allocation requires at least two bodies')
    if not math.isfinite(expansion_fraction) or not 0 <= expansion_fraction <= 1:
        raise ValueError('Expansion fraction must be finite and between zero and one')
    distance = math.dist(a.position_m, b.position_m)
    if not math.isclose(distance, a.radius_m + b.radius_m, rel_tol=1e-12, abs_tol=0):
        raise ValueError('Allocation requires surface contact')
    dx = np.subtract(b.position_m, a.position_m)
    dv = np.subtract(b.velocity_m_s, a.velocity_m_s)
    if _dot(dx, dv) > 0:
        raise ValueError('Allocation contact must not be separating')
    total = a.mass_kg + b.mass_kg
    if not math.isclose(math.fsum(s.mass_kg for s in specs), total, rel_tol=1e-12, abs_tol=0):
        raise ValueError('Proposed remnant masses do not close the incoming inventory')
    # Compare scaled volumes without cubing very large SI radii.
    radius_scale = max(a.radius_m, b.radius_m, *(s.radius_m for s in specs))
    volume_before = (a.radius_m / radius_scale)**3 + (b.radius_m / radius_scale)**3
    volume_after = math.fsum((s.radius_m / radius_scale)**3 for s in specs)
    if not math.isclose(volume_after, volume_before, rel_tol=1e-12, abs_tol=0):
        raise ValueError('Proposed remnant volumes do not close the incoming inventory')

    fraction = b.mass_kg / total
    reduced_mass = a.mass_kg * fraction
    centre = np.asarray(a.position_m) + fraction * dx
    bulk_velocity = np.asarray(a.velocity_m_s) + fraction * dv
    angular = np.asarray(a.spin_kg_m2_s) + b.spin_kg_m2_s + reduced_mass * np.cross(dx, dv)
    masses = np.array([s.mass_kg for s in specs])
    offsets = np.array([s.offset_m for s in specs])
    offsets -= offsets[0].copy()
    centroid = np.array([math.fsum((m / total) * r[i] for m, r in zip(masses, offsets, strict=True))
                         for i in range(3)])
    offsets -= centroid
    resting = tuple(SphereState(s.mass_kg, s.radius_m, r, (0, 0, 0))
                    for s, r in zip(specs, offsets, strict=True))
    potential = collision_budget(resting)  # also rejects overlapping layouts
    moments = np.array([s.inertia_kg_m2 for s in resting])
    inertia = np.diag([math.fsum(m * (r[(i + 1) % 3]**2 + r[(i + 2) % 3]**2)
                                for m, r in zip(masses, offsets, strict=True)) + math.fsum(moments)
                       for i in range(3)])
    for i, j in ((0, 1), (0, 2), (1, 2)):
        inertia[i, j] = inertia[j, i] = -math.fsum(m * r[i] * r[j] for m, r in zip(masses, offsets, strict=True))
    scaled_inertia = inertia / np.max(np.abs(inertia))
    if not np.isfinite(scaled_inertia).all() or np.linalg.cond(scaled_inertia) > 1e12:
        raise ValueError('Proposed layout has numerically unresolved inertia')
    omega = np.linalg.solve(scaled_inertia, angular / np.max(np.abs(inertia)))
    rotational_velocities = np.cross(omega, offsets)
    spins = moments[:, None] * omega
    for state, spin in zip(resting, spins, strict=True):
        limit = state.inertia_kg_m2 * math.sqrt(G_SI * state.mass_kg / state.radius_m) / state.radius_m
        if math.hypot(*spin) >= limit:
            raise ValueError('Proposed layout exceeds a remnant spin limit')

    minimum_kinetic = math.fsum(.5 * m * _dot(v, v) for m, v in zip(masses, rotational_velocities, strict=True))
    minimum_kinetic += .5 * math.fsum(moments) * _dot(omega, omega)
    available = math.fsum((a.internal_energy_j, b.internal_energy_j,
                           .5 * reduced_mass * _dot(dv, dv), a.rotational_energy_j, b.rotational_energy_j,
                           a.self_binding_j, b.self_binding_j, _mutual_potential(a, b),
                           -potential.self_binding_j, -potential.mutual_potential_j, -minimum_kinetic))
    if not math.isfinite(available) or available < 0:
        raise ValueError('Insufficient or non-finite energy for the proposed layout')
    radial_moment = math.fsum(m * _dot(r, r) for m, r in zip(masses, offsets, strict=True))
    rate = math.sqrt(2 * expansion_fraction * available / radial_moment)
    internal_per_mass = (1 - expansion_fraction) * available / total
    return tuple(SphereState(s.mass_kg, s.radius_m, centre + r,
                             bulk_velocity + v + rate * r, spin, s.mass_kg * internal_per_mass)
                 for s, r, v, spin in zip(specs, offsets, rotational_velocities, spins, strict=True))
