"""Bounded far-field gravity exchange for frozen debris snapshots (SI).

This is a momentum substep, not cloud transport or a complete time integrator.
It does not update positions or replace stored snapshot gravitational energies.
"""
from dataclasses import dataclass, replace
import math

from collision_outcomes import SphereState, _vector
from debris import DebrisReservoir
from units import G_SI


@dataclass(frozen=True)
class GravityEstimate:
    force_on_reservoir_n: tuple[float, float, float]
    potential_j: float
    relative_force_error_bound: float
    force_error_bound_n: float
    potential_error_bound_j: float
    tidal_acceleration_bound_m_s2: float
    tidal_torque_bound_nm: float


def estimate_gravity(reservoir: DebrisReservoir, body: SphereState) -> GravityEstimate:
    """Monopole interaction and conservative instantaneous truncation bounds.

    Both mass distributions must be centred on their stored centres of mass
    and contained in non-overlapping supports. Bounds include the body's radius.
    No claim about trajectory error or subsequent support evolution is implied.
    """
    delta = tuple(x - r for x, r in zip(body.position_m, reservoir.centre_m, strict=True))
    distance = math.hypot(*delta)
    support = reservoir.extent_m + body.radius_m
    if not math.isfinite(distance) or distance <= support:
        raise ValueError('Gravity exchange requires finite, non-overlapping supports')
    ratio = support / distance
    gap_fraction = 1 - ratio
    force = (G_SI * reservoir.mass_kg / distance) * (body.mass_kg / distance)
    potential = -(G_SI * reservoir.mass_kg / distance) * body.mass_kg
    relative_error = 12 * ratio * ratio / gap_fraction**4
    potential_error = abs(potential) * ratio * ratio / gap_fraction**3
    tidal_acceleration = 2 * (G_SI * body.mass_kg / distance / distance) * (
        reservoir.extent_m / distance) / gap_fraction**3
    torque = reservoir.mass_kg * reservoir.extent_m * tidal_acceleration
    result = GravityEstimate(tuple(force * (x / distance) for x in delta), potential, relative_error,
                             force * relative_error, potential_error, tidal_acceleration, torque)
    if not all(math.isfinite(x) for x in (*result.force_on_reservoir_n, potential, relative_error,
                                         result.force_error_bound_n, potential_error, tidal_acceleration, torque)):
        raise ValueError('Gravity estimate is outside numerical range')
    return result


@dataclass(frozen=True)
class GravityKick:
    reservoir: DebrisReservoir
    body: SphereState
    estimate: GravityEstimate
    impulse_on_reservoir_kg_m_s: tuple[float, float, float]
    kinetic_work_j: float
    omitted_tidal_velocity_change_bound_m_s: float
    omitted_tidal_angular_momentum_change_bound_kg_m2_s: float


def gravity_kick(reservoir: DebrisReservoir, body: SphereState, duration_s: float, *,
                 max_relative_force_error: float, max_tidal_velocity_change_m_s: float) -> GravityKick:
    """Apply equal/opposite monopole impulses at fixed positions, or reject.

    Callers supply accuracy limits for centre-force error and omitted internal
    tidal velocity change. Returned work is the pair's kinetic-energy increment;
    it is not heat and must not be added to the internal-energy reservoirs.
    Momentum and orbital-plus-intrinsic angular momentum are preserved. Total
    isolated energy is not conserved by a kick alone: a complete integrator must
    also evolve positions and gravitational potential, with its own error tests.
    """
    if not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError('Kick duration must be finite and nonnegative')
    if not math.isfinite(max_relative_force_error) or not 0 < max_relative_force_error <= 1:
        raise ValueError('Relative force error limit must be finite and in (0, 1]')
    if not math.isfinite(max_tidal_velocity_change_m_s) or max_tidal_velocity_change_m_s < 0:
        raise ValueError('Tidal velocity limit must be finite and nonnegative')
    estimate = estimate_gravity(reservoir, body)
    tidal_change = estimate.tidal_acceleration_bound_m_s2 * duration_s
    if estimate.relative_force_error_bound > max_relative_force_error:
        raise ValueError('Reservoir is too extended for the requested force accuracy')
    if tidal_change > max_tidal_velocity_change_m_s:
        raise ValueError('Omitted tidal velocity change exceeds the requested limit')
    impulse = _vector(f * duration_s for f in estimate.force_on_reservoir_n)
    cloud_velocity = _vector(v + p / reservoir.mass_kg
                             for v, p in zip(reservoir.velocity_m_s, impulse, strict=True))
    body_velocity = _vector(v - p / body.mass_kg for v, p in zip(body.velocity_m_s, impulse, strict=True))
    # Paired work in relative variables is invariant under a common velocity boost.
    relative_velocity = tuple(v - u for v, u in zip(reservoir.velocity_m_s, body.velocity_m_s, strict=True))
    work = math.fsum(p * (v + .5 * (p / reservoir.mass_kg + p / body.mass_kg))
                     for p, v in zip(impulse, relative_velocity, strict=True))
    angular_bound = estimate.tidal_torque_bound_nm * duration_s
    if not math.isfinite(work) or not math.isfinite(angular_bound):
        raise ValueError('Gravity kick is outside numerical range')
    return GravityKick(replace(reservoir, velocity_m_s=cloud_velocity), replace(body, velocity_m_s=body_velocity),
                       estimate, impulse, work, tidal_change, angular_bound)
