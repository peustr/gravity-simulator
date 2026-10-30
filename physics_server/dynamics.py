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


def _contact_geometry(sim):
    m, r = np.empty(sim.N), np.empty(sim.N)
    sim.serialize_particle_data(m=m, r=r)
    if sim.N_active < sim.N:
        m[sim.N_active:] = 0
    i, j = _pairs(sim.N)
    vectors = [np.empty((len(i), 3)) for _ in range(3)]
    return i, j, r[i] + r[j], sim.G * m[i], sim.G * m[j], np.empty(3 * sim.N), np.empty(3 * sim.N), *vectors


def contact_step_limit(sim, maximum, fraction=CONTACT_FRACTION, *, _geometry=None):
    """Limit approach to finite surfaces before IAS15 evaluates a singular centre.

    Outside overlaps, bound all source accelerations over an interval in which
    no pair can halve its separation. Use radial motion and that acceleration
    bound to limit gap closure, without charging circular orbits for immediate
    motion at escape speed. Existing overlaps retain the pair escape-speed
    safeguard so new ejecta can separate. Allow a small finite overlap for
    direct collision detection; IAS15 still controls integration error.
    """
    if sim.N < 2:
        return maximum
    i, j, radius, gmi, gmj, x, v, dx, dv, scratch = _contact_geometry(sim) if _geometry is None else _geometry
    sim.serialize_particle_data(xyz=x, vxvyvz=v)
    # Gather into reusable contiguous buffers instead of allocating indexed
    # copies on every near-contact step.
    for values, delta in ((x, dx), (v, dv)):
        np.take(values.reshape(-1, 3), j, axis=0, out=delta)
        np.take(values.reshape(-1, 3), i, axis=0, out=scratch)
        np.subtract(delta, scratch, out=delta)
    distance2 = np.einsum('ij,ij->i', dx, dx)
    distance = np.sqrt(distance2)
    radial = np.einsum('ij,ij->i', dx, dv) / np.maximum(distance, 1e-300)
    scale = np.maximum(distance - radius, fraction * radius)
    if np.all(distance > radius):
        # If every separation stays >= d/2, each source acceleration is at most
        # 4*G*m/d**2. Sum magnitudes: this also bounds third-body perturbations.
        acceleration = (np.bincount(i, weights=4 * gmj / distance2, minlength=sim.N)
                        + np.bincount(j, weights=4 * gmi / distance2, minlength=sim.N))
        pair_acceleration = acceleration[i] + acceleration[j]
        speed2 = np.einsum('ij,ij->i', dv, dv)
        # Solve |dv|*t + A*t**2/2 = d/2. Before the earliest such time, the
        # assumed separation floor, and hence the acceleration bound, hold.
        denominator = np.sqrt(speed2) + np.sqrt(speed2 + pair_acceleration * distance)
        horizon = np.full(len(i), math.inf)
        np.divide(distance, denominator, out=horizon, where=denominator > 0)
        # Projection along the initial separation gives
        # d(t) >= d + radial*t - A*t**2/2. Allow half the gap (or contact scale).
        denominator = np.abs(radial) + np.sqrt(radial**2 + pair_acceleration * scale)
        interval = np.full(len(i), math.inf)
        np.divide(scale, denominator, out=interval, where=denominator > 0)
        outgoing = radial > 0
        # Use the other quadratic root form for outgoing motion to avoid
        # subtracting nearly equal numbers. Force-free outgoing pairs stay free.
        np.divide(denominator, pair_acceleration, out=interval, where=outgoing & (pair_acceleration > 0))
        interval[(outgoing & (pair_acceleration == 0)) | (radius <= 0)] = math.inf
        return min(maximum, float(np.min(horizon)), float(np.min(interval)))

    mu = gmi + gmj
    # Outside surfaces, gravity can turn an initially receding pair around
    # during a large trial step. Separating overlaps must remain free to leave.
    eligible = (distance > radius) | (radial <= 0)
    # Tangential velocity alone cannot close a gap. Including it would impose
    # unnecessary small steps on every circular orbit; gravity is covered by
    # the escape-speed allowance and IAS15's own force error control.
    speed = np.maximum(-radial, 0) + np.sqrt(2 * mu / np.maximum(distance, 1e-300))
    candidates = eligible & (radius > 0) & (speed > 0)
    interval = np.full(len(i), math.inf)
    np.divide(0.5 * scale, speed, out=interval, where=candidates)
    # An outgoing pair must turn around before closing its gap. While it is
    # separating, its mutual inward acceleration is at most mu / distance**2;
    # tangential motion only delays the turn. Half that minimum turnaround
    # time avoids tiny steps for ejecta just outside a surface, while still
    # rechecking bound outgoing trajectories before they approach again.
    delay = np.zeros(len(i))
    np.divide(0.5 * np.maximum(radial, 0) * distance**2, mu, out=delay, where=mu > 0)
    interval += delay
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
        self.geometry = None
        self.geometry_key = None

    def limit(self, sim, maximum):
        key = (sim.N, sim.N_active, sim.G)
        if key != self.geometry_key:
            self.reset()
            self.geometry_key = key
        if self.geometry is None:
            self.geometry = _contact_geometry(sim)
        # Refresh before a proposed step crosses the cached interval. Splitting
        # at its old end can leave a tiny remainder that repeatedly shrinks
        # IAS15's next proposed step, even when every surface is still distant.
        if self.check_at <= sim.t + maximum:
            # Without a finite constraint, recheck on the next native call;
            # never cache an unbounded interval across changing trajectories.
            interval = contact_step_limit(sim, math.inf, _geometry=self.geometry)
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
