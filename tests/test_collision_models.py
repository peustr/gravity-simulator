"""Classification-to-state conservation, contact correction and escape references."""
from dataclasses import FrozenInstanceError, replace
import math

import numpy as np
import pytest
import rebound

from collision_models import construct_collision, remnant_escape_check, surface_contact
from collision_outcomes import RemnantSpec, SphereState, collision_budget
from disruption import classify_contact, estimate_head_on_disruption
from impacts import Impact
from units import G_SI


def encounter(*, target=4.2e15, gamma=.25, density=1000, b=0, speed=40):
    radius = (target / ((4 / 3) * math.pi * density))**(1 / 3)
    small_radius = radius * gamma**(1 / 3)
    return (SphereState(target, radius, (0, 0, 0), (0, 0, 0)),
            SphereState(target * gamma, small_radius, (radius + small_radius, 0, 0),
                        (-speed * math.sqrt(1 - b * b), speed * b, 0)))


def classify(pair, material):
    a, b = pair
    impact = Impact(a.mass_kg, b.mass_kg, a.radius_m, b.radius_m,
                    tuple(np.subtract(b.position_m, a.position_m)),
                    tuple(np.subtract(b.velocity_m_s, a.velocity_m_s)), G_SI)
    return classify_contact(impact, material=material, body_types=(0, 0), unit_system='si')


def layout_for(pair, classification):
    masses = [classification.largest_remnant_mass_kg]
    if classification.runner_mass_kg:
        masses.append(classification.runner_mass_kg)
    if classification.remaining_mass_kg:
        count = math.ceil(classification.remaining_mass_kg / masses[0])
        masses.extend([classification.remaining_mass_kg / count] * count)
    a, b = pair
    radius = (a.radius_m**3 + b.radius_m**3)**(1 / 3)
    total = a.mass_kg + b.mass_kg
    # Prescribed ring with ample spacing; no empirical ejecta claim.
    extent = 4 * len(masses) * radius
    return tuple(RemnantSpec(m, radius * (m / total)**(1 / 3),
                             (extent * math.cos(2 * math.pi * i / len(masses)),
                              extent * math.sin(2 * math.pi * i / len(masses)), 0))
                 for i, m in enumerate(masses))


def assert_closed(before, after):
    a, b = before
    fraction = b.mass_kg / (a.mass_kg + b.mass_kg)
    origin = np.array(a.position_m) + fraction * np.subtract(b.position_m, a.position_m)
    velocity = np.array(a.velocity_m_s) + fraction * np.subtract(b.velocity_m_s, a.velocity_m_s)
    initial = collision_budget(before, origin_m=origin, frame_velocity_m_s=velocity)
    final = collision_budget(after, origin_m=origin, frame_velocity_m_s=velocity)
    states = (*before, *after)
    momentum_scale = sum(s.mass_kg * math.dist(s.velocity_m_s, velocity) for s in states)
    angular_scale = sum(s.mass_kg * math.dist(s.position_m, origin) * math.dist(s.velocity_m_s, velocity)
                        + math.hypot(*s.spin_kg_m2_s) for s in states)
    energy_scale = sum(abs(getattr(budget, component)) for budget in (initial, final)
                       for component in ('translational_energy_j', 'rotational_energy_j', 'self_binding_j',
                                         'mutual_potential_j', 'internal_energy_j'))
    assert final.mass_kg == pytest.approx(initial.mass_kg, rel=1e-12)
    np.testing.assert_allclose(final.momentum_kg_m_s, initial.momentum_kg_m_s, rtol=0, atol=1e-12 * momentum_scale)
    np.testing.assert_allclose(final.angular_momentum_kg_m2_s, initial.angular_momentum_kg_m2_s,
                               rtol=0, atol=1e-12 * angular_scale)
    assert abs(final.energy_j - initial.energy_j) < 1e-12 * energy_scale


@pytest.mark.parametrize('material,target', [('planetesimals', 4.2e15), ('fluid_planets', 5.9722e24)])
@pytest.mark.parametrize('ratio,regime,fraction', [(.3, 'partial_accretion', .85), (.7, 'erosion', .65),
                                                (1.2, 'disruption', .4), (2, 'supercatastrophic_disruption',
                                                                        .1 * (2 / 1.8)**-1.5)])
