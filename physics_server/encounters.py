"""Deterministic incoming contact states shared by live demos and references."""

import math

import numpy as np
import rebound

from disruption import estimate_head_on_disruption
import units as U

DEMO_CASES = ("merging", "hit_and_run", "disruption")


def incoming_states(masses, radii, velocity, lead):
    """Back-propagate a physical two-body contact without changing its energy."""
    fraction = masses[1] / sum(masses)
    back = rebound.Simulation()
    back.G = U.G
    back.integrator = "ias15"
    back.integrator.epsilon = 1e-12
    for mass, weight in zip(masses, (-fraction, 1 - fraction), strict=True):
        position = weight * sum(radii) * np.array([1, 0, 0])
        speed = -weight * np.asarray(velocity)
        back.add(m=mass, x=position[0], y=position[1], z=position[2], vx=speed[0], vy=speed[1], vz=speed[2])
    back.integrate(lead)
    return tuple((tuple(p.xyz), tuple(-v for v in p.vxyz)) for p in back.particles)


def demo_initial_conditions(case, masses, radii):
    if case not in DEMO_CASES:
        raise ValueError("Unknown collision encounter")
    angle = 0.9 if case == "hit_and_run" else 0.0
    if case == "disruption":
        threshold = estimate_head_on_disruption(
            *(m * U.MASS_KG for m in masses), 0, material="fluid_planets"
        ).disruption_energy_j_kg
        fraction = masses[1] / sum(masses)
        speed = math.sqrt(2 * 2.2 * threshold / (fraction * (1 - fraction))) / U.VELOCITY_M_S
    else:
        speed = (1.5 if case == "hit_and_run" else 1.05) * math.sqrt(2 * U.G * sum(masses) / sum(radii))
    velocity = speed * np.array([-math.sqrt(1 - angle * angle), 0, angle])
    states = incoming_states(masses, radii, velocity, 0.015)
    extent = max(math.hypot(*position) + radius for (position, _), radius in zip(states, radii, strict=True))
    camera = dict(focus=[0, 0, 0], distance=max(8 * sum(radii), 3 * extent), pitch=0.35, display_scale=0.0)
    return states, camera, dict(case=case, speed_m_s=speed * U.VELOCITY_M_S, angle_deg=math.degrees(math.asin(angle)))
