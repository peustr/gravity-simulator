"""Published curve references and dimensional checks for head-on disruption."""
from dataclasses import FrozenInstanceError
import math

import pytest

from disruption import estimate_head_on_disruption, largest_remnant_fraction
from units import G_SI


@pytest.mark.parametrize('speed,predicted_fraction', [(24, .67), (30, .49), (35, .31)])
def test_ls12_table_one_largest_remnant_predictions(speed, predicted_fraction):
    # LS12 Table 1, b=0, gamma=1: fitted Q*_RD=1.1e2 J/kg. Compare
    # its rounded PREDICTIONS, not measured remnants or the global material fit.
    q_r = speed**2 / 8
    assert largest_remnant_fraction(q_r / 110) == pytest.approx(predicted_fraction, abs=.01)


@pytest.mark.parametrize('ratio,fraction', [(0, 1), (.5, .75), (1, .5),
                                         (1.8, .1), (7.2, .0125)])
def test_remnant_curve_anchor_points(ratio, fraction):
    assert largest_remnant_fraction(ratio) == pytest.approx(fraction, rel=1e-12)


def test_supercatastrophic_transition_is_continuous_and_monotonic():
    ratios = [0, .1, .5, 1, 1.8 - 1e-10, 1.8, 1.8 + 1e-10, 2, 10, 100]
    fractions = [largest_remnant_fraction(q) for q in ratios]
    assert all(0 < f <= 1 for f in fractions)
    assert all(a > b for a, b in zip(fractions[:-1], fractions[1:], strict=True))
    assert fractions[4:7] == pytest.approx([.1, .1, .1], abs=1e-10)


@pytest.mark.parametrize('material,c_star', [('fluid_planets', 1.9), ('planetesimals', 5)])
def test_equal_mass_threshold_is_calibrated_binding_energy(material, c_star):
    # A combined sphere of radius 1000 km at the *reference* density.
    radius = 1e6
    total = (4 / 3) * math.pi * radius**3 * 1000
    binding_energy_per_kg = 3 * G_SI * total / (5 * radius)
    threshold = c_star * binding_energy_per_kg
    critical_speed = math.sqrt(8 * threshold)
    result = estimate_head_on_disruption(total / 2, total / 2, critical_speed, material=material)
    assert result.disruption_energy_j_kg == pytest.approx(threshold, rel=1e-12)
    assert result.specific_energy_j_kg == pytest.approx(threshold, rel=1e-12)
    assert result.largest_remnant_mass_kg == pytest.approx(total / 2, rel=1e-12)
    assert result.remaining_mass_kg == pytest.approx(total / 2, rel=1e-12)


def test_global_planetesimal_fit_matches_reference_threshold_within_calibration_scatter():
    # LS12 section 2: 4.2e15 kg per body; Table 1: Q*_RD ~110 J/kg.
    # c*=5 +/-2 alone gives 40% uncertainty; this is a fit check, not roundoff.
    result = estimate_head_on_disruption(4.2e15, 4.2e15, 30, material='planetesimals')
    assert result.disruption_energy_j_kg == pytest.approx(110, rel=.4)
    assert result.specific_energy_j_kg == 112.5


@pytest.mark.parametrize('material', ['fluid_planets', 'planetesimals'])
def test_mass_ratio_and_scale_laws_and_body_exchange(material):
    total = 1e22
    reference = estimate_head_on_disruption(total / 2, total / 2, 5000, material=material)
    unequal = estimate_head_on_disruption(.8 * total, .2 * total, 5000, material=material)
    swapped = estimate_head_on_disruption(.2 * total, .8 * total, 5000, material=material)
    assert unequal == swapped
    assert unequal.disruption_energy_j_kg > reference.disruption_energy_j_kg
    assert unequal.specific_energy_j_kg < reference.specific_energy_j_kg
    # At fixed density, 8x mass doubles radius: disruption energy grows 4x.
    # Doubling speed preserves the largest-remnant fraction at this new scale.
    scaled = estimate_head_on_disruption(6.4 * total, 1.6 * total, 10000, material=material)
    assert scaled.disruption_energy_j_kg == pytest.approx(4 * unequal.disruption_energy_j_kg, rel=1e-12)
    assert scaled.largest_remnant_mass_kg == pytest.approx(8 * unequal.largest_remnant_mass_kg, rel=1e-12)
    assert scaled.remaining_mass_kg == pytest.approx(8 * unequal.remaining_mass_kg, rel=1e-12)


def test_unequal_mass_scaling_has_published_exponent():
    # Choose gamma so (1+gamma)^2/(4gamma)=4. For mu_bar=.36,
    # the exponent is 23/27; keeping total mass fixed isolates equation 23.
    gamma = 7 - 4 * math.sqrt(3)
    equal = estimate_head_on_disruption(5e21, 5e21, 0, material='fluid_planets')
    target = 1e22 / (1 + gamma)
    unequal = estimate_head_on_disruption(target, target * gamma, 0, material='fluid_planets')
    assert unequal.disruption_energy_j_kg / equal.disruption_energy_j_kg == pytest.approx(4**(23 / 27), rel=1e-12)


@pytest.mark.parametrize('speed', [0, 1, 1e4, 5e4])
def test_mass_inventory_and_immutable_result(speed):
    result = estimate_head_on_disruption(8e23, 2e23, speed, material='fluid_planets')
    assert 0 < result.largest_remnant_mass_kg <= 1e24
    assert result.remaining_mass_kg >= 0
    assert result.largest_remnant_mass_kg + result.remaining_mass_kg == pytest.approx(1e24, rel=1e-15)
    with pytest.raises(FrozenInstanceError):
        result.remaining_mass_kg = 0


@pytest.mark.parametrize('ratio', [-1, math.inf, math.nan])
def test_invalid_energy_ratio_is_rejected(ratio):
    with pytest.raises(ValueError, match='Energy ratio'):
        largest_remnant_fraction(ratio)


@pytest.mark.parametrize('a,b,speed,material,message', [
    (0, 1, 1, 'fluid_planets', 'Masses'),
    (1, -1, 1, 'fluid_planets', 'Masses'),
    (math.inf, 1, 1, 'fluid_planets', 'Masses'),
    (1, math.nan, 1, 'fluid_planets', 'Masses'),
    (1, 1, -1, 'fluid_planets', 'Speed'),
    (1, 1, math.inf, 'fluid_planets', 'Speed'),
    (1, 1, math.nan, 'fluid_planets', 'Speed'),
    (1, 1, 1, 'gas_giant', 'calibration'),
])
def test_invalid_inputs_are_rejected(a, b, speed, material, message):
    with pytest.raises(ValueError, match=message):
        estimate_head_on_disruption(a, b, speed, material=material)