def test_classified_non_grazing_reference_outcomes_close_budgets(material, target, ratio, regime, fraction):
    threshold = estimate_head_on_disruption(target, target / 4, 0, material=material).disruption_energy_j_kg
    speed = math.sqrt(2 * ratio * threshold / .16)
    pair = encounter(target=target, speed=speed)
    classified = classify(pair, material)
    result = construct_collision(*pair, material=material, body_types=(0, 0),
                                 layout=layout_for(pair, classified), expansion_fraction=.5)
    assert result.classification.regime == regime
    assert result.remnants[0].mass_kg == pytest.approx(fraction * target * 1.25, rel=1e-12)
    assert result.escape_certificate in ('two_body_hyperbolic', 'all_pairs_escape_bound')
    assert_closed(pair, result.remnants)


def rocky_pair(b, speed_ratio):
    mass = .5 * 5.9722e24
    radius = (mass / ((4 / 3) * math.pi * 5514))**(1 / 3)
    return encounter(target=mass, gamma=1, density=5514, b=b,
                     speed=speed_ratio * math.sqrt(2 * G_SI * mass / radius))


@pytest.mark.parametrize('grazing', [False, True])
def test_merger_routes_and_immutable_results(grazing):
    pair = rocky_pair(.6 if grazing else 0, 1 if grazing else .5)
    result = construct_collision(*pair, material='fluid_planets', body_types=(0, 0))
    assert result.classification.regime == ('graze_and_merge' if grazing else 'merging')
    assert len(result.remnants) == 1
    assert result.escape_certificate is None
    assert_closed(pair, result.remnants)
    with pytest.raises(FrozenInstanceError):
        result.escape_certificate = 'other'


@pytest.mark.parametrize('b,speed_ratio,certificate', [(.9, 1.5, 'two_body_hyperbolic'),
                                                     (.7, 3, 'all_pairs_escape_bound')])
def test_escape_certificate_and_forward_gravitational_reference(b, speed_ratio, certificate):
    pair = rocky_pair(b, speed_ratio)
    classified = classify(pair, 'fluid_planets')
    result = construct_collision(*pair, material='fluid_planets', body_types=(0, 0),
                                 layout=layout_for(pair, classified), expansion_fraction=1)
    assert result.classification.regime == 'hit_and_run'
    assert result.escape_certificate == certificate
    assert result.remnants[1].mass_kg == classified.runner_mass_kg
    assert_closed(pair, result.remnants)
    # Independent isolated N-body evolution, nondimensionalised for conditioning.
    states = result.remnants
    length = min(math.dist(a.position_m, b.position_m) for i, a in enumerate(states) for b in states[i + 1:])
    total = sum(s.mass_kg for s in states)
    speed_unit = math.sqrt(G_SI * total / length)
    sim = rebound.Simulation()
    sim.G = 1
    sim.integrator = 'ias15'
    for s in states:
        x, y, z = np.array(s.position_m) / length
        vx, vy, vz = np.array(s.velocity_m_s) / speed_unit
        sim.add(m=s.mass_kg / total, x=x, y=y, z=z, vx=vx, vy=vy, vz=vz)
    energy = sim.energy()
    distances = [math.dist(a.xyz, b.xyz) for i, a in enumerate(sim.particles) for b in sim.particles[i + 1:]]
    sim.integrate(20)
    assert sim.energy() == pytest.approx(energy, rel=1e-10)
    later = [math.dist(a.xyz, b.xyz) for i, a in enumerate(sim.particles) for b in sim.particles[i + 1:]]
    assert all(end > 2 * start for start, end in zip(distances, later, strict=True))


@pytest.mark.parametrize('offset', [-5e-5, 0, 5e-5])
def test_surface_projection_preserves_point_mass_energy_momentum_and_angular_momentum(offset):
    pair = encounter(b=.35, speed=4)
    a, b = pair
    b = replace(b, position_m=tuple(x * (1 + offset) for x in b.position_m))
    corrected = surface_contact(a, b)
    assert math.dist(*(s.position_m for s in corrected)) == pytest.approx(a.radius_m + b.radius_m, rel=1e-12)
    # Use the explicitly defined point-mass potential for an overlapping sample.
    def inventory(states):
        first, second = states
        relative_v = np.subtract(second.velocity_m_s, first.velocity_m_s)
        relative_r = np.subtract(second.position_m, first.position_m)
        total = first.mass_kg + second.mass_kg
        reduced = first.mass_kg * (second.mass_kg / total)
        energy = .5 * reduced * (relative_v @ relative_v) - G_SI * first.mass_kg * second.mass_kg / np.linalg.norm(relative_r)
        angular = reduced * np.cross(relative_r, relative_v)
        momentum = sum((s.mass_kg * np.array(s.velocity_m_s) for s in states), np.zeros(3))
        centre = sum((s.mass_kg / total * np.array(s.position_m) for s in states), np.zeros(3))
        return energy, angular, momentum, centre
    for initial, final in zip(inventory((a, b)), inventory(corrected), strict=True):
        np.testing.assert_allclose(final, initial, rtol=1e-12, atol=0)
    if offset == 0:
        assert corrected == pair
    result = construct_collision(a, b, material='planetesimals', body_types=(0, 0))
    assert result.contact == corrected
    assert_closed(corrected, result.remnants)


