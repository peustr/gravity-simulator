"""On-demand orbital and spherical-body accounting; no rest-mass energy."""
from __future__ import annotations

import math
from copy import deepcopy
import numpy as np
import units
from debris_shell import shell_potential_energy


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
    samples = np.array([world.meta[name]['type'] == 6 and world.meta[name].get('tidal_sample', False)
                        for name in snap['names']], dtype=bool)
    compact = np.array([world.meta[name]['type'] == 4 for name in snap['names']], dtype=bool)
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
        included = ~(samples[i] & samples[i+1:])
        if np.any(((distance == 0) & included) | ((distance < (r[i] + r[i + 1:]) * (1 - 1e-12))
                                   & ~samples[i] & ~samples[i + 1:])):
            mutual = None
            break
        mutual -= float(units.G_SI * np.sum(m[i] * m[i + 1:][included] / distance[included]))
    orbital = (m[:, None] * np.cross(x, v)).sum(axis=0)
    components = dict(translational_energy_j=float(.5 * np.sum(m[:, None] * v * v)),
                      rotational_energy_j=rotational, self_binding_j=float(-.6 * units.G_SI * np.sum((m * m / r)[~samples & ~compact])),
                      mutual_potential_j=mutual, internal_energy_j=internal)
    momentum = (m[:, None] * v).sum(axis=0)
    mass = float(m.sum())
    components['model_potential_offset_j'] = world.tidal_potential_offset_j
    components['unresolved_accretion_energy_j'] = math.fsum(s['energy_j'] for s in world.accretion_flows.values())
    accretion_angular = np.sum([s['angular_momentum_kg_m2_s'] for s in world.accretion_flows.values()], axis=0) if world.accretion_flows else np.zeros(3)
    for shell in world.shells:
        mass += shell.mass_kg
        p = shell.mass_kg*np.array(shell.velocity_m_s)
        momentum += p
        orbital += np.cross(shell.centre_m,p)
        components['translational_energy_j'] += .5*shell.mass_kg*(math.fsum(v*v for v in shell.velocity_m_s)
                                                               +shell.radial_speed_m_s**2)
        components['self_binding_j'] += shell.self_binding_j
        if components['internal_energy_j'] is not None:
            components['internal_energy_j'] += shell.internal_energy_j
        components['model_potential_offset_j'] += shell.potential_offset_j
    if mutual is not None:
        components['mutual_potential_j'] += shell_potential_energy(world.shells,m,x)
    complete = all(value is not None for value in components.values())
    return dict(time_s=float(world.sim.t * units.TIME_S), bodies=len(m), unknown_inventories=unknown,
                ballistic_samples=int(samples.sum()), ballistic_mass_kg=float(m[samples].sum()),
                ballistic_backreaction=world.settings['gravity']=='full',
                tracers=sum(not world.exerts_gravity(n, mass) for n, mass in
                            zip(snap['names'], snap['m'], strict=True)),
                removed_bodies=world.removed['bodies'], mass_kg=mass,
                unresolved_fragments=sum(s.fragment_count for s in world.shells),reservoirs=len(world.shells),
                model_omitted_impulse_m_s=max(world.shell_error_history['max_omitted_impulse_m_s'],
                    max((s.omitted_impulse_m_s for s in world.shells),default=0.0)),
                model_error_history=world.shell_error_history.copy(),
                shell_numerical_energy_error_j=world.shell_numerical_energy_error_j,
                explicit_losses=deepcopy(world.physical_loss_ledger.totals),
                loss_event_count=world.physical_loss_ledger.event_count,
                momentum_kg_m_s=momentum.tolist(),
                orbital_angular_momentum_kg_m2_s=orbital.tolist(),
                spin_angular_momentum_kg_m2_s=None if spin is None else spin.tolist(),
                accretion_angular_momentum_kg_m2_s=accretion_angular.tolist(),
                angular_momentum_kg_m2_s=None if spin is None else (orbital + spin + accretion_angular).tolist(),
                **components, energy_j=math.fsum(components.values()) if complete else None,
                energy_scale_j=math.fsum(abs(v) for v in components.values()) if complete else None)


_BASELINE_KEYS = ('time_s', 'mass_kg', 'momentum_kg_m_s', 'angular_momentum_kg_m2_s',
                  'energy_j', 'energy_scale_j', 'removed_bodies')


