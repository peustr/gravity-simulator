"""Connect calibrated mass outcomes to conditional isolated-sphere states (SI).

Layouts and energy partitions remain caller prescriptions, not ejecta fits.
Nothing here mutates the live simulation. See docs/collision-budgets.md.
"""
from dataclasses import dataclass, replace
import math

import numpy as np

from collision_outcomes import RemnantSpec, SphereState, _mutual_potential, allocate_remnants, merge_spheres
from disruption import ContactOutcome, classify_contact, _supported_contact
from impacts import Impact
from units import G_SI
from debris_shell import symmetric_directions, form_shell


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
    mass-weighted all-pairs impulse bound. Bound debris is outside
    this certificate even when the largest remnants could escape in reality.
    """
    states = tuple(states)
    if len(states) < 2:
        raise ValueError('Remnant escape requires at least two remnants')
    separations, radial_speeds, pairs = [], [], []
    impulse_bounds = [0.0] * len(states)
    for i, a in enumerate(states):
        for j, b in enumerate(states[i + 1:], i + 1):
            relative = _impact(a, b)
            if relative.separation < (a.radius_m + b.radius_m) * (1 - 1e-12):
                raise ValueError('Remnant escape requires non-overlapping remnants')
            if not all(math.isfinite(x) for x in (relative.separation, relative.radial_speed)):
                raise ValueError('Remnant escape calculation is outside numerical range')
            if relative.radial_speed <= 0:
                raise ValueError('Remnant escape requires receding remnants')
            separations.append(relative.separation)
            radial_speeds.append(relative.radial_speed)
            pairs.append((i, j))
            # If every radial speed remains above half its initial value,
            # integrating G*m/(d + u*t/2)^2 bounds the total gravity impulse.
            impulse_bounds[i] += 2 * G_SI * b.mass_kg / relative.separation / float(relative.radial_speed)
            impulse_bounds[j] += 2 * G_SI * a.mass_kg / relative.separation / float(relative.radial_speed)
    total = math.fsum(s.mass_kg for s in states)
    if len(states) == 2:
        speed = _impact(*states).speed
        binding = 2 * G_SI * total / separations[0]
        method = 'two_body_hyperbolic'
    else:
        # The pair's radial acceleration is >= -(|a_i| + |a_j|).
        # Strict margins close the bootstrap assumption above for all time.
        if not all(math.isfinite(value) for value in impulse_bounds):
            raise ValueError('Remnant escape calculation is outside numerical range')
        if any(2 * (impulse_bounds[i] + impulse_bounds[j]) >= u * (1 - 1e-12)
               for (i, j), u in zip(pairs, radial_speeds, strict=True)):
            raise ValueError('Remnant escape is not established for the proposed allocation')
        return 'all_pairs_escape_bound'
    kinetic = speed * speed
    if not math.isfinite(kinetic + binding):
        raise ValueError('Remnant escape calculation is outside numerical range')
    if kinetic - binding <= 1e-12 * max(kinetic, binding):
        raise ValueError('Remnant escape is not established for the proposed allocation')
    return method


def _resolved_layout(contact, classification):
    """Bounded equal-mass debris on a coarse spherical shell; not an ejecta fit."""
    masses = [classification.largest_remnant_mass_kg]
    if classification.runner_mass_kg:
        masses.append(classification.runner_mass_kg)
    remaining = classification.remaining_mass_kg
    count = math.ceil(remaining / masses[0])
    impact = _impact(*contact)
    central = (classification.runner_mass_kg == 0 and 2 <= count <= 30
               and impact.impact_parameter <= 1e-12)
    directions = symmetric_directions(count) if central else None
    if central:
        count = len(directions)
    if len(masses) + count > 32:
        raise ValueError('Impact requires more than 32 remnants; no compact layout supports this allocation')
    masses.extend([remaining / count] * count)
    a, b = contact
    radius = (a.radius_m**3 + b.radius_m**3)**(1 / 3)
    total = a.mass_kg + b.mass_kg
    layout = []
    for i, mass in enumerate(masses):
        if central:
            direction = np.zeros(3) if i == 0 else directions[i-1]
        elif len(masses) == 2:
            direction = (2*i - 1) * np.array(impact.normal)
        else:
            z = 1 - 2 * (i + .5) / len(masses)
            phi = i * math.pi * (3 - math.sqrt(5))
            rho = math.sqrt(1 - z*z)
            direction = (rho * math.cos(phi), rho * math.sin(phi), z)
        offset = tuple(8 * radius * x for x in direction)
        layout.append(RemnantSpec(mass, radius * (mass / total)**(1 / 3), offset))
    return tuple(layout)


def intact_hit_and_run(a, b):
    """Local frictionless rebound; retain half the normal kinetic energy.

    Restitution and heat partition are prescriptions, not calibrated ejecta
    fits. Tangential velocity, individual radii and existing heat are retained.
    """
    impact = _impact(a, b)
    fraction = b.mass_kg / impact.total_mass
    change = -(1 + math.sqrt(.5)) * impact.radial_speed * np.array(impact.normal)
    heat = .25 * impact.reduced_mass * impact.radial_speed**2
    remnants = (
        replace(a, velocity_m_s=np.array(a.velocity_m_s) - fraction * change,
                internal_energy_j=a.internal_energy_j + (1 - fraction) * heat),
        replace(b, velocity_m_s=np.array(b.velocity_m_s) + (1 - fraction) * change,
                internal_energy_j=b.internal_energy_j + fraction * heat),
    )
    return tuple(sorted(remnants, key=lambda s: s.mass_kg, reverse=True))


def couple_external_gravity(incoming, remnants, external, *, contact_impulse=False, spherical_sticking=False):
    """Close external work for isolated layouts, local impulses or a sphere.

    Isolated layouts retain the 1e-4 field bound. Prescribed spherical sticking
    instead requires spin plus tidal surface retention. Neither certifies
    long-term escape or fluid-shape stability. Impulses retain masses/positions.
    """
    external = tuple(external)
    if contact_impulse and (spherical_sticking or len(remnants) != 2 or any(
            s.mass_kg != r.mass_kg or s.radius_m != r.radius_m
            or tuple(s.position_m) != tuple(r.position_m)
            for s, r in zip(incoming, remnants, strict=True))):
        raise ValueError('Contact impulse must retain both bodies at their sampled positions')
    if contact_impulse:
        return remnants  # Identical masses/positions: external potential is identical.
    if not external and not spherical_sticking:
        return remnants
    a, b = incoming
    total = a.mass_kg + b.mass_kg
    contact = a.radius_m + b.radius_m
    if spherical_sticking:
        if len(remnants) != 1 or not math.isclose(remnants[0].mass_kg,total,rel_tol=1e-12):
            raise ValueError('Spherical sticking requires one mass-conserving remnant')
        remnant = remnants[0]
        gradient = 0.
        for source in external:
            clearance = math.dist(source.position_m,remnant.position_m)-remnant.radius_m
            if clearance <= source.radius_m:
                raise ValueError('External body intersects the spherical remnant')
            gradient += 2*G_SI*source.mass_kg/clearance**3
        centrifugal = (math.hypot(*remnant.spin_kg_m2_s)/remnant.inertia_kg_m2)**2
        if centrifugal+gradient >= G_SI*remnant.mass_kg/remnant.radius_m**3:
            raise ValueError('Spin plus external tides exceed spherical surface retention')
    else:
        centre = np.array(a.position_m) + b.mass_kg / total * np.subtract(b.position_m, a.position_m)
        extent = max(math.dist(s.position_m, centre) + s.radius_m for s in (*incoming, *remnants))
        gradient = 0.0
        for source in external:
            clearance = math.dist(source.position_m, centre) - extent
            if clearance <= source.radius_m:
                raise ValueError('External body intersects the impact construction region')
            # The operator norm of the point-mass acceleration gradient is 2GM/r^3.
            gradient += 2 * G_SI * source.mass_kg / clearance**3
        ratio = 2 * extent * gradient / (G_SI * total / contact**2)
        if not math.isfinite(ratio) or (ratio > 1e-4 and not contact_impulse):
            raise ValueError('External tidal acceleration exceeds the isolated-impact limit (1e-4)')
    correction = math.fsum([_mutual_potential(s, source) for source in external for s in incoming] +
                           [-_mutual_potential(s, source) for source in external for s in remnants])
    relative_energy = .5 * a.mass_kg * (b.mass_kg / total) * math.dist(a.velocity_m_s, b.velocity_m_s)**2
    energy_scale = max(relative_energy, G_SI * a.mass_kg / contact * b.mass_kg)
    if not math.isfinite(correction) or (abs(correction) > 1e-4 * energy_scale and not spherical_sticking):
        raise ValueError('External potential correction exceeds the isolated-impact limit (1e-4)')
    # A negative inventory is rejected by SphereState before any live mutation.
    return tuple(replace(s, internal_energy_j=s.internal_energy_j + correction * (s.mass_kg / total))
                 for s in remnants)


def _gentle_impact(a, b, material, body_types):
    impact = _impact(a,b)
    _supported_contact(impact,material,body_types)
    if (material != 'fluid_planets' or tuple(body_types) != (0,0)
            or impact.speed >= 1.08*impact.escape_speed
            or any(math.hypot(*s.spin_kg_m2_s) >= s.inertia_kg_m2*math.sqrt(G_SI*s.mass_kg/s.radius_m)/s.radius_m for s in (a,b))):
        raise ValueError('Outside the gentle-contact speed, material or input-spin domain')
    surface_contact(a,b)  # A valid earlier surface state must exist.
    return impact


def _gentle_merger(a,b,material,body_types):
    impact = _gentle_impact(a,b,material,body_types)
    contact = surface_contact(a,b)
    impact = _impact(*contact)
    remnant = merge_spheres(*contact)
    bound = impact.kinetic_energy+sum(s.rotational_energy_j for s in contact) < G_SI*a.mass_kg*b.mass_kg/impact.separation
    classification = ContactOutcome('bound_sticking' if bound else 'gentle_sticking', remnant.mass_kg,
                                    0.,None,impact.specific_energy,None,None)
    return ConstructedCollision(classification,contact,(remnant,),None)


def gentle_rebound(a, b, *, material, body_types):
    """Conditional smooth-sphere rebound for a gentle rocky contact.

    Elastic normal restitution retains both masses/radii and incoming spins.
    The central impulse conserves angular momentum and kinetic energy without
    inventing an uncalibrated dissipation coefficient. This is a prescription, not a
    rotating-impact calibration or an escape claim. Bound pairs remain live.
    """
    contact = (a, b)
    impact = _gentle_impact(a, b, material, body_types)
    impulse = -2 * impact.reduced_mass * impact.radial_speed * np.array(impact.normal)
    remnants = tuple(replace(s, velocity_m_s=np.add(s.velocity_m_s, sign * impulse / s.mass_kg))
                     for s, sign in zip(contact, (-1, 1), strict=True))
    classification = ContactOutcome('gentle_rebound', max(a.mass_kg, b.mass_kg), 0., None,
                                    impact.specific_energy, None, None, min(a.mass_kg, b.mass_kg))
    return ConstructedCollision(classification, contact, remnants, None)


@dataclass(frozen=True)
class ConstructedCollision:
    classification: ContactOutcome
    contact: tuple[SphereState, SphereState]
    remnants: tuple[SphereState, ...]
    escape_certificate: str | None
    central_shell: bool = False


def construct_collision(a: SphereState, b: SphereState, *, material: str, body_types: tuple[int, int],
                        layout=None, expansion_fraction: float | None = None,
                        resolved_policy: bool = False, allow_gentle_contacts: bool = False) -> ConstructedCollision:
    """Construct in the pair's rest frame to resolve contact at orbital distances."""
    fraction = b.mass_kg / (a.mass_kg + b.mass_kg)
    separation = np.subtract(b.position_m, a.position_m)
    relative = np.subtract(b.velocity_m_s, a.velocity_m_s)
    centre = np.array(a.position_m) + fraction * separation
    bulk = np.array(a.velocity_m_s) + fraction * relative
    local = tuple(replace(s, position_m=weight * separation, velocity_m_s=weight * relative)
                  for s, weight in ((a, -fraction), (b, 1 - fraction)))
    try:
        result = _construct_collision(*local, material=material, body_types=body_types, layout=layout,
                                      expansion_fraction=expansion_fraction, resolved_policy=resolved_policy)
    except ValueError as original:
        if not allow_gentle_contacts or layout is not None or expansion_fraction is not None:
            raise
        if not any(component for state in local for component in state.spin_kg_m2_s):
            # A failed allocation must not overwrite calibrated mass losses.
            try:
                reference = classify_contact(_impact(*surface_contact(*local)), unit_system='si',
                                             material=material, body_types=body_types)
            except ValueError:
                reference = None
            if reference is not None and reference.regime not in ('merging','graze_and_merge'):
                raise original from None
        try:
            result = _gentle_merger(*local,material,body_types)
        except ValueError:
            try:
                return gentle_rebound(a,b,material=material,body_types=body_types)
            except ValueError as unsupported:
                raise ValueError(f'{original}; gentle-contact fallback: {unsupported}') from None

    def translated(states):
        return tuple(replace(s, position_m=np.add(s.position_m, centre),
                             velocity_m_s=np.add(s.velocity_m_s, bulk)) for s in states)

    return replace(result, contact=translated(result.contact), remnants=translated(result.remnants))


