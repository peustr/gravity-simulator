"""LS12 disruption curves and restricted solid-body contact classification.

The scalar curves are numerical primitives. Contact classifiers enforce the
implementation envelopes documented in docs/impact-scaling.md.
"""
from dataclasses import dataclass
import math
from typing import Literal

from impacts import Impact
import units
from units import G_SI


# Leinhardt & Stewart (2012), section 3.1.4. Selection is explicit: a rendered
# body type or density alone does not determine its material response.
_CALIBRATIONS = {'fluid_planets': (1.9, 0.36), 'planetesimals': (5.0, 0.37)}


@dataclass(frozen=True)
class DisruptionEstimate:
    disruption_energy_j_kg: float
    specific_energy_j_kg: float
    largest_remnant_mass_kg: float
    remaining_mass_kg: float


def largest_remnant_fraction(energy_ratio: float) -> float:
    """LS12 equations 5 and 44: M_lr/M_tot for Q_R/Q*_RD >= 0.

    The low-energy limit is a mathematical continuation, not a merging decision.
    The remainder is unassigned mass, not a resolved fragment distribution.
    """
    if not math.isfinite(energy_ratio) or energy_ratio < 0:
        raise ValueError('Energy ratio must be finite and nonnegative')
    if energy_ratio <= 1.8:
        return 1.0 - 0.5 * energy_ratio
    return 0.1 * (energy_ratio / 1.8)**-1.5


def estimate_head_on_disruption(
    mass_a_kg: float, mass_b_kg: float, speed_m_s: float, *,
    material: Literal['fluid_planets', 'planetesimals'],
) -> DisruptionEstimate:
    """Estimate disruption at a supplied head-on contact speed, in SI units.

    Applies LS12 equations 23 and 28, then the largest-remnant curve. No radius,
    angle, spin, escape/merging gate or particle capacity is inferred. A caller
    must establish applicability before using this curve to select an outcome.
    """
    if material not in _CALIBRATIONS:
        raise ValueError('Unknown disruption calibration')
    for mass in (mass_a_kg, mass_b_kg):
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError('Masses must be finite and positive')
    if not math.isfinite(speed_m_s) or speed_m_s < 0:
        raise ValueError('Speed must be finite and nonnegative')

    c_star, mu_bar = _CALIBRATIONS[material]
    total = mass_a_kg + mass_b_kg
    gamma = min(mass_a_kg, mass_b_kg) / max(mass_a_kg, mass_b_kg)
    # R_C1 is the combined-mass radius at the reference density of 1000 kg/m^3,
    # not either body's physical radius or the density of its material.
    reference_radius = (3 * total / (4 * math.pi * 1000))**(1 / 3)
    equal_mass_threshold = c_star * (4 / 5) * math.pi * 1000 * G_SI * reference_radius**2
    threshold = equal_mass_threshold * ((1 + gamma)**2 / (4 * gamma))**(2 / (3 * mu_bar) - 1)
    reduced_fraction = gamma / (1 + gamma)**2
    specific_energy = 0.5 * reduced_fraction * speed_m_s**2
    largest = total * largest_remnant_fraction(specific_energy / threshold)
    return DisruptionEstimate(threshold, specific_energy, largest, total - largest)


@dataclass(frozen=True)
class ContactOutcome:
    regime: str
    largest_remnant_mass_kg: float
    remaining_mass_kg: float
    disruption_energy_j_kg: float
    specific_energy_j_kg: float
    interacting_fraction: float
    merging_speed_m_s: float
    runner_mass_kg: float = 0.0


def _contact_in_si(impact, unit_system):
    if unit_system == 'si':
        return impact
    if unit_system != units.SYSTEM:
        raise ValueError('Unsupported contact unit system')
    return Impact(impact.mass_a * units.MASS_KG, impact.mass_b * units.MASS_KG,
                  impact.radius_a * units.LENGTH_M, impact.radius_b * units.LENGTH_M,
                  tuple(x * units.LENGTH_M for x in impact.relative_position),
                  tuple(v * units.VELOCITY_M_S for v in impact.relative_velocity),
                  impact.gravity * G_SI / units.G)


