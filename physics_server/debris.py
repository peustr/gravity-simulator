"""Creation-time debris capacity partition and compact SI reservoir inventories.

The reservoir is a snapshot, not a particle or an evolution model. In particular,
its stored potentials cannot be reused after advancing the resolved bodies.
"""
from dataclasses import dataclass
from itertools import product
import math

from collision_models import ConstructedCollision
from collision_outcomes import CollisionBudget, SphereState, _mutual_potential, _vector, collision_budget
from disruption import ContactOutcome
from impacts import _cross


def _centre(states, attribute, total):
    anchor = getattr(states[0], attribute)
    return tuple(anchor[i] + math.fsum((s.mass_kg / total) * (getattr(s, attribute)[i] - anchor[i])
                                      for s in states) for i in range(3))


@dataclass(frozen=True)
class DebrisReservoir:
    """Aggregate of fixed spheres at one instant; no constituent states retained.

    Orbital angular momentum and velocity dispersion are relative to the stored
    centre/velocity. Spin and fragment self-binding remain separate inventories;
    the reservoir must not be interpreted as one larger spherical remnant.
    """
    fragment_count: int
    mass_kg: float
    volume_m3: float
    centre_m: tuple[float, float, float]
    velocity_m_s: tuple[float, float, float]
    extent_m: float
    orbital_angular_momentum_kg_m2_s: tuple[float, float, float]
    spin_kg_m2_s: tuple[float, float, float]
    dispersion_energy_j: float
    rotational_energy_j: float
    self_binding_j: float
    mutual_potential_j: float
    internal_energy_j: float

    def budget(self, *, origin_m=(0, 0, 0), frame_velocity_m_s=(0, 0, 0)) -> CollisionBudget:
        """Inventory of this snapshot in a chosen inertial frame."""
        origin, frame_velocity = _vector(origin_m), _vector(frame_velocity_m_s)
        relative = tuple(v - u for v, u in zip(self.velocity_m_s, frame_velocity, strict=True))
        momentum = tuple(self.mass_kg * v for v in relative)
        offset = tuple(x - o for x, o in zip(self.centre_m, origin, strict=True))
        orbital = _cross(offset, momentum)
        result = CollisionBudget(
            self.mass_kg, momentum,
            tuple(math.fsum((orbital[i], self.orbital_angular_momentum_kg_m2_s[i], self.spin_kg_m2_s[i]))
                  for i in range(3)),
            math.fsum((.5 * self.mass_kg * math.fsum(v * v for v in relative), self.dispersion_energy_j)),
            self.rotational_energy_j, self.self_binding_j, self.mutual_potential_j, self.internal_energy_j)
        if not all(math.isfinite(x) for x in (result.energy_j, *result.momentum_kg_m_s,
                                             *result.angular_momentum_kg_m2_s)):
            raise ValueError('Debris budget is outside numerical range')
        return result


def summarize_debris(states) -> DebrisReservoir:
    """Compress non-overlapping spherical states without losing their budgets.

    Positions and velocities are compressed into centre, extent and inventory
    moments. Individual trajectories cannot be reconstructed from these fields.
    """
    states = tuple(states)
    if not states:
        raise ValueError('A debris reservoir requires at least one fragment')
    total = math.fsum(s.mass_kg for s in states)
    centre = _centre(states, 'position_m', total)
    velocity = _centre(states, 'velocity_m_s', total)
    local = collision_budget(states, origin_m=centre, frame_velocity_m_s=velocity)
    orbital = []
    for s in states:
        r = tuple(x - o for x, o in zip(s.position_m, centre, strict=True))
        p = tuple(s.mass_kg * (v - u) for v, u in zip(s.velocity_m_s, velocity, strict=True))
        orbital.append(_cross(r, p))
    volume = (4 / 3) * math.pi * math.fsum(s.radius_m * s.radius_m * s.radius_m for s in states)
    extent = max(math.dist(s.position_m, centre) + s.radius_m for s in states)
    if not all(math.isfinite(x) for x in (total, volume, extent)):
        raise ValueError('Debris reservoir is outside numerical range')
    return DebrisReservoir(
        len(states), total, volume, centre, velocity, extent,
        tuple(math.fsum(value[i] for value in orbital) for i in range(3)),
        tuple(math.fsum(s.spin_kg_m2_s[i] for s in states) for i in range(3)),
        local.translational_energy_j, local.rotational_energy_j, local.self_binding_j,
        local.mutual_potential_j, local.internal_energy_j)


@dataclass(frozen=True)
class DebrisPartition:
    """Immutable allocation after primary-remnant slots have been reserved.

    Cross potential couples explicit and unresolved material at this snapshot.
    It belongs to neither inventory alone and must be counted exactly once.
    """
    classification: ContactOutcome
    escape_certificate: str | None
    primaries: tuple[SphereState, ...]
    explicit_debris: tuple[SphereState, ...]
    reservoir: DebrisReservoir | None
    cross_potential_j: float

    def budget(self, *, origin_m=(0, 0, 0), frame_velocity_m_s=(0, 0, 0)) -> CollisionBudget:
        explicit = collision_budget((*self.primaries, *self.explicit_debris), origin_m=origin_m,
                                    frame_velocity_m_s=frame_velocity_m_s)
        if self.reservoir is None:
            return explicit
        unresolved = self.reservoir.budget(origin_m=origin_m, frame_velocity_m_s=frame_velocity_m_s)
        return CollisionBudget(
            math.fsum((explicit.mass_kg, unresolved.mass_kg)),
            tuple(math.fsum(values) for values in zip(explicit.momentum_kg_m_s, unresolved.momentum_kg_m_s, strict=True)),
            tuple(math.fsum(values) for values in zip(explicit.angular_momentum_kg_m2_s,
                                                     unresolved.angular_momentum_kg_m2_s, strict=True)),
            math.fsum((explicit.translational_energy_j, unresolved.translational_energy_j)),
            math.fsum((explicit.rotational_energy_j, unresolved.rotational_energy_j)),
            math.fsum((explicit.self_binding_j, unresolved.self_binding_j)),
            math.fsum((explicit.mutual_potential_j, unresolved.mutual_potential_j, self.cross_potential_j)),
            math.fsum((explicit.internal_energy_j, unresolved.internal_energy_j)))


def partition_debris(outcome: ConstructedCollision, *, max_explicit_debris: int) -> DebrisPartition:
    """Allocate optional debris slots without reclassifying a constructed outcome.

    The largest remnant and any runner always remain explicit. Capacity counts
    additional debris slots after those primaries replace the two incoming bodies.
    Prefer higher-mass fragments; ties retain their input layout order. Do not
    retain the outcome or unresolved SphereStates in the returned representation.
    """
    if type(max_explicit_debris) is not int or max_explicit_debris < 0:
        raise ValueError('Explicit debris capacity must be a nonnegative integer')
    primary_count = 1 + int(outcome.classification.runner_mass_kg > 0)
    primaries, debris = outcome.remnants[:primary_count], outcome.remnants[primary_count:]
    ranked = sorted(range(len(debris)), key=lambda i: (-debris[i].mass_kg, i))
    chosen = ranked[:max_explicit_debris]
    explicit = tuple(debris[i] for i in chosen)
    chosen_set = set(chosen)
    unresolved = tuple(s for i, s in enumerate(debris) if i not in chosen_set)
    reservoir = summarize_debris(unresolved) if unresolved else None
    cross_potential = math.fsum(_mutual_potential(a, b) for a, b in product((*primaries, *explicit), unresolved))
    return DebrisPartition(outcome.classification, outcome.escape_certificate, primaries, explicit,
                           reservoir, cross_potential)
