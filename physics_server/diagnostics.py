"""Opt-in Newtonian accounting. No spin, thermal, or rest-mass energy is modelled."""
from __future__ import annotations

import numpy as np


def totals(world):
    """All-body inventory, including tracer masses (not necessarily conserved).

    Use the same inertial origin for comparisons. Pair potential is unsoftened,
    even for overlaps. Coincident centres have undefined Newtonian potential.
    This does not change particle order, RNG state, or the simulation.
    """
    snap = world.snapshot()
    m, x, v = snap['m'], snap['xyz'], snap['v']
    if not all(np.isfinite(a).all() for a in (m, x, v)):
        raise ValueError('Non-finite physical state')
    momentum = (m[:, None] * v).sum(axis=0)
    angular = (m[:, None] * np.cross(x, v)).sum(axis=0)
    kinetic = float(0.5 * np.sum(m[:, None] * v * v))
    potential = 0.0
    for i in range(len(m) - 1):
        distance = np.linalg.norm(x[i + 1:] - x[i], axis=1)
        if np.any(distance == 0):
            raise ValueError('Coincident centres have undefined potential energy')
        potential -= float(world.sim.G * np.sum(m[i] * m[i + 1:] / distance))
    tracers = sum(world.is_light(world.meta[n]['type'], mass)
                  for n, mass in zip(snap['names'], m, strict=True))
    return dict(mass=float(m.sum()), momentum=momentum.tolist(),
                angular_momentum=angular.tolist(), kinetic_energy=kinetic,
                potential_energy=potential, energy=kinetic + potential,
                tracers=int(tracers), bodies=len(m), time=float(world.sim.t))


def difference(after, before):
    """Signed inventory changes; vectors retain direction and absolute units."""
    return {key: (np.asarray(after[key]) - before[key]).tolist()
            for key in ('mass', 'momentum', 'angular_momentum', 'energy')}


class Ledger:
    """Observed changes across known removal rules, not a radiation model.

    Adding each recorded loss to the remaining inventory accounts for those
    rules only. Collisions, explosions and tracer forces may still change the
    inventory; the remainder is NOT automatically numerical error.
    """

    def __init__(self):
        self.entries = []
        self.errors = []

    def capture(self, world):
        # Diagnostics must never prevent the rule being observed from running.
        try:
            return totals(world)
        except ValueError as exc:
            self.errors.append(dict(time=float(world.sim.t), error=str(exc)))
            return None

    def record(self, reason, before, after):
        if before is None or after is None:
            return
        self.entries.append(dict(reason=reason, time=after['time'],
                                 removed=difference(before, after)))

    def report(self, initial, final):
        removed = {key: np.zeros_like(initial[key], dtype=float)
                   for key in ('mass', 'momentum', 'angular_momentum', 'energy')}
        for entry in self.entries:
            for key in removed:
                removed[key] += entry['removed'][key]
        adjusted = {key: (np.asarray(final[key]) + value).tolist()
                    for key, value in removed.items()}
        return dict(initial=initial, final=final, changes=difference(final, initial),
                    recorded_losses={key: value.tolist() for key, value in removed.items()},
                    remaining_change=difference(adjusted, initial), entries=self.entries, errors=self.errors,
                    interpretation='Remaining change includes model effects; it is not an integrator error estimate.')