def _construct_collision(a: SphereState, b: SphereState, *, material: str, body_types: tuple[int, int],
                         layout=None, expansion_fraction: float | None = None,
                         resolved_policy: bool = False) -> ConstructedCollision:
    """Classify a contact and construct only a compatible, feasible outcome.

    Calibrated inputs are nonrotating. Merging needs no
    layout or energy fraction. Other regimes require both; layout order is
    largest remnant, runner (hit-and-run only), then debris. Fragment allocations
    retain mean density; intact runners retain their individual radii. Separated
    remnants must pass an escape certificate. Rejection
    never silently changes masses, parameters or regime.
    """
    if resolved_policy and (layout is not None or expansion_fraction is not None):
        raise ValueError('Resolved policy cannot be combined with a prescribed allocation')
    if any(component for state in (a,b) for component in state.spin_kg_m2_s):
        raise ValueError('Calibrated construction requires nonrotating inputs')
    contact = surface_contact(a,b)
    classification = classify_contact(_impact(*contact),unit_system='si',material=material,body_types=body_types)
    if classification.regime in ('merging', 'graze_and_merge'):
        if layout is not None or expansion_fraction is not None:
            raise ValueError('A classified merger does not accept a fragment layout or energy split')
        remnant = merge_spheres(*contact)
        return ConstructedCollision(classification, contact, (remnant,), None)
    if resolved_policy:
        if classification.regime == 'hit_and_run' and classification.remaining_mass_kg == 0:
            remnants = intact_hit_and_run(*contact)
            return ConstructedCollision(classification, contact, remnants, remnant_escape_check(remnants))
        layout, expansion_fraction = _resolved_layout(contact, classification), .5
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
    central = resolved_policy and len(specs) > 2 and specs[0].offset_m == (0.0,0.0,0.0)
    if central:
        shell = form_shell(remnants[0],remnants[1:],1)
        gravity = -G_SI*remnants[0].mass_kg*shell.mass_kg/shell.radius_m
        kinetic = .5*shell.mass_kg*shell.radial_speed_m_s**2
        if kinetic+shell.self_potential_j+gravity <= 1e-12*(kinetic-shell.self_potential_j-gravity):
            raise ValueError('Symmetric shell does not have positive escape energy')
        escape = 'symmetric_shell_escape'
    else:
        escape = remnant_escape_check(remnants)
    return ConstructedCollision(classification, contact, remnants, escape, central)


