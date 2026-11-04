"""On-demand orbital and spherical-body accounting; no rest-mass energy."""
from __future__ import annotations

import math
import numpy as np
import units


def physical_totals(world):
    """Resolved-body SI inventory, with unavailable quantities explicitly null.

    Binding uses homogeneous spheres. Unknown intrinsic inventories invalidate
    total energy and angular momentum; overlapping spheres invalidate potential
    energy. No missing heat or spin is silently replaced with a known zero.
    """
    if world.units != units.SYSTEM or not math.isclose(world.sim.G, units.G, rel_tol=1e-12):
        raise ValueError('Conservation reports require physical units and Newtonian gravity')
    snap = world.snapshot()
    m, r = snap['m'] * units.MASS_KG, snap['r'] * units.LENGTH_M
    x, v = snap['xyz'] * units.LENGTH_M, snap['v'] * units.VELOCITY_M_S
    if not all(np.isfinite(a).all() for a in (m, r, x, v)) or np.any(m <= 0) or np.any(r <= 0):
        raise ValueError('Conservation report requires finite state and positive masses/radii')
    inventories = [world.meta[name]['inventory'] for name in snap['names']]
    unknown = sum(s is None for s in inventories)
    spin, rotational, internal = None, None, None
    if not unknown:
        spins = np.array([s.spin_kg_m2_s for s in inventories]).reshape(-1, 3)
        spin = spins.sum(axis=0)
        rotational = float(np.sum(spins * spins / (.8 * m * r * r)[:, None]))
        internal = math.fsum(s.internal_energy_j for s in inventories)
    mutual = 0.0
    for i in range(len(m) - 1):
        distance = np.linalg.norm(x[i + 1:] - x[i], axis=1)
        if np.any(distance < (r[i] + r[i + 1:]) * (1 - 1e-12)):
            mutual = None
            break
        mutual -= float(units.G_SI * np.sum(m[i] * m[i + 1:] / distance))
    orbital = (m[:, None] * np.cross(x, v)).sum(axis=0)
    components = dict(translational_energy_j=float(.5 * np.sum(m[:, None] * v * v)),
                      rotational_energy_j=rotational, self_binding_j=float(-.6 * units.G_SI * np.sum(m * m / r)),
                      mutual_potential_j=mutual, internal_energy_j=internal)
    complete = all(value is not None for value in components.values())
    return dict(time_s=float(world.sim.t * units.TIME_S), bodies=len(m), unknown_inventories=unknown,
                tracers=sum(world.is_light(world.meta[n]['type'], mass) for n, mass in
                            zip(snap['names'], snap['m'], strict=True)),
                removed_bodies=world.removed['bodies'], mass_kg=float(m.sum()),
                momentum_kg_m_s=(m[:, None] * v).sum(axis=0).tolist(),
                orbital_angular_momentum_kg_m2_s=orbital.tolist(),
                spin_angular_momentum_kg_m2_s=None if spin is None else spin.tolist(),
                angular_momentum_kg_m2_s=None if spin is None else (orbital + spin).tolist(),
                **components, energy_j=math.fsum(components.values()) if complete else None,
                energy_scale_j=math.fsum(abs(v) for v in components.values()) if complete else None)


_BASELINE_KEYS = ('time_s', 'mass_kg', 'momentum_kg_m_s', 'angular_momentum_kg_m2_s',
                  'energy_j', 'energy_scale_j', 'removed_bodies')


def validate_baseline(value):
    """Validate and copy optional saved comparison metadata; no physics state."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(_BASELINE_KEYS):
        raise ValueError('Invalid conservation baseline fields')
    result = {}
    for key in _BASELINE_KEYS:
        item = value[key]
        if item is None and key in ('angular_momentum_kg_m2_s', 'energy_j', 'energy_scale_j'):
            result[key] = None
            continue
        vector = key in ('momentum_kg_m_s', 'angular_momentum_kg_m2_s')
        values = item if vector else [item]
        if not isinstance(values, (list, tuple)) or len(values) != (3 if vector else 1):
            raise ValueError('Invalid conservation baseline vector')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Conservation baseline values must be finite numbers')
        if key in ('time_s', 'mass_kg', 'energy_scale_j', 'removed_bodies') and item < 0:
            raise ValueError('Conservation baseline inventory must be nonnegative')
        if key == 'removed_bodies' and type(item) is not int:
            raise ValueError('Conservation baseline removal count must be an integer')
        result[key] = list(values) if vector else item
    if (result['energy_j'] is None) != (result['energy_scale_j'] is None):
        raise ValueError('Conservation baseline energy and scale must be available together')
    return result


def conservation_report(world, *, reset=False):
    """Compare remaining resolved inventories; changes include edits and losses."""
    current = physical_totals(world)
    snapshot = validate_baseline({key: current[key] for key in _BASELINE_KEYS})
    if reset or world.conservation_baseline is None:
        world.conservation_baseline = snapshot
    initial = validate_baseline(world.conservation_baseline)
    changes = {key: None if current[key] is None or initial[key] is None else
               (np.asarray(current[key]) - initial[key]).tolist()
               for key in ('mass_kg', 'momentum_kg_m_s', 'angular_momentum_kg_m2_s', 'energy_j')}
    relative = None if changes['energy_j'] is None else changes['energy_j'] / max(
        current['energy_scale_j'], initial['energy_scale_j'], 1e-300)
    return dict(current=current, baseline=initial, changes=changes, relative_energy_change=relative,
                removed_since_baseline=current['removed_bodies'] - initial['removed_bodies'])


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
