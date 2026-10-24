"""Contact-aware step limits shared by the live solver and orbit forecasts."""
from functools import lru_cache
import math

import numpy as np


# Maximum near-contact travel scale as a fraction of the summed physical radii.
# This controls contact localisation, not the IAS15 gravitational error tolerance.
CONTACT_FRACTION = 1e-4


@lru_cache(maxsize=4)
def _pairs(count):
    return np.triu_indices(count, 1)


def contact_step_limit(sim, maximum, fraction=CONTACT_FRACTION):
    """Limit approach to finite surfaces before IAS15 evaluates a singular centre.

    The gap, radial approach speed and pair escape speed bound the proposed travel
    scale. Far pairs do not limit the step. Near contact, allow a small finite
    overlap so direct collision detection can resolve it without an asymptotic
    approach to the surface. Separating overlaps (new ejecta) remain free to leave.
    This is a numerical safeguard tested for resolved encounters, not a proof
    of contact detection for arbitrary many-body singularities.
    """
    if sim.N < 2:
        return maximum
    x, v = np.zeros(3 * sim.N), np.zeros(3 * sim.N)
    m, r = np.zeros(sim.N), np.zeros(sim.N)
    sim.serialize_particle_data(m=m, r=r, xyz=x, vxvyvz=v)
    i, j = _pairs(sim.N)
    dx = x.reshape(-1, 3)[j] - x.reshape(-1, 3)[i]
    dv = v.reshape(-1, 3)[j] - v.reshape(-1, 3)[i]
    distance = np.linalg.norm(dx, axis=1)
    radius = r[i] + r[j]
    radial = np.einsum('ij,ij->i', dx, dv) / np.maximum(distance, 1e-300)
    # Outside surfaces, gravity can turn an initially receding pair around
    # during a large trial step. Separating overlaps must remain free to leave.
    eligible = (distance > radius) | (radial <= 0)
    # A mass-bearing tracer exerts no force, including on another tracer.
    if sim.N_active < sim.N:
        m[sim.N_active:] = 0
    # Tangential velocity alone cannot close a gap. Including it would impose
    # unnecessary small steps on every circular orbit; gravity is covered by
    # the escape-speed allowance and IAS15's own force error control.
    mu = sim.G * (m[i] + m[j])
    speed = np.maximum(-radial, 0) + np.sqrt(2 * mu / np.maximum(distance, 1e-300))
    scale = np.maximum(distance - radius, fraction * radius)
    candidates = eligible & (radius > 0) & (speed > 0)
    if not np.any(candidates):
        return maximum
    interval = 0.5 * scale[candidates] / speed[candidates]
    # An outgoing pair must turn around before closing its gap. While it is
    # separating, its mutual inward acceleration is at most mu / distance**2;
    # tangential motion only delays the turn. Half that minimum turnaround
    # time avoids tiny steps for ejecta just outside a surface, while still
    # rechecking bound outgoing trajectories before they approach again.
    outgoing = (radial[candidates] > 0) & (mu[candidates] > 0)
    interval[outgoing] += (0.5 * radial[candidates][outgoing] * distance[candidates][outgoing]**2
                           / mu[candidates][outgoing])
    return min(maximum, float(np.min(interval)))


class ContactGuard:
    """Amortise pair checks across small native steps within a guarded interval.

    The interval is capped by the earliest pair approach scale, and no step
    crosses its end. Recompute after edits, collisions or fragment generation.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.check_at = -1.0

    def limit(self, sim, maximum):
        # Refresh before a proposed step crosses the cached interval. Splitting
        # at its old end can leave a tiny remainder that repeatedly shrinks
        # IAS15's next proposed step, even when every surface is still distant.
        if self.check_at <= sim.t + maximum:
            # Without a finite constraint, recheck on the next native call;
            # never cache an unbounded interval across changing trajectories.
            interval = contact_step_limit(sim, math.inf)
            if not math.isfinite(interval):
                return maximum
            self.check_at = sim.t + interval
        return min(maximum, self.check_at - sim.t)


def step(sim, maximum, guard):
    """One bounded IAS15 step, including its collision callback.

    REBOUND's global predictor convergence ratio is 0/0 for exactly force-free
    states. Its individual criterion handles zero acceleration correctly. Use
    that criterion only when gravity is identically absent, restoring the
    configured mode afterwards; gravitational steps retain PRS23 and epsilon.
    """
    free = sim.N <= 1 or sim.N_active == 0 or sim.G == 0
    sim.dt = guard.limit(sim, min(sim.dt, maximum))
    if not free:
        sim.steps(1)
    else:
        mode = sim.integrator.adaptive_mode
        sim.integrator.adaptive_mode = 'individual'
        try:
            sim.steps(1)
        finally:
            sim.integrator.adaptive_mode = mode
