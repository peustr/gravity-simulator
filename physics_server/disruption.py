"""LS12 head-on gravity-regime disruption curves, with explicit SI inputs.

These numerical primitives do not select collision regimes or validate a body's
material/size against the calibration domain. See docs/impact-scaling.md.
"""
from dataclasses import dataclass
import math
from typing import Literal

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