def test_projection_exchange_rotation_translation_and_boost():
    a, b = rocky_pair(.6, 1)
    b = replace(b, position_m=tuple(.99995 * x for x in b.position_m))
    result = construct_collision(a, b, material='fluid_planets', body_types=(0, 0))
    rotation = np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]])
    origin, boost = np.array([1e9, -1e8, 1e7]), np.array([1e4, -2e4, 3e4])
    moved = tuple(replace(s, position_m=rotation @ s.position_m + origin,
                          velocity_m_s=rotation @ s.velocity_m_s + boost) for s in (b, a))
    actual = construct_collision(*moved, material='fluid_planets', body_types=(0, 0))
    assert actual.classification.regime == result.classification.regime
    assert_closed(actual.contact, actual.remnants)
    np.testing.assert_allclose(np.subtract(actual.remnants[0].position_m, origin),
                               rotation @ result.remnants[0].position_m, rtol=1e-12)
    np.testing.assert_allclose(np.subtract(actual.remnants[0].velocity_m_s, boost),
                               rotation @ result.remnants[0].velocity_m_s, rtol=1e-12)
    assert actual.remnants[0].internal_energy_j == pytest.approx(result.remnants[0].internal_energy_j, rel=1e-12)


def test_invalid_contact_and_calibration_inputs():
    a, b = encounter(speed=4)
    with pytest.raises(ValueError, match='shallow'):
        surface_contact(a, replace(b, position_m=(.5 * b.position_m[0], 0, 0)))
    with pytest.raises(ValueError, match='approaching bodies'):
        surface_contact(a, replace(b, velocity_m_s=(1, 0, 0)))
    with pytest.raises(ValueError, match='No approaching surface'):
        surface_contact(a, replace(b, position_m=(.99995 * b.position_m[0], 0, 0), velocity_m_s=(-.001, 0, 0)))
    with pytest.raises(ValueError, match='nonrotating'):
        construct_collision(replace(a, spin_kg_m2_s=(1, 0, 0)), b, material='planetesimals', body_types=(0, 0))
    with pytest.raises(ValueError, match='solid body types'):
        construct_collision(a, b, material='planetesimals', body_types=(0, 2))
    with pytest.raises(ValueError, match='does not accept'):
        construct_collision(a, b, material='planetesimals', body_types=(0, 0), expansion_fraction=1)
    with pytest.raises(ValueError, match='spin limit'):
        construct_collision(*rocky_pair(.9, 1), material='fluid_planets', body_types=(0, 0))


def test_classified_mass_order_density_and_debris_constraints():
    pair = rocky_pair(.7, 3)
    classified = classify(pair, 'fluid_planets')
    layout = layout_for(pair, classified)
    options = dict(material='fluid_planets', body_types=(0, 0))
    with pytest.raises(ValueError, match='require a layout'):
        construct_collision(*pair, **options)
    for bad in ((), layout[:1], tuple(reversed(layout))):
        with pytest.raises(ValueError, match='in order'):
            construct_collision(*pair, **options, layout=bad, expansion_fraction=1)
    with pytest.raises(ValueError, match='remaining mass'):
        construct_collision(*pair, **options, layout=layout[:2], expansion_fraction=1)
    bad_radius = (replace(layout[0], radius_m=layout[0].radius_m * 1.01), *layout[1:])
    with pytest.raises(ValueError, match='mean density'):
        construct_collision(*pair, **options, layout=bad_radius, expansion_fraction=1)
    with pytest.raises(ValueError, match='receding|escape is not established'):
        construct_collision(*pair, **options, layout=layout, expansion_fraction=0)
    with pytest.raises(ValueError, match='escape is not established'):
        construct_collision(*pair, **options, layout=layout, expansion_fraction=.001)
    # Supercatastrophic debris cannot be packaged as a second, larger remnant.
    pair = encounter(speed=200)
    classified = classify(pair, 'planetesimals')
    layout = (RemnantSpec(classified.largest_remnant_mass_kg, 1, (0, 0, 0)),
              RemnantSpec(classified.remaining_mass_kg, 1, (1, 0, 0)))
    with pytest.raises(ValueError, match='cannot exceed'):
        construct_collision(*pair, material='planetesimals', body_types=(0, 0), layout=layout, expansion_fraction=1)


