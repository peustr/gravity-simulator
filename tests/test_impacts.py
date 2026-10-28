"""Analytic pair budgets, coordinate invariance and native callback capture."""
import ctypes
from dataclasses import FrozenInstanceError
import math
from types import SimpleNamespace

import numpy as np
import pytest

from impacts import capture
import world as W


def particles():
    return (SimpleNamespace(m=3, r=2, xyz=[0, 0, 0], vxyz=[1, 2, 0]),
            SimpleNamespace(m=1, r=1, xyz=[3, 0, 0], vxyz=[-3, 5, 0]))


def test_oblique_impact_has_analytic_geometry_and_pair_budgets():
    impact = capture(*particles(), gravity=1)
    assert impact.total_mass == 4
    assert impact.reduced_mass == .75
    assert impact.separation == impact.contact_distance == 3
    assert impact.speed == 5
    assert impact.normal == (1, 0, 0)
    assert impact.radial_speed == -4
    assert impact.impact_parameter == pytest.approx(.6, rel=1e-12)
    assert impact.kinetic_energy == 9.375
    assert impact.specific_energy == 2.34375
    assert impact.angular_momentum == (0, 0, 6.75)
    assert impact.escape_speed == pytest.approx(math.sqrt(8 / 3), rel=1e-12)


@pytest.mark.parametrize('velocity,parameter,radial', [((-5, 0, 0), 0, -5),
                                                    ((0, 5, 0), 1, 0),
                                                    ((5, 0, 0), 0, 5)])
def test_head_on_tangential_and_separating_geometry(velocity, parameter, radial):
    a, b = particles()
    a.vxyz, b.vxyz = [0, 0, 0], velocity
    impact = capture(a, b, 1)
    assert impact.impact_parameter == parameter
    assert impact.radial_speed == radial


def test_measurements_are_invariant_under_boost_translation_and_body_exchange():
    a, b = particles()
    original = capture(a, b, 1)
    for p in (a, b):
        p.xyz = np.asarray(p.xyz) + [20, -10, 7]
        p.vxyz = np.asarray(p.vxyz) + [3, 2, -8]
    for measured in (capture(a, b, 1), capture(b, a, 1)):
        for key in ('kinetic_energy', 'specific_energy', 'speed', 'separation',
                    'radial_speed', 'impact_parameter', 'escape_speed'):
            assert getattr(measured, key) == pytest.approx(getattr(original, key), rel=1e-12, abs=1e-12)
        np.testing.assert_allclose(measured.angular_momentum, original.angular_momentum, rtol=1e-12, atol=1e-12)
    assert capture(b, a, 1).normal == (-1, 0, 0)


def test_angular_momentum_rotates_with_the_coordinate_system():
    a, b = particles()
    rotation = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
    for p in (a, b):
        p.xyz = rotation @ p.xyz
        p.vxyz = rotation @ p.vxyz
    impact = capture(a, b, 1)
    assert impact.angular_momentum == (0, -6.75, 0)
    assert impact.specific_energy == 2.34375
    assert impact.impact_parameter == pytest.approx(.6, rel=1e-12)


def test_degenerate_measurements_are_explicit():
    a, b = particles()
    b.vxyz = a.vxyz.copy()
    stationary = capture(a, b, 1)
    assert stationary.impact_parameter is None
    assert stationary.radial_speed == stationary.kinetic_energy == 0
    assert stationary.angular_momentum == (0, 0, 0)
    b.xyz = a.xyz.copy()
    a.r = b.r = 0
    coincident = capture(a, b, 1)
    assert coincident.normal is None and coincident.radial_speed is None
    assert coincident.impact_parameter is None and coincident.escape_speed is None
    a.m = b.m = 0
    a.r = b.r = 1
    massless = capture(a, b, 1)
    assert massless.reduced_mass == massless.specific_energy == massless.escape_speed == 0


def test_capture_is_immutable_and_owns_its_values():
    a, b = particles()
    impact = capture(a, b, 1)
    a.m, b.r = 90, 80
    a.xyz[0], b.vxyz[0] = 100, 200
    assert impact.mass_a == 3 and impact.radius_b == 1
    assert impact.relative_position == (3, 0, 0) and impact.relative_velocity == (-4, 3, 0)
    with pytest.raises(FrozenInstanceError):
        impact.mass_a = 10


def test_callback_records_contact_before_merging_and_fragmenting():
    w = W.World(seed=42)
    w.sim.G = 2
    w.add_body(W.ROCKY, 3, (0, 0, 0), (1, 2, 0))
    w.add_body(W.ROCKY, 1, (3, 0, 0), (-3, 5, 0))
    w.sim.particles[0].r, w.sim.particles[1].r = 2, 1
    removed = w._resolve_collision(ctypes.pointer(w.sim), SimpleNamespace(p1=0, p2=1))
    assert removed == 2
    impact = w._pending[0]['impact']
    spheres = w._pending[0]['spheres']
    assert spheres[0].mass_kg == 3 * W.units.MASS_KG
    assert spheres[1].position_m == (3 * W.units.LENGTH_M, 0, 0)
    assert spheres[0].velocity_m_s == (W.units.VELOCITY_M_S, 2 * W.units.VELOCITY_M_S, 0)
    assert w.meta['1']['inventory'] is None
    assert w.sim.particles[0].m == 4 and w.sim.particles[0].x == .75
    assert impact.mass_a == 3 and impact.relative_position == (3, 0, 0)
    assert impact.kinetic_energy == 9.375 and impact.angular_momentum == (0, 0, 6.75)
    assert impact.escape_speed == pytest.approx(math.sqrt(16 / 3), rel=1e-12)
    w.sim.remove(1)
    w._process_collisions()
    assert not w._pending and w.sim.N > 2
    assert impact.mass_a == 3 and impact.relative_velocity == (-4, 3, 0)
    assert spheres[0].mass_kg == 3 * W.units.MASS_KG
    assert all(md['inventory'] is None for md in w.meta.values())
