"""Connect calibrated mass outcomes to conditional isolated-sphere states (SI).

Layouts and energy partitions remain caller prescriptions, not ejecta fits.
Nothing here mutates the live simulation. See docs/collision-budgets.md.
"""
from dataclasses import dataclass, replace
import math

import numpy as np

from collision_outcomes import SphereState, allocate_remnants, merge_spheres
from disruption import ContactOutcome, classify_contact
from impacts import Impact
from units import G_SI


def _impact(a, b):
    return Impact(a.mass_kg, b.mass_kg, a.radius_m, b.radius_m,
                  tuple(np.subtract(b.position_m, a.position_m)),
                  tuple(np.subtract(b.velocity_m_s, a.velocity_m_s)), G_SI)


def surface_contact(a: SphereState, b: SphereState) -> tuple[SphereState, SphereState]:
    """Project a shallow sample onto contact, conserving point-mass E and L.

    Preserve the sampled separation direction and COM state. This is a local
    correction, not a Kepler propagation to an earlier collision time. Inside
    contact the pre-correction potential is explicitly the point-mass -Gm1m2/r,
    not the potential of overlapping extended spheres.
    """
    impact = _impact(a, b)
    distance, radius = impact.separation, impact.contact_distance
    if not math.isclose(distance, radius, rel_tol=1e-4, abs_tol=0):
        raise ValueError('Contact reconstruction requires a shallow surface sample')
    if impact.radial_speed >= 0:
        raise ValueError('Contact reconstruction requires approaching bodies')
    if math.isclose(distance, radius, rel_tol=1e-12, abs_tol=0):
        return a, b
    normal = np.array(impact.normal)
    radial = impact.radial_speed
    tangent = np.array(impact.relative_velocity) - radial * normal
    scale = distance / radius
    # h = r x v is fixed; v_contact^2 = v_sample^2 + 2GM(1/R - 1/r).
    radial_squared = math.fsum((radial**2, float(tangent @ tangent) * (1 - scale) * (1 + scale),
                               2 * G_SI * impact.total_mass * ((distance - radius) / distance) / radius))
    if not math.isfinite(radial_squared) or radial_squared <= 0:
        raise ValueError('No approaching surface state at the sampled energy and angular momentum')
    relative_velocity = scale * tangent - math.sqrt(radial_squared) * normal
    fraction = b.mass_kg / impact.total_mass
    centre = np.array(a.position_m) + fraction * np.array(impact.relative_position)
    bulk_velocity = np.array(a.velocity_m_s) + fraction * np.array(impact.relative_velocity)
    return (replace(a, position_m=centre - fraction * radius * normal,
                    velocity_m_s=bulk_velocity - fraction * relative_velocity),
            replace(b, position_m=centre + (1 - fraction) * radius * normal,
                    velocity_m_s=bulk_velocity + (1 - fraction) * relative_velocity))


def remnant_escape_check(states) -> str:
    """Certify isolated fixed-sphere escape, or reject an inconclusive proposal.

    Two bodies: outgoing hyperbolic relative orbit. More bodies: a sufficient
    all-pairs separation bound, u_min^2 > 8GM/d_min. Bound debris is outside
    this certificate even when the largest remnants could escape in reality.
    """
    states = tuple(states)
    if len(states) < 2:
        raise ValueError('Remnant escape requires at least two remnants')
    separations, radial_speeds = [], []
    for i, a in enumerate(states):
        for b in states[i + 1:]:
            relative = _impact(a, b)
            if relative.separation < (a.radius_m + b.radius_m) * (1 - 1e-12):
                raise ValueError('Remnant escape requires non-overlapping remnants')
            if not all(math.isfinite(x) for x in (relative.separation, relative.radial_speed)):
                raise ValueError('Remnant escape calculation is outside numerical range')
            if relative.radial_speed <= 0:
                raise ValueError('Remnant escape requires receding remnants')
            separations.append(relative.separation)
            radial_speeds.append(relative.radial_speed)
    total = math.fsum(s.mass_kg for s in states)
    if len(states) == 2:
        speed = _impact(*states).speed
        binding = 2 * G_SI * total / separations[0]
        method = 'two_body_hyperbolic'
    else:
        speed = min(radial_speeds)
        binding = 8 * G_SI * total / min(separations)
        method = 'all_pairs_escape_bound'
    kinetic = speed * speed
    if not math.isfinite(kinetic + binding):
        raise ValueError('Remnant escape calculation is outside numerical range')
    if kinetic - binding <= 1e-12 * max(kinetic, binding):
        raise ValueError('Remnant escape is not established for the proposed allocation')
    return method


@dataclass(frozen=True)
class ConstructedCollision:
    classification: ContactOutcome
    contact: tuple[SphereState, SphereState]
    remnants: tuple[SphereState, ...]
    escape_certificate: str | None


def construct_collision(a: SphereState, b: SphereState, *, material: str, body_types: tuple[int, int],
                        layout=None, expansion_fraction: float | None = None) -> ConstructedCollision:
    """Classify a contact and construct only a compatible, feasible outcome.

    Nonrotating inputs only, as required by the classifier. Merging needs no
    layout or energy fraction. Other regimes require both; layout order is
    largest remnant, runner (hit-and-run only), then debris. Uniform density is
    retained and separated remnants must pass an escape certificate. Rejection
    never silently changes masses, parameters or regime.
    """
    if any(component != 0 for s in (a, b) for component in s.spin_kg_m2_s):
        raise ValueError('Calibrated construction requires nonrotating inputs')
    contact = surface_contact(a, b)
    classification = classify_contact(_impact(*contact), unit_system='si', material=material, body_types=body_types)
    if classification.regime in ('merging', 'graze_and_merge'):
        if layout is not None or expansion_fraction is not None:
            raise ValueError('A classified merger does not accept a fragment layout or energy split')
        return ConstructedCollision(classification, contact, (merge_spheres(*contact),), None)
    if layout is None or expansion_fraction is None:
        raise ValueError('Multiple remnants require a layout and explicit expansion fraction')
    specs = tuple(layout)
    required = [classification.largest_remnant_mass_kg]
    if classification.runner_mass_kg > 0:
        required.append(classification.runner_mass_kg)
    if len(specs) < len(required) or any(not math.isclose(s.mass_kg, m, rel_tol=1e-12, abs_tol=0)
                                       for s, m in zip(specs[:len(required)], required, strict=True)):
        raise ValueError('Layout must preserve the classified largest remnant and runner in order')
    debris = specs[len(required):]
    if not math.isclose(math.fsum(s.mass_kg for s in debris), classification.remaining_mass_kg,
                        rel_tol=1e-12, abs_tol=0):
        raise ValueError('Layout debris must close the classified remaining mass')
    if any(s.mass_kg > classification.largest_remnant_mass_kg * (1 + 1e-12) for s in debris):
        raise ValueError('A debris fragment cannot exceed the classified largest remnant')
    total = a.mass_kg + b.mass_kg
    volume_radius = max(a.radius_m, b.radius_m) * (1 + (min(a.radius_m, b.radius_m)
                                                       / max(a.radius_m, b.radius_m))**3)**(1 / 3)
    for s in specs:
        expected_radius = volume_radius * (s.mass_kg / total)**(1 / 3)
        if not math.isclose(s.radius_m, expected_radius, rel_tol=1e-12, abs_tol=0):
            raise ValueError('Remnant radii must retain the incoming mean density')
    remnants = allocate_remnants(*contact, specs, expansion_fraction=expansion_fraction)
    escape = remnant_escape_check(remnants)
    return ConstructedCollision(classification, contact, remnants, escape)
