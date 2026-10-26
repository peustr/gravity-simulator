"""Contact classification: references, boundaries, units and exclusions."""
from dataclasses import asdict, FrozenInstanceError, replace
import math

import pytest

from disruption import (_grazing_merging_ratio, _reverse_interacting_mass,
                        classify_contact, classify_non_grazing, estimate_head_on_disruption)
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


def rocky_contact(*, gamma=1, b=.7, speed_ratio=1.5, target=.5 * 5.9722e24):
    impact = contact(target=target, gamma=gamma, density=5514, b=b)
    return with_speed(impact, speed_ratio * impact.escape_speed)


def classify_rocky(impact):
    return classify_contact(impact, unit_system='si', material='fluid_planets', body_types=(0, 0))


@pytest.mark.parametrize('gamma,angle,critical', [(1, 30, 1.39), (1, 45, 1.19), (1, 60, 1.11),
                                               (.5, 45, 1.19), (.5, 60, 1.09)])
def test_genda_reported_transition_speeds(gamma, angle, critical):
    # Genda et al. section 4; allow 0.04 vesc fit error, distinct from their
    # +/-0.01 numerical transition sampling. All cases are geometrically grazing.
    impact = rocky_contact(gamma=gamma, b=math.sin(math.radians(angle)))
    result = classify_rocky(impact)
    assert result.merging_speed_m_s / impact.escape_speed == pytest.approx(critical, abs=.04)
    assert classify_rocky(with_speed(impact, (critical - .05) * impact.escape_speed)).regime == 'graze_and_merge'
    assert classify_rocky(with_speed(impact, (critical + .05) * impact.escape_speed)).regime == 'hit_and_run'


def test_genda_equation_16_mass_asymmetry_is_linear():
    # gamma=1/3 -> Gamma=1/2; b=3/4 -> Theta^(5/2)=1/32.
    # This distinguishes the original equation from later squared-Gamma variants.
    assert _grazing_merging_ratio(1 / 3, .75) == pytest.approx(1.15569375, rel=1e-12)


@pytest.mark.parametrize('speed_ratio,regime', [(1.3, 'graze_and_merge'), (1.5, 'hit_and_run')])
def test_genda_figure_two_equal_mass_reference_events(speed_ratio, regime):
    impact = rocky_contact(target=.1 * 5.9722e24, b=.5, speed_ratio=speed_ratio)
    outcome = classify_rocky(impact)
    assert outcome.regime == regime
    if regime == 'graze_and_merge':
        assert outcome.largest_remnant_mass_kg == impact.total_mass
        assert outcome.runner_mass_kg == outcome.remaining_mass_kg == 0
    else:
        assert outcome.largest_remnant_mass_kg == impact.mass_a
        assert 0 < outcome.runner_mass_kg <= impact.mass_b


@pytest.mark.parametrize('b,fraction', [(.5, 3 * math.sqrt(3) / 8),
                                      (.75, 3 * math.sqrt(7) / (8 * math.pi) * (math.pi / 3 - math.sqrt(3) / 4))])
def test_reverse_interaction_has_analytic_volume_and_density(b, fraction):
    # Unit equal spheres; circle segments and chords have closed-form volumes.
    assert _reverse_interacting_mass(7, 1, 1, b) == pytest.approx(7 * fraction, rel=1e-12)
    # Rescaling lengths with constant mass cannot change the participating mass.
    assert _reverse_interacting_mass(7, 20, 20, b) == pytest.approx(7 * fraction, rel=1e-12)


def test_runner_intact_and_eroded_mass_are_accounted_without_double_counting():
    intact = rocky_contact(b=.9, speed_ratio=1.5)
    outcome = classify_rocky(intact)
    assert outcome.regime == 'hit_and_run'
    assert outcome.runner_mass_kg == intact.mass_b
    assert outcome.remaining_mass_kg == 0
    eroded = rocky_contact(b=.7, speed_ratio=3)
    outcome = classify_rocky(eroded)
    assert outcome.regime == 'hit_and_run'
    assert 0 < outcome.runner_mass_kg < eroded.mass_b
    assert outcome.largest_remnant_mass_kg == eroded.mass_a
    assert outcome.remaining_mass_kg == eroded.mass_b - outcome.runner_mass_kg
    # Reverse impact: equal spheres, b=.7 gives l/r=.6. Independent numeric
    # quadrature of the circle segment checks the chord-volume construction.
    import numpy as np
    nodes, weights = np.polynomial.legendre.leggauss(128)
    y = .4 + .3 * (nodes + 1)
    area = .3 * float(weights @ (2 * np.sqrt(1 - y * y)))
    chord = 2 * math.sqrt(.6 - .6**2 / 4)
    participating_mass = eroded.mass_a * area * chord / (4 * math.pi / 3)
    reverse = estimate_head_on_disruption(eroded.mass_b, participating_mass, eroded.speed, material='fluid_planets')
    assert outcome.runner_mass_kg == pytest.approx(reverse.largest_remnant_mass_kg, rel=1e-6)


