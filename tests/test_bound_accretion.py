"""Conditional rotating sticking, with explicit domain and conserved budgets."""
from dataclasses import replace
import math

import numpy as np
import pytest

import experiments as E
import units as U
import world as W
from body_state import capture_sphere
from collision_models import construct_collision
from collision_outcomes import collision_budget
from test_collision_models import assert_closed, rocky_pair, encounter
from test_live_collisions import pair, callback


def spinning_pair(speed=.5, b=0):
    a, c = rocky_pair(b, speed)
    angular = .05 * a.inertia_kg_m2 * math.sqrt(U.G_SI*a.mass_kg/a.radius_m**3)
    return replace(a, spin_kg_m2_s=(0, 0, angular)), c


def test_bound_rotating_sticking_is_a_distinct_conserving_prescription():
    incoming = spinning_pair()
    result = construct_collision(*incoming, material='fluid_planets', body_types=(0, 0), allow_gentle_contacts=True)
    assert result.classification.regime == 'bound_sticking'
    assert result.classification.disruption_energy_j_kg is None
    assert result.classification.merging_speed_m_s is None
    assert len(result.remnants) == 1 and result.remnants[0].spin_kg_m2_s != (0, 0, 0)
    assert_closed(incoming, result.remnants)


@pytest.mark.parametrize('changes', [dict(), dict(material='planetesimals'), dict(layout=[]), dict(expansion_fraction=.5)])
def test_sticking_requires_explicit_policy_material_and_no_allocation(changes):
    args = dict(material='fluid_planets', body_types=(0, 0), allow_gentle_contacts=True)
    args.update(changes)
    if not changes:
        args['allow_gentle_contacts'] = False
    with pytest.raises(ValueError):
        construct_collision(*spinning_pair(), **args)


def test_gentle_unbound_merger_is_a_separate_sticking_prescription():
    incoming = spinning_pair(1.05)
    result = construct_collision(*incoming, material='fluid_planets', body_types=(0, 0), allow_gentle_contacts=True)
    assert result.classification.regime == 'gentle_sticking'
    assert result.classification.disruption_energy_j_kg is None
    assert_closed(incoming, result.remnants)


def test_rotating_fragmentation_is_not_relabelled_as_sticking():
    with pytest.raises(ValueError, match='gentle-contact'):
        construct_collision(*spinning_pair(3), material='fluid_planets', body_types=(0, 0), allow_gentle_contacts=True)


def test_small_body_calibration_and_asteroid_types_do_not_enable_rotating_sticking():
    a,b = encounter(target=4e18, gamma=.5, density=3000, b=0, speed=1)
    a = replace(a, spin_kg_m2_s=(0, 0, 1))
    with pytest.raises(ValueError, match='gentle-contact'):
        construct_collision(a,b, material='planetesimals', body_types=(5,5), allow_gentle_contacts=True)
    with pytest.raises(ValueError, match='gentle-contact'):
        construct_collision(*spinning_pair(), material='fluid_planets', body_types=(5,5), allow_gentle_contacts=True)


def test_bound_pair_cannot_exceed_the_spherical_remnant_spin_limit():
    a, b = rocky_pair(.89, .9)
    radius = (a.radius_m**3+b.radius_m**3)**(1/3)
    inertia = .4 * (a.mass_kg+b.mass_kg) * radius**2
    limit = inertia*math.sqrt(U.G_SI*(a.mass_kg+b.mass_kg)/radius**3)
    a = replace(a, spin_kg_m2_s=(0, 0, .15*limit))
    from collision_outcomes import merge_spheres
    with pytest.raises(ValueError, match='spin limit'):
        merge_spheres(a, b)
    result = construct_collision(a, b, material='fluid_planets', body_types=(0, 0), allow_gentle_contacts=True)
    assert result.classification.regime == 'gentle_rebound' and len(result.remnants) == 2
    assert_closed((a,b), result.remnants)


