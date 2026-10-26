"""Non-grazing classification: references, boundaries, units and exclusions."""
from dataclasses import asdict, replace
import math

import pytest

from disruption import classify_non_grazing, estimate_head_on_disruption
from impacts import Impact
import units


def contact(*, target=4.2e15, gamma=.25, density=1000, b=0, speed=40):
    projectile = target * gamma
    rt = (target / ((4 / 3) * math.pi * density))**(1 / 3)
    rp = rt * gamma**(1 / 3)
    return Impact(target, projectile, rt, rp, (rt + rp, 0, 0),
                  (-speed * math.sqrt(1 - b * b), speed * b, 0), units.G_SI)


def classify(impact, material='planetesimals', **kwargs):
    return classify_non_grazing(impact, material=material, unit_system='si', body_types=(5, 0), **kwargs)


def with_speed(impact, speed):
    return replace(impact, relative_velocity=tuple(v * speed / impact.speed for v in impact.relative_velocity))


@pytest.mark.parametrize('material,target', [('planetesimals', 4.2e15), ('fluid_planets', 5.9722e24)])
@pytest.mark.parametrize('ratio,regime', [(.3, 'partial_accretion'), (.7, 'erosion'),
                                        (1.2, 'disruption'), (2, 'supercatastrophic_disruption')])
def test_head_on_regimes_and_mass_budget(material, target, ratio, regime):
    impact = contact(target=target)
    threshold = estimate_head_on_disruption(impact.mass_a, impact.mass_b, 0,
                                           material=material).disruption_energy_j_kg
    speed = math.sqrt(2 * ratio * threshold * impact.total_mass / impact.reduced_mass)
    result = classify(with_speed(impact, speed), material)
    assert result.regime == regime
    assert result.interacting_fraction == 1
    assert result.largest_remnant_mass_kg + result.remaining_mass_kg == pytest.approx(impact.total_mass, rel=1e-15)
    assert 0 < result.largest_remnant_mass_kg < impact.total_mass
    if regime == 'partial_accretion':
        assert result.largest_remnant_mass_kg > impact.mass_a
    else:
        assert result.largest_remnant_mass_kg < impact.mass_a


@pytest.mark.parametrize('boundary,below,above', [(.4, 'partial_accretion', 'erosion'),
                                              (1, 'erosion', 'disruption'),
                                              (1.8, 'disruption', 'supercatastrophic_disruption')])
def test_energy_boundaries_preserve_continuous_remnant_mass(boundary, below, above):
    impact = contact()
    threshold = estimate_head_on_disruption(impact.mass_a, impact.mass_b, 0,
                                           material='planetesimals').disruption_energy_j_kg
    outcomes = []
    for ratio in (boundary * (1 - 1e-8), boundary * (1 + 1e-8)):
        speed = math.sqrt(2 * ratio * threshold * impact.total_mass / impact.reduced_mass)
        outcomes.append(classify(with_speed(impact, speed)))
    assert [o.regime for o in outcomes] == [below, above]
    assert outcomes[0].largest_remnant_mass_kg == pytest.approx(outcomes[1].largest_remnant_mass_kg, rel=1e-6)


def test_merging_uses_interacting_combined_radius_and_strict_speed_boundary():
    impact = contact(gamma=1, b=.25)
    result = classify(impact)
    # l/r=1.5, cap fraction=27/32; equation 53 uses R'=(R^3+alpha*r^3)^(1/3).
    assert result.interacting_fraction == 27 / 32
    mass = impact.mass_a * (1 + 27 / 32)
    radius = impact.radius_a * (1 + 27 / 32)**(1 / 3)
    expected = math.sqrt(2 * units.G_SI * mass / radius)
    assert result.merging_speed_m_s == pytest.approx(expected, rel=1e-12)
    below = classify(with_speed(impact, expected * (1 - 1e-8)))
    above = classify(with_speed(impact, expected * (1 + 1e-8)))
    assert below.regime == 'merging' and below.remaining_mass_kg == 0
    assert above.regime == 'partial_accretion' and above.remaining_mass_kg > 0


@pytest.mark.parametrize('gamma,b,alpha', [(1, .35, .72), (.25, .35, .93)])
def test_interacting_mass_matches_ls12_table_one(gamma, b, alpha):
    result = classify(contact(gamma=gamma, b=b))
    assert result.interacting_fraction == pytest.approx(alpha, abs=.005)


@pytest.mark.parametrize('material,target,exponent', [('planetesimals', 4.2e15, 1.445),
                                                    ('fluid_planets', 5.9722e24, 1.46)])