def test_grazing_merging_and_target_erosion_boundaries():
    impact = rocky_contact(gamma=.25, b=.7)
    base = classify_rocky(impact)
    for scale, regime in [(1 - 1e-8, 'graze_and_merge'), (1 + 1e-8, 'hit_and_run')]:
        assert classify_rocky(with_speed(impact, base.merging_speed_m_s * scale)).regime == regime
    # Q_R/Qprime=2Mp/Mtot is the onset of target erosion, even for grazing events.
    critical_q = base.disruption_energy_j_kg * 2 * impact.mass_b / impact.total_mass
    critical_v = math.sqrt(2 * critical_q * impact.total_mass / impact.reduced_mass)
    before = classify_rocky(with_speed(impact, critical_v * (1 - 1e-8)))
    after = classify_rocky(with_speed(impact, critical_v * (1 + 1e-8)))
    assert before.regime == 'hit_and_run' and before.runner_mass_kg > 0
    assert after.regime == 'erosion' and after.runner_mass_kg == 0
    assert after.largest_remnant_mass_kg < impact.mass_a
    assert after.largest_remnant_mass_kg == pytest.approx(before.largest_remnant_mass_kg, rel=1e-7)


def test_grazing_results_invariant_under_body_exchange_and_scene_conversion():
    impact = rocky_contact(gamma=.25, b=.8, speed_ratio=2)
    original = classify_rocky(impact)
    exchanged = replace(impact, mass_a=impact.mass_b, mass_b=impact.mass_a,
                        radius_a=impact.radius_b, radius_b=impact.radius_a,
                        relative_position=tuple(-x for x in impact.relative_position),
                        relative_velocity=tuple(-v for v in impact.relative_velocity))
    assert classify_rocky(exchanged) == original
    scene = Impact(impact.mass_a / units.MASS_KG, impact.mass_b / units.MASS_KG,
                   impact.radius_a / units.LENGTH_M, impact.radius_b / units.LENGTH_M,
                   tuple(x / units.LENGTH_M for x in impact.relative_position),
                   tuple(v / units.VELOCITY_M_S for v in impact.relative_velocity), units.G)
    result = classify_contact(scene, unit_system=units.SYSTEM, material='fluid_planets', body_types=(0, 0))
    assert asdict(result) == pytest.approx(asdict(original), rel=1e-12)
    with pytest.raises(FrozenInstanceError):
        result.runner_mass_kg = 0


def test_general_entry_point_matches_restricted_classifier_for_non_grazing():
    impact = contact(b=.35)
    assert classify_contact(impact, unit_system='si', material='planetesimals', body_types=(0, 5)) == classify(impact)


@pytest.mark.parametrize('gamma', [1 / 9, .25, 1])
def test_supported_grazing_grid_has_finite_nonnegative_complete_mass_inventory(gamma):
    for b in (1 / (1 + gamma**(1 / 3)), .8, math.sin(math.radians(75))):
        for speed_ratio in (.5, 1.2, 2, 4, 7):
            impact = rocky_contact(gamma=gamma, b=b, speed_ratio=speed_ratio)
            result = classify_rocky(impact)
            masses = [result.largest_remnant_mass_kg, result.runner_mass_kg, result.remaining_mass_kg]
            assert all(math.isfinite(m) and m >= 0 for m in masses)
            assert sum(masses) == pytest.approx(impact.total_mass, rel=1e-15)
            assert result.runner_mass_kg <= impact.mass_b


@pytest.mark.parametrize('changes,options,message', [
    ({'gamma': .1, 'b': .8}, {}, 'mass ratio or angle'),
    ({'b': math.sin(math.radians(75)) + 1e-8}, {}, 'mass ratio or angle'),
    ({'target': .1 * 5.9722e24, 'gamma': .5}, {}, 'total mass'),
    ({'target': 1.01 * 5.9722e24}, {}, 'total mass'),
    ({}, {'body_types': (0, 5)}, 'rocky protoplanets'),
])
def test_grazing_extrapolation_is_rejected(changes, options, message):
    settings = dict(unit_system='si', material='fluid_planets', body_types=(0, 0))
    settings.update(options)
    with pytest.raises(ValueError, match=message):
        classify_contact(rocky_contact(**changes), **settings)


def test_grazing_planetesimals_remain_explicitly_unsupported():
    with pytest.raises(ValueError, match='rocky protoplanets'):
        classify_contact(contact(b=.8), unit_system='si', material='planetesimals', body_types=(5, 5))
