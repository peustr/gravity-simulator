"""Conservative two-centre transport of radially expanding debris clouds (SI).

Internal geometry expands by one scale factor; self-gravity is projected onto
that expansion mode. Nonhomologous inputs are rejected. See unresolved-debris.md
for force-defect controls and the distinction between model and trajectory error.
"""
from dataclasses import dataclass, replace
import math

from collision_outcomes import CollisionBudget, SphereState, _dot, _mutual_potential, _vector, collision_budget
from debris import DebrisReservoir, summarize_debris
from debris_gravity import estimate_gravity, gravity_kick
from units import G_SI


def _difference(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _energy_terms(cloud, body):
    reduced_mass = cloud.mass_kg * (body.mass_kg / (cloud.mass_kg + body.mass_kg))
    relative = _difference(cloud.velocity_m_s, body.velocity_m_s)
    return (.5 * reduced_mass * _dot(relative, relative), cloud.dispersion_energy_j,
            cloud.mutual_potential_j, estimate_gravity(cloud, body).potential_j)


@dataclass(frozen=True)
class CloudTransport:
    reservoir: DebrisReservoir
    body: SphereState
    scale: float
    expansion_rate_s: float
    expansion_inertia_kg_m2: float
    initial_mutual_potential_j: float
    initial_centre_extent_m: float
    max_fragment_radius_m: float
    initial_self_force_residual_m_s2: float
    energy_offset_j: float
    reference_dynamic_energy_j: float
    energy_scale_j: float
    elapsed_s: float = 0.0
    force_defect_impulse_m_s: float = 0.0

    @property
    def energy_error_j(self):
        return math.fsum((*_energy_terms(self.reservoir, self.body), -self.reference_dynamic_energy_j))

    def budget(self, *, origin_m=(0, 0, 0), frame_velocity_m_s=(0, 0, 0)) -> CollisionBudget:
        """Current model inventory; the explicit initial energy offset is separate."""
        a = self.reservoir.budget(origin_m=origin_m, frame_velocity_m_s=frame_velocity_m_s)
        b = collision_budget([self.body], origin_m=origin_m, frame_velocity_m_s=frame_velocity_m_s)
        return CollisionBudget(
            a.mass_kg + b.mass_kg,
            tuple(math.fsum(v) for v in zip(a.momentum_kg_m_s, b.momentum_kg_m_s, strict=True)),
            tuple(math.fsum(v) for v in zip(a.angular_momentum_kg_m2_s, b.angular_momentum_kg_m2_s, strict=True)),
            a.translational_energy_j + b.translational_energy_j,
            a.rotational_energy_j + b.rotational_energy_j,
            a.self_binding_j + b.self_binding_j,
            math.fsum((a.mutual_potential_j, estimate_gravity(self.reservoir, self.body).potential_j)),
            a.internal_energy_j + b.internal_energy_j)


def start_transport(fragments, body: SphereState) -> CloudTransport:
    """Compress outward homologous velocities and measure the closure's force defect.

    Relative velocities must equal H * relative_position to 1e-12 relative to
    the cloud's velocity scale. Multiple fragments require positive expansion
    energy. A single fragment is the exact point-mass two-body special case.
    """
    states = tuple(fragments)
    cloud = summarize_debris(states)
    positions = [_difference(s.position_m, cloud.centre_m) for s in states]
    velocities = [_difference(s.velocity_m_s, cloud.velocity_m_s) for s in states]
    inertia = math.fsum(s.mass_kg * _dot(r, r) for s, r in zip(states, positions, strict=True))
    if not math.isfinite(inertia):
        raise ValueError('Expansion inertia is outside numerical range')
    rate, residual = 0.0, 0.0
    if inertia > 0:
        rate = math.fsum(s.mass_kg * _dot(r, v) for s, r, v in zip(states, positions, velocities, strict=True)) / inertia
        velocity_scale = max(math.hypot(*v) for v in velocities)
        if rate <= 0 or any(math.dist(v, tuple(rate * x for x in r)) > 1e-12 * velocity_scale
                            for r, v in zip(positions, velocities, strict=True)):
            raise ValueError('Cloud transport requires outward homologous velocities')
        kinetic = .5 * inertia * rate * rate
        if kinetic + cloud.mutual_potential_j <= 1e-12 * (kinetic + abs(cloud.mutual_potential_j)):
            raise ValueError('Cloud expansion must have positive escape energy')
        # Exact constituent self-gravity versus its projection onto r_i = s*r_i0.
        for i, state in enumerate(states):
            acceleration = [0.0, 0.0, 0.0]
            for j, other in enumerate(states):
                if i != j:
                    delta = _difference(other.position_m, state.position_m)
                    distance = math.hypot(*delta)
                    factor = G_SI * other.mass_kg / distance / distance
                    for axis in range(3):
                        acceleration[axis] += factor * (delta[axis] / distance)
            projected = tuple((cloud.mutual_potential_j / inertia) * x for x in positions[i])
            residual = max(residual, math.dist(acceleration, projected))
    centre_extent = max(math.hypot(*r) for r in positions)
    radius = max(s.radius_m for s in states)
    kinetic = .5 * inertia * rate * rate
    cloud = replace(cloud, extent_m=centre_extent + radius, dispersion_energy_j=kinetic)
    terms = _energy_terms(cloud, body)
    if not all(math.isfinite(x) for x in (*terms, rate, residual)):
        raise ValueError('Transport state is outside numerical range')
    cross = math.fsum(_mutual_potential(s, body) for s in states)
    # Preserve the initial inventory without mislabelling model error as heat.
    actual_kinetic = math.fsum(.5 * s.mass_kg * _dot(v, v) for s, v in zip(states, velocities, strict=True))
    offset = math.fsum((cross, -terms[-1], actual_kinetic, -kinetic))
    return CloudTransport(cloud, body, 1.0, rate, inertia, cloud.mutual_potential_j,
                          centre_extent, radius, residual, offset, math.fsum(terms),
                          math.fsum(abs(x) for x in terms))


def advance_transport(state: CloudTransport, duration_s: float, *, max_relative_force_error: float,
                      max_omitted_velocity_change_m_s: float, max_relative_energy_error: float) -> CloudTransport:
    """One kick–drift–kick step, or reject without modifying the input.

    Bounds cover the complete linear drift segment of this numerical step.
    Force-defect impulse accumulates over accepted model paths; it is not a bound
    on the deviation of the actual Newtonian trajectory. Numerical energy error
    is measured against the initial dynamic energy, excluding fixed reservoirs.
    """
    if not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError('Transport duration must be finite and nonnegative')
    for name, limit in (('Force', max_relative_force_error), ('Energy', max_relative_energy_error)):
        if not math.isfinite(limit) or not 0 < limit <= 1:
            raise ValueError(f'{name} error limit must be finite and in (0, 1]')
    if not math.isfinite(max_omitted_velocity_change_m_s) or max_omitted_velocity_change_m_s < 0:
        raise ValueError('Omitted velocity change limit must be finite and nonnegative')
    if duration_s == 0:
        return state
    options = dict(max_relative_force_error=max_relative_force_error,
                   max_tidal_velocity_change_m_s=max_omitted_velocity_change_m_s)
    first = gravity_kick(state.reservoir, state.body, duration_s / 2, **options)
    coefficient = (state.initial_mutual_potential_j / state.expansion_inertia_kg_m2
                   if state.expansion_inertia_kg_m2 > 0 else 0.0)
    half_rate = state.expansion_rate_s + .5 * duration_s * coefficient / state.scale**2
    if half_rate < 0:
        raise ValueError('Step reverses cloud expansion; reduce the timestep')
    scale = state.scale + duration_s * half_rate
    cloud = replace(first.reservoir,
                    centre_m=_vector(x + duration_s * v for x, v in zip(first.reservoir.centre_m,
                                                                       first.reservoir.velocity_m_s, strict=True)),
                    extent_m=scale * state.initial_centre_extent_m + state.max_fragment_radius_m,
                    mutual_potential_j=state.initial_mutual_potential_j / scale)
    body = replace(first.body, position_m=_vector(x + duration_s * v for x, v in zip(
        first.body.position_m, first.body.velocity_m_s, strict=True)))
    # Check closest approach along the whole drift, not just its endpoints.
    initial_delta = _difference(state.body.position_m, state.reservoir.centre_m)
    final_delta = _difference(body.position_m, cloud.centre_m)
    change = _difference(final_delta, initial_delta)
    length_squared = _dot(change, change)
    fraction = min(1.0, max(0.0, -_dot(initial_delta, change) / length_squared)) if length_squared else 0.0
    closest = tuple(x + fraction * d for x, d in zip(initial_delta, change, strict=True))
    envelope = estimate_gravity(replace(state.reservoir, extent_m=cloud.extent_m),
                                replace(state.body, position_m=_vector(x + d for x, d in zip(
                                    state.reservoir.centre_m, closest, strict=True))))
    if envelope.relative_force_error_bound > max_relative_force_error:
        raise ValueError('Drift path exceeds the requested force accuracy')
    defect = state.force_defect_impulse_m_s + duration_s * (
        state.initial_self_force_residual_m_s2 / state.scale**2 + envelope.tidal_acceleration_bound_m_s2)
    if defect > max_omitted_velocity_change_m_s:
        raise ValueError('Accumulated force defect exceeds the omitted velocity limit')
    second = gravity_kick(cloud, body, duration_s / 2, **options)
    rate = half_rate + .5 * duration_s * coefficient / scale**2
    if rate < 0:
        raise ValueError('Step reverses cloud expansion; reduce the timestep')
    result = replace(state, reservoir=replace(second.reservoir, dispersion_energy_j=(
        .5 * state.expansion_inertia_kg_m2 * rate * rate)), body=second.body, scale=scale,
                     expansion_rate_s=rate, elapsed_s=state.elapsed_s + duration_s,
                     force_defect_impulse_m_s=defect)
    if abs(result.energy_error_j) > max_relative_energy_error * state.energy_scale_j:
        raise ValueError('Accumulated energy error exceeds the requested limit; reduce the timestep')
    return result