def test_oblique_threshold_correction_keeps_full_pair_energy(material, target, exponent):
    head_on = classify(contact(target=target, gamma=1), material)
    oblique = classify(contact(target=target, gamma=1, b=.25), material)
    # alpha=27/32; for equal masses mu/mu_alpha=(1+alpha)/(2*alpha)=59/54.
    assert oblique.disruption_energy_j_kg / head_on.disruption_energy_j_kg == pytest.approx((59 / 54)**exponent, rel=1e-12)
    assert oblique.specific_energy_j_kg == pytest.approx(head_on.specific_energy_j_kg, rel=1e-12)


def test_scene_conversion_body_exchange_rotation_and_shallow_overlap():
    impact = contact(b=.35)
    expected = classify(impact)
    scene = Impact(impact.mass_a / units.MASS_KG, impact.mass_b / units.MASS_KG,
                   impact.radius_a / units.LENGTH_M, impact.radius_b / units.LENGTH_M,
                   tuple(x / units.LENGTH_M for x in impact.relative_position),
                   tuple(v / units.VELOCITY_M_S for v in impact.relative_velocity), units.G)
    result = classify_non_grazing(scene, unit_system=units.SYSTEM, material='planetesimals', body_types=(5, 0))
    exchanged = replace(impact, mass_a=impact.mass_b, mass_b=impact.mass_a,
                        radius_a=impact.radius_b, radius_b=impact.radius_a,
                        relative_position=tuple(-x for x in impact.relative_position),
                        relative_velocity=tuple(-v for v in impact.relative_velocity))
    rotated = replace(impact, relative_position=(0, impact.relative_position[0], 0),
                      relative_velocity=(-impact.relative_velocity[1], impact.relative_velocity[0], 0))
    shallow = replace(impact, relative_position=tuple(x * .99995 for x in impact.relative_position))
    for outcome in (result, classify(exchanged), classify(rotated), classify(shallow)):
        assert asdict(outcome) == pytest.approx(asdict(expected), rel=1e-12)


def test_grazing_boundary_is_excluded_even_for_slow_encounters():
    impact = contact(gamma=1, b=.5 - 1e-8, speed=1)
    assert classify(impact).regime == 'merging'
    for b in (.5, .5 + 1e-8, .9):
        with pytest.raises(ValueError, match='Grazing'):
            classify(contact(gamma=1, b=b, speed=1))


@pytest.mark.parametrize('material,target,gamma', [('fluid_planets', .1 * 5.9722e24, .1),
                                                 ('fluid_planets', 10 * 5.9722e24, 1),
                                                 ('planetesimals', (4 / 3) * math.pi * 1000**3 * 1000, .025),
                                                 ('planetesimals', (4 / 3) * math.pi * 100000**3 * 1000, 1)])
def test_size_and_mass_ratio_endpoints(material, target, gamma):
    assert classify(contact(target=target, gamma=gamma, speed=.01), material).regime == 'merging'


@pytest.mark.parametrize('changes,message', [
    ({'mass_a': math.inf}, 'finite'), ({'relative_velocity': (math.nan, 0, 0)}, 'finite'),
    ({'mass_b': 0}, 'positive'), ({'radius_b': -1}, 'positive'),
    ({'gravity': 2 * units.G_SI}, 'gravity'),
    ({'mass_b': 1}, 'mass ratio'), ({'radius_a': 999}, 'size'),
    ({'radius_a': 100001}, 'size'),
    ({'radius_b': 1e-200}, 'density'), ({'radius_b': 1e200}, 'density'),
    ({'radius_b': 7000}, 'density'),  # outside permitted density range
    ({'radius_b': 5000}, 'equal bulk densities'),
    ({'relative_position': (0, 0, 0)}, 'surfaces'),
    ({'relative_position': (1e8, 0, 0)}, 'surfaces'),
    ({'relative_position': (1, 2)}, 'three components'),
    ({'relative_velocity': (1, 2)}, 'three components'),
    ({'relative_velocity': (0, 0, 0)}, 'speed'),
    ({'relative_velocity': (-5001, 0, 0)}, 'speed'),
    ({'relative_velocity': (40, 0, 0)}, 'approaching'),
    ({'relative_velocity': (0, 40, 0)}, 'approaching'),
])
def test_unsupported_contact_values_are_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        classify(replace(contact(), **changes))


@pytest.mark.parametrize('kwargs,message', [
    ({'material': 'gas'}, 'calibration'),
    ({'unit_system': units.LEGACY}, 'unit system'),
    ({'unit_system': 'unknown'}, 'unit system'),
    ({'body_types': (0, 2)}, 'solid body types'),
    ({'body_types': (0,)}, 'solid body types'),
    ({'material': 'fluid_planets'}, 'size'),
])
def test_model_selection_and_non_solid_types_are_rejected(kwargs, message):
    options = dict(material='planetesimals', unit_system='si', body_types=(0, 5))
    options.update(kwargs)
    with pytest.raises(ValueError, match=message):
        classify_non_grazing(contact(), **options)