def test_escape_certificate_rejects_bound_marginal_overlapping_and_inward_states():
    a = SphereState(1e20, 2e5, (0, 0, 0), (0, 0, 0))
    escape = math.sqrt(2 * G_SI * 2e20 / 1e6)
    b = SphereState(1e20, 2e5, (1e6, 0, 0), (escape, 0, 0))
    with pytest.raises(ValueError, match='at least two'):
        remnant_escape_check((a,))
    with pytest.raises(ValueError, match='non-overlapping'):
        remnant_escape_check((a, replace(b, position_m=(1, 0, 0))))
    with pytest.raises(ValueError, match='receding'):
        remnant_escape_check((a, replace(b, velocity_m_s=(-escape, 0, 0))))
    for speed in (.5 * escape, escape, escape * (1 + 1e-14)):
        with pytest.raises(ValueError, match='not established'):
            remnant_escape_check((a, replace(b, velocity_m_s=(speed, 0, 0))))
    assert remnant_escape_check((a, replace(b, velocity_m_s=(2 * escape, 0, 0)))) == 'two_body_hyperbolic'


def test_weighted_escape_bound_has_analytic_margin_and_independent_gravity_check():
    mass, side = 1e20, 1e6
    points = np.array([[-.5, -math.sqrt(3)/6, 0], [.5, -math.sqrt(3)/6, 0], [0, math.sqrt(3)/3, 0]])
    # Equilateral triangle: B_i=4Gm/(d*u), hence u^2 > 16Gm/d.
    critical = math.sqrt(16 * G_SI * mass / side)
    def triangle(speed):
        return tuple(SphereState(mass, 1e4, side*p, speed*p) for p in points)
    for speed in (critical * .9, critical, critical * (1 + 1e-14)):
        with pytest.raises(ValueError, match='escape is not established'):
            remnant_escape_check(triangle(speed))
    states = triangle(1.01 * critical)
    assert remnant_escape_check(states) == 'all_pairs_escape_bound'
    # This valid state fails the former 8GM/d_min bound (24Gm/d here).
    assert (1.01 * critical)**2 < 24 * G_SI * mass / side
    sim = rebound.Simulation()
    sim.G = 1
    sim.integrator = 'ias15'
    speed_unit = math.sqrt(G_SI * 3*mass / side)
    for s in states:
        x,y,z = np.array(s.position_m)/side
        vx,vy,vz = np.array(s.velocity_m_s)/speed_unit
        sim.add(m=1/3,x=x,y=y,z=z,vx=vx,vy=vy,vz=vz)
    sim.integrate(20)
    assert min(math.dist(a.xyz,b.xyz) for i,a in enumerate(sim.particles) for b in sim.particles[i+1:]) > 20


def test_weighted_escape_rejects_overflow_in_gravity_impulse():
    states = tuple(SphereState(1e20, 1e4, (i*1e6,0,0), (i*1e-310,0,0)) for i in range(3))
    with pytest.raises(ValueError, match='numerical range'):
        remnant_escape_check(states)


def test_resolved_policy_preserves_classification_and_rejects_conflicting_or_excessive_allocations():
    pair = rocky_pair(.7, 3)
    with pytest.raises(ValueError, match='cannot be combined'):
        construct_collision(*pair, material='fluid_planets', body_types=(0,0), resolved_policy=True,
                            expansion_fraction=.5)
    pair = rocky_pair(0, 8)
    with pytest.raises(ValueError, match='more than 32'):
        construct_collision(*pair, material='fluid_planets', body_types=(0,0), resolved_policy=True)
    pair = rocky_pair(.9, 1.5)
    outcome = construct_collision(*pair, material='fluid_planets', body_types=(0,0), resolved_policy=True)
    assert outcome.classification.regime == 'hit_and_run' and len(outcome.remnants) == 2
    assert_closed(pair, outcome.remnants)


def test_fragmentation_cannot_accept_immediately_reaccreting_debris():
    pair = encounter(speed=200)
    classified = classify(pair, 'planetesimals')
    with pytest.raises(ValueError, match='receding'):
        construct_collision(*pair, material='planetesimals', body_types=(0, 0),
                            layout=layout_for(pair, classified), expansion_fraction=0)


@pytest.mark.parametrize('position,velocity', [((1e6, 0, 0), (1e155, 0, 0)),
                                              ((1.1e308, 1.1e308, 1.1e308), (0, 0, 0))])
def test_escape_cannot_certify_nonfinite_arithmetic(position, velocity):
    a = SphereState(1e20, 2e5, (0, 0, 0), (0, 0, 0))
    b = SphereState(1e20, 2e5, position, velocity)
    with pytest.raises(ValueError, match='numerical range'):
        remnant_escape_check((a, b))