def _supported_contact(impact, material, body_types):
    if material not in _CALIBRATIONS:
        raise ValueError('Unknown disruption calibration')
    # World type IDs: ROCKY=0 and ASTEROID=5. Gas/stellar/compact objects need
    # separate laws; a material selection alone must not admit those types.
    if len(body_types) != 2 or any(kind not in (0, 5) for kind in body_types):
        raise ValueError('Only solid body types are supported')
    if len(impact.relative_position) != 3 or len(impact.relative_velocity) != 3:
        raise ValueError('Contact vectors must have three components')
    values = (impact.mass_a, impact.mass_b, impact.radius_a, impact.radius_b,
              impact.gravity, *impact.relative_position, *impact.relative_velocity)
    if not all(math.isfinite(x) for x in values):
        raise ValueError('Contact values must be finite')
    if min(impact.mass_a, impact.mass_b, impact.radius_a, impact.radius_b) <= 0:
        raise ValueError('Contact masses and radii must be positive')
    if not math.isclose(impact.gravity, G_SI, rel_tol=1e-12, abs_tol=0):
        raise ValueError('Contact requires physical Newtonian gravity')

    (mt, rt), (mp, rp) = sorted(((impact.mass_a, impact.radius_a),
                               (impact.mass_b, impact.radius_b)), reverse=True)
    # Conservative implementation limits, not sharp physical transitions.
    if material == 'fluid_planets':
        size, low, high, min_ratio, max_speed = mt, .1 * 5.9722e24, 10 * 5.9722e24, .1, 80_000
    else:
        size, low, high, min_ratio, max_speed = rt, 1_000, 100_000, .025, 5_000
    if not low * (1 - 1e-12) <= size <= high * (1 + 1e-12) or mp / mt < min_ratio * (1 - 1e-12):
        raise ValueError('Contact size or mass ratio is outside the implementation envelope')
    densities = [mass / radius / radius / radius / ((4 / 3) * math.pi)
                 for mass, radius in ((mt, rt), (mp, rp))]
    if not all(1000 * (1 - 1e-12) <= rho <= 8000 * (1 + 1e-12) for rho in densities):
        raise ValueError('Contact density is outside the solid-body envelope')
    if not math.isclose(*densities, rel_tol=1e-6):
        raise ValueError('Contact requires equal bulk densities')
    if not 0 < impact.speed <= max_speed:
        raise ValueError('Contact speed is outside the implementation envelope')
    # The native step guard targets 1e-4 of the summed radii. Do not silently
    # classify deep initial overlaps or distant flybys as surface impacts.
    if not math.isclose(impact.separation, impact.contact_distance, rel_tol=1e-4, abs_tol=0):
        raise ValueError('Contact must be sampled at the physical surfaces')
    if impact.radial_speed >= 0:
        raise ValueError('Contact must be approaching')
    return mt, rt, mp, rp, impact.impact_parameter


def _grazing_merging_ratio(gamma, b):
    """Genda et al. (2012), equation 16, relative to mutual surface escape.

    Gamma is NOT squared, and the 1.86 term has no Gamma factor in the original.
    """
    asymmetry = (1 - gamma) / (1 + gamma)
    return (2.43 * asymmetry + 1.86) * (1 - b)**2.5 - .0408 * asymmetry + 1.08


def _reverse_interacting_mass(mt, rt, rp, b):
    """LS12 equations 46–48: cross-sectional area times chord times density."""
    length = (rt + rp) * (1 - b)
    cap = min(1.0, length / rp)  # grazing: at most one projectile radius
    area = rp**2 * (math.acos(1 - cap) - (1 - cap) * math.sqrt(cap * (2 - cap)))
    chord = 2 * math.sqrt(rt * length - length**2 / 4)
    density = mt / ((4 / 3) * math.pi * rt**3)
    return density * area * chord


def _check_grazing_domain(mt, mp, b, material, body_types):
    # Genda's fit concerns nonspinning rocky protoplanets, not small aggregates.
    if material != 'fluid_planets' or tuple(body_types) != (0, 0):
        raise ValueError('Grazing classification requires rocky protoplanets')
    if not .2 * (1 - 1e-12) <= (mt + mp) / 5.9722e24 <= 2 * (1 + 1e-12):
        raise ValueError('Grazing total mass is outside the implementation envelope')
    if mp / mt < (1 / 9) * (1 - 1e-12) or b > math.sin(math.radians(75)) + 1e-12:
        raise ValueError('Grazing mass ratio or angle is outside the implementation envelope')