def couple_collision(incoming, outcome, external, *, material, body_types, allow_gentle_contacts=False):
    """Couple contact prescriptions; never overwrite calibrated mass losses."""
    external = tuple(external)
    active = allow_gentle_contacts and material == 'fluid_planets' and tuple(body_types) == (0,0)
    regime = outcome.classification.regime

    def prescribed(tag, states):
        return replace(outcome, remnants=states, escape_certificate=None,
                       classification=replace(outcome.classification, regime=tag,
                                              disruption_energy_j_kg=None, merging_speed_m_s=None,
                                              interacting_fraction=None))

    if regime == 'gentle_rebound':
        return replace(outcome,remnants=couple_external_gravity(incoming,outcome.remnants,external,contact_impulse=True))
    if not (active and regime in ('bound_sticking','gentle_sticking')):
        try:
            return replace(outcome,remnants=couple_external_gravity(incoming,outcome.remnants,external))
        except ValueError:
            if not active:
                raise
            if regime == 'hit_and_run' and outcome.classification.remaining_mass_kg == 0:
                states = intact_hit_and_run(*incoming)
                states = couple_external_gravity(incoming,states,external,contact_impulse=True)
                return prescribed('contact_rebound',states)
            if len(outcome.remnants) != 1 or regime not in ('merging','graze_and_merge'):
                raise
    try:
        states = couple_external_gravity(incoming,outcome.remnants,external,spherical_sticking=True)
    except ValueError as unsupported:
        try:
            rebound = gentle_rebound(*incoming,material=material,body_types=body_types)
        except ValueError:
            raise unsupported from None
        return replace(rebound,remnants=couple_external_gravity(incoming,rebound.remnants,external,contact_impulse=True))
    return prescribed(regime if regime in ('bound_sticking','gentle_sticking') else 'gentle_sticking',states)