def validate_baseline(value):
    """Validate and copy optional saved comparison metadata; no physics state."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value)-{'explicit_losses'} != set(_BASELINE_KEYS):
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
    result['explicit_losses'] = validate_losses(value['explicit_losses']) if value.get('explicit_losses') is not None else None
    return result


_LOSS_KEYS = ('mass_kg','momentum_kg_m_s','angular_momentum_kg_m2_s','energy_j')


def validate_losses(value):
    if not isinstance(value,dict) or set(value) != set(_LOSS_KEYS):
        raise ValueError('Invalid physical loss inventory')
    result = {}
    for key,item in value.items():
        if item is None:
            result[key] = None
            continue
        vector = key in ('momentum_kg_m_s','angular_momentum_kg_m2_s')
        values = item if vector else [item]
        if not isinstance(values,(list,tuple)) or len(values) != (3 if vector else 1):
            raise ValueError('Invalid physical loss vector')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
            raise ValueError('Physical losses must be finite numbers')
        result[key] = list(values) if vector else item
    return result


class PhysicalLossLedger:
    """Signed explicit removals/additions with complete aggregate inventories.

    Keep the last 64 event details and counters; aggregation never drops a budget.
    Unknown heat/spin propagates as unknown, rather than becoming a zero loss.
    """
    def __init__(self,state=None):
        self.totals = dict(mass_kg=0.,momentum_kg_m_s=[0.,0.,0.],angular_momentum_kg_m2_s=[0.,0.,0.],energy_j=0.)
        self.events = []
        self.event_count = 0
        self.unknown_events = 0
        if state is not None:
            if not isinstance(state,dict) or set(state) != {'totals','events','event_count','unknown_events'}:
                raise ValueError('Invalid physical loss history')
            self.totals = validate_losses(state['totals'])
            events = state['events']
            if not isinstance(events,list) or len(events) > 64:
                raise ValueError('Invalid physical loss event storage')
            for event in events:
                if (not isinstance(event,dict) or set(event) != {'time_s','reason','losses'}
                        or not isinstance(event['reason'],str) or not 1 <= len(event['reason']) <= 80
                        or type(event['time_s']) not in (int,float) or not math.isfinite(event['time_s'])
                        or event['time_s'] < 0):
                    raise ValueError('Invalid physical loss event')
                self.events.append(dict(time_s=event['time_s'],reason=event['reason'],losses=validate_losses(event['losses'])))
            for key in ('event_count','unknown_events'):
                if type(state[key]) is not int or state[key] < 0:
                    raise ValueError('Invalid physical loss event count')
            if state['event_count'] < len(events) or state['unknown_events'] > state['event_count']:
                raise ValueError('Inconsistent physical loss event counts')
            self.event_count,self.unknown_events = state['event_count'],state['unknown_events']

    def state(self):
        return deepcopy(dict(totals=self.totals,events=self.events,event_count=self.event_count,unknown_events=self.unknown_events))

    def capture(self,world):
        try:
            return physical_totals(world)
        except ValueError:
            return None

    def record(self,reason,before,after):
        self.event_count += 1
        if before is None or after is None:
            self.unknown_events += 1
            self.totals = {key:None for key in _LOSS_KEYS}
            return
        losses = {}
        for key in _LOSS_KEYS:
            losses[key] = None if before[key] is None or after[key] is None else (
                np.asarray(before[key])-after[key]).tolist()
            self.totals[key] = None if self.totals[key] is None or losses[key] is None else (
                np.asarray(self.totals[key])+losses[key]).tolist()
        if any(v is None for v in losses.values()):
            self.unknown_events += 1
        self.events.append(dict(time_s=after['time_s'],reason=reason,losses=losses))
        self.events = self.events[-64:]


def conservation_report(world, *, reset=False):
    """Compare remaining resolved inventories; changes include edits and losses."""
    current = physical_totals(world)
    snapshot = validate_baseline({key: current[key] for key in (*_BASELINE_KEYS,'explicit_losses')})
    if reset or world.conservation_baseline is None:
        world.conservation_baseline = snapshot
    initial = validate_baseline(world.conservation_baseline)
    changes = {key: None if current[key] is None or initial[key] is None else
               (np.asarray(current[key]) - initial[key]).tolist()
               for key in ('mass_kg', 'momentum_kg_m_s', 'angular_momentum_kg_m2_s', 'energy_j')}
    relative = None if changes['energy_j'] is None else changes['energy_j'] / max(
        current['energy_scale_j'], initial['energy_scale_j'], 1e-300)
    losses,adjusted = {},{}
    for key in _LOSS_KEYS:
        start = initial['explicit_losses']
        losses[key] = None if start is None or start[key] is None or current['explicit_losses'][key] is None else (
            np.asarray(current['explicit_losses'][key])-start[key]).tolist()
        adjusted[key] = None if losses[key] is None or changes[key] is None else (
            np.asarray(changes[key])+losses[key]).tolist()
    return dict(current=current, baseline=initial, changes=changes, relative_energy_change=relative,
                explicit_losses=losses,conservation_residual=adjusted,
                relative_conservation_residual=None if adjusted['energy_j'] is None else adjusted['energy_j']/max(
                    current['energy_scale_j'],initial['energy_scale_j'],1e-300),
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
    tracers = sum(not world.exerts_gravity(n, mass)
                  for n, mass in zip(snap['names'], m, strict=True))
    mass = float(m.sum())
    energy_unit = units.MASS_KG*units.VELOCITY_M_S**2
    if world.shells:
        for shell in world.shells:
            mass += shell.mass_kg/units.MASS_KG
            p = shell.mass_kg*np.array(shell.velocity_m_s)
            momentum += p/(units.MASS_KG*units.VELOCITY_M_S)
            angular += np.cross(shell.centre_m,p)/(units.MASS_KG*units.LENGTH_M*units.VELOCITY_M_S)
            kinetic += .5*shell.mass_kg*(math.fsum(v*v for v in shell.velocity_m_s)+shell.radial_speed_m_s**2)/energy_unit
        potential += (shell_potential_energy(world.shells,m*units.MASS_KG,x*units.LENGTH_M)
                      +sum(s.potential_offset_j for s in world.shells))/energy_unit
    return dict(mass=mass, momentum=momentum.tolist(),
                angular_momentum=angular.tolist(), kinetic_energy=kinetic,
                potential_energy=potential, energy=kinetic + potential,
                tracers=int(tracers), bodies=len(m)+sum(s.fragment_count for s in world.shells), time=float(world.sim.t))


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