def test_automatic_second_accretion_retains_spin_heat_and_restart_metadata():
    w = pair(b=.1, speed_ratio=.5, gap=1, capacity=3)
    w.configure(dict(collisions='auto'))
    callback(w)
    w._process_collisions()
    remnant = w.sim.particles[0]
    spin = w.meta[remnant.name]['inventory'].spin_kg_m2_s
    assert math.hypot(*spin) > 0
    mass = .5*5.9722e24/U.MASS_KG
    radius = w.radius_for(W.ROCKY, mass)
    speed = .5*math.sqrt(2*(remnant.m+mass)/(remnant.r+radius))
    w.add_body(W.ROCKY, mass, (remnant.x+remnant.r+radius, remnant.y, remnant.z), (-speed, 0, 0))
    incoming = tuple(capture_sphere(p, w.meta[p.name]['inventory'], w.units) for p in w.sim.particles)
    callback(w)
    w._process_collisions()
    assert not w.paused and w.sim.N == 1 and w.last_impact['regime'] == 'bound_sticking'
    final = capture_sphere(w.sim.particles[0], w.meta[w.sim.particles[0].name]['inventory'], w.units)
    assert_closed(incoming, (final,))
    np.testing.assert_allclose(collision_budget((final,)).angular_momentum_kg_m2_s,
                               collision_budget(incoming).angular_momentum_kg_m2_s, rtol=1e-12)
    restored, _ = E.restore(E.capture(w,E.DEFAULT_CAMERA))
    assert restored.last_impact == w.last_impact and restored.meta == w.meta


def test_stable_counterspin_grazing_contact_can_stick_without_a_rotating_mass_fit():
    a,b = rocky_pair(.8,1.02)
    limit = a.inertia_kg_m2*math.sqrt(U.G_SI*a.mass_kg/a.radius_m)/a.radius_m
    a = replace(a,spin_kg_m2_s=(0,0,-.8*limit))
    result = construct_collision(a,b,material='fluid_planets',body_types=(0,0),allow_gentle_contacts=True)
    assert len(result.remnants)==1 and result.classification.regime=='gentle_sticking'
    assert result.classification.disruption_energy_j_kg is None
    assert_closed((a,b),result.remnants)


def test_gentle_fallback_cannot_replace_calibrated_mass_losses():
    a,b = encounter(target=5.9722e24,gamma=1/9,density=5514,b=.96,speed=1)
    escape = math.sqrt(2*U.G_SI*(a.mass_kg+b.mass_kg)/(a.radius_m+b.radius_m))
    incoming = (a,replace(b,velocity_m_s=np.multiply(b.velocity_m_s,1.06*escape)))
    with pytest.raises(ValueError,match='Multiple remnants'):
        construct_collision(*incoming,material='fluid_planets',body_types=(0,0),allow_gentle_contacts=True)


def test_supercritical_input_spin_is_refused_intact():
    a,b = rocky_pair(0,.5)
    limit = a.inertia_kg_m2*math.sqrt(U.G_SI*a.mass_kg/a.radius_m)/a.radius_m
    a = replace(a,spin_kg_m2_s=(0,0,2*limit))
    with pytest.raises(ValueError,match='input-spin'):
        construct_collision(a,b,material='fluid_planets',body_types=(0,0),allow_gentle_contacts=True)


def test_uncalibrated_grazing_mass_ratio_uses_only_the_explicit_gentle_policy():
    incoming = encounter(target=5.9722e24,gamma=.105,density=5514,b=.7,speed=.9)
    with pytest.raises(ValueError,match='Grazing mass ratio'):
        construct_collision(*incoming,material='fluid_planets',body_types=(0,0))
    result = construct_collision(*incoming,material='fluid_planets',body_types=(0,0),allow_gentle_contacts=True)
    assert result.classification.regime=='bound_sticking' and len(result.remnants)==1
    assert_closed(incoming,result.remnants)