def _classify_contact(impact, unit_system, material, body_types, *, allow_grazing):
    impact = _contact_in_si(impact, unit_system)
    mt, rt, mp, rp, b = _supported_contact(impact, material, body_types)
    critical_b = rt / (rt + rp)
    grazing = b >= critical_b or math.isclose(b, critical_b, rel_tol=0, abs_tol=1e-12)
    if grazing:
        if not allow_grazing:
            raise ValueError('Grazing contacts require a separate outcome model')
        _check_grazing_domain(mt, mp, b, material, body_types)
    # LS12 equations 11, 12 and 15. The clipped spherical cap is a fraction
    # of the projectile, not the geometric intersection volume of two spheres.
    cap_height = min(2.0, (rt + rp) * (1 - b) / rp)
    alpha = cap_height**2 * (3 - cap_height) / 4
    mu_ratio = (mt + alpha * mp) / (alpha * (mt + mp))
    head_on = estimate_head_on_disruption(mt, mp, impact.speed, material=material)
    mu_bar = _CALIBRATIONS[material][1]
    threshold = head_on.disruption_energy_j_kg * mu_ratio**(2 - 1.5 * mu_bar)
    ratio = head_on.specific_energy_j_kg / threshold

    # Equation 53 uses the radius of the combined interacting mass at the
    # common bulk density, NOT the sum of the two original surface radii.
    interacting_radius = (rt**3 + alpha * rp**3)**(1 / 3)
    merging_speed = math.sqrt(2 * G_SI * (mt + alpha * mp) / interacting_radius)
    runner = 0.0
    if grazing:
        # Use Genda's surface-escape normalization, not the LS12 interacting
        # escape scale: those two merging boundaries are different models.
        merging_speed = _grazing_merging_ratio(mp / mt, b) * impact.escape_speed
    if grazing and ratio < 2 * mp / (mt + mp):
        if impact.speed < merging_speed:
            regime, fraction = 'graze_and_merge', 1.0
        else:
            regime, fraction = 'hit_and_run', mt / (mt + mp)
            interacting_mass = _reverse_interacting_mass(mt, rt, rp, b)
            reverse = estimate_head_on_disruption(mp, interacting_mass, impact.speed, material=material)
            # The idealized target stays intact. Cap the reverse estimate at
            # the original projectile inventory to avoid counting target mass twice.
            runner = min(mp, reverse.largest_remnant_mass_kg)
    elif not grazing and impact.speed < merging_speed:
        regime, fraction = 'merging', 1.0
    else:
        fraction = largest_remnant_fraction(ratio)
        if ratio >= 1.8:
            regime = 'supercatastrophic_disruption'
        elif ratio >= 1:
            regime = 'disruption'
        elif ratio >= 2 * mp / (mt + mp):
            regime = 'erosion'
        else:
            regime = 'partial_accretion'
    if regime == 'hit_and_run':
        largest, remaining = mt, mp - runner
    else:
        largest = (mt + mp) * fraction
        remaining = mt + mp - largest
    return ContactOutcome(regime, largest, remaining, threshold,
                          head_on.specific_energy_j_kg, alpha, merging_speed, runner)


def classify_contact(impact: Impact, *, unit_system: str, material: str,
                     body_types: tuple[int, int]) -> ContactOutcome:
    """Classify supported nonrotating solids, including rocky grazing impacts.

    Returns SI remnant masses without particle creation or capacity limits.
    Unsupported units, materials and encounter domains raise ValueError.
    """
    return _classify_contact(impact, unit_system, material, body_types, allow_grazing=True)


def classify_non_grazing(impact: Impact, *, unit_system: str, material: str,
                         body_types: tuple[int, int]) -> ContactOutcome:
    """Restricted entry point retaining explicit rejection of grazing contacts."""
    return _classify_contact(impact, unit_system, material, body_types, allow_grazing=False)
