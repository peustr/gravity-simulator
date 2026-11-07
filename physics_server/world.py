"""
world.py - the physics brain of Gravity Simulator.

Everything that moves is a REBOUND particle. REBOUND integrates gravity with
IAS15 (an adaptive 15th-order integrator that stays accurate through close
encounters), detects collisions, and calls back into this file whenever two
bodies touch. This file then decides what the collision *means*:

  * gentle impacts merge (momentum and mass are conserved),
  * violent impacts shatter bodies into fragments (a simplified version of the
    Leinhardt & Stewart 2012 "universal law" for the largest remnant),
  * anything that touches a black hole is swallowed,
  * bodies that wander inside a massive body's Roche limit are torn apart by
    tides (spaghettification),
  * gas giants that grow heavy enough ignite into stars, neutron stars that
    grow too heavy collapse into black holes, and stars can go supernova.

New scenes use explicit physical units (see units.py) and physical contact
radii. Visual enlargement belongs exclusively to the client. Version-1 saves
retain their original sandbox scale and radius rules in a labelled legacy mode.
"""

from __future__ import annotations

import ctypes
import math
import random
import time
import traceback

import warnings

import numpy as np
import rebound

import units
import configuration
from impacts import capture as capture_impact
from body_state import BodyInventory, GravitySource, capture_sphere
from collision_models import construct_collision, couple_collision
from collision_outcomes import absorb_point_sample
from diagnostics import totals,PhysicalLossLedger,conservation_report
from dynamics import ContactGuard, step, GAS_SINK_RADII
from debris_shell import MAX_SHELLS, ShellIntegrator, approaching_contacts, form_shell, model_defect, shell_energy
from dataclasses import replace
from encounters import DEMO_CASES, demo_initial_conditions
from tidal_debris import source_samples
from rotation import Rotation, angular_velocity
from equilibrium_tides import Tide, MAX_TIDAL_BODIES, response as tidal_response, orbit as tidal_orbit
from tidal_integrator import TidalIntegrator

# REBOUND rebuilds its name lookup table on its own; the warning is just noise.
warnings.filterwarnings("ignore", message=".*hash table.*")

G = 1.0  # units.G is unity to floating-point precision
_INITIAL_INVENTORY = BodyInventory()
MAX_BODIES = 1321  # 11 + 12*N + 8*64 float32 values must fit IPv4 UDP (65507 bytes).
SCENARIOS = ("solar", "binary", "black_hole", "smash", "formation", "galaxies", "empty")
PRESET_SPEEDS = dict(solar=1.0, binary=10.0, black_hole=0.005, smash=0.05,
                    formation=1.0, galaxies=8.0, empty=10.0)

# --- Body types (must match godot/scripts/palette.gd) -------------------------
ROCKY, GAS_GIANT, STAR, NEUTRON_STAR, BLACK_HOLE, ASTEROID, PLASMA = range(7)

TYPE_KEYS = {
    "rocky": ROCKY,
    "gas_giant": GAS_GIANT,
    "star": STAR,
    "neutron_star": NEUTRON_STAR,
    "black_hole": BLACK_HOLE,
    "asteroid": ASTEROID,
    "plasma": PLASMA,
}

DEFAULT_MASS = {
    ROCKY: 0.003,        # ~ Earth
    GAS_GIANT: 1.0,      # ~ Jupiter
    STAR: 1000.0,        # ~ Sun
    NEUTRON_STAR: 1400.0,  # ~ 1.4 Suns, the classic neutron star mass
    BLACK_HOLE: 20000.0,   # ~ 20 Suns, a stellar-mass black hole
    ASTEROID: 2e-5,
    PLASMA: 1.0,
}

# --- Mass thresholds where a body changes type (only ever upwards) -----------
ASTEROID_TO_ROCKY = 3e-4    # about a Mars mass: a proper planet
ROCKY_TO_GAS = 0.03         # ~10 Earths: runaway gas accretion begins
GAS_TO_STAR = 80.0          # ~80 Jupiters: the hydrogen-burning limit
NEUTRON_TO_BH = 2300.0      # ~2.3 Suns: the maximum neutron star mass (TOV limit)
STAR_COLLAPSE = 40000.0     # merged stars this heavy go supernova on the spot

# Tidal disruption: r_t = TIDAL_K * (M_heavy / density_victim)^(1/3)
TIDAL_K = 1.1
TIDAL_DENSITY = {ROCKY: 4.0, GAS_GIANT: 1.3, STAR: 1.0}
TIDAL_MIN_MASS = 5e-4        # smaller rocks are too small to bother disrupting
HEAVY_TYPES = (STAR, NEUTRON_STAR, BLACK_HOLE)

# --- Event codes sent to Godot (must match godot/scripts/main.gd) ------------
EV_MERGE = 1
EV_SHATTER = 2
EV_SWALLOW = 3
EV_TIDAL = 4
EV_SUPERNOVA = 5
EV_IGNITION = 6
EV_COLLAPSE = 7
EV_BH_MERGER = 8
EV_KILONOVA = 9
EV_HIT_AND_RUN = 10
EV_ACCRETION = 11
EV_EROSION = 12

# Light debris (asteroids, small gas clouds) are "test particles": they feel
# everyone's gravity but don't pull on anything themselves. That is the
# classic trick (Toomre & Toomre used it for colliding galaxies in 1972) and
# makes debris-heavy scenes about 10x faster. They still collide normally.
LIGHT_TYPES = (ASTEROID, PLASMA)
LIGHT_MASS = 0.5
PARTICLE_SIZE = ctypes.sizeof(rebound.Particle)

ESCAPE_DISTANCE = 15000.0
SHATTER_MIN_MASS = 1e-4      # collisions lighter than this just merge (dust settles)
MIN_FRAGMENT_MASS = 5e-6     # never make fragments lighter than this
HEAT_COOLING_TIME = 40.0


def radius_for(btype: int, m: float) -> float:
    """Physical contact radius for new scenes; never a display size."""
    return units.physical_radius(btype, m)


def legacy_radius_for(btype: int, m: float) -> float:
    """Version-1 sandbox radii, retained only for old scene dynamics."""
    m = max(m, 1e-12)
    if btype == ROCKY:
        return max(0.2, (m / 0.003) ** (1.0 / 3.0))
    if btype == GAS_GIANT:
        # Gas giants barely change size with mass (degenerate matter).
        return 2.8 * max(m, 0.03) ** 0.08
    if btype == STAR:
        # Main-sequence stars: R grows a bit slower than M.
        return max(2.4, 5.0 * (m / 1000.0) ** 0.55)
    if btype == NEUTRON_STAR:
        return 0.6
    if btype == BLACK_HOLE:
        # Schwarzschild radius is proportional to mass.
        return max(0.6, 3.0 * m / 10000.0)
    if btype == ASTEROID:
        return max(0.2, (m / 0.003) ** (1.0 / 3.0))
    if btype == PLASMA:
        return min(4.0, max(0.08, 0.35 * m ** (1.0 / 3.0)))
    return 1.0


# --- Tiny vector helpers (plain tuples keep the hot paths simple) ------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a, fallback=(1.0, 0.0, 0.0)):
    n = _norm(a)
    return _mul(a, 1.0 / n) if n > 1e-12 else fallback


class World:
    """Owns the REBOUND simulation plus the game-level bookkeeping around it."""

    def __init__(self, max_bodies: int = 600, seed: int | None = None):
        if type(max_bodies) is not int or not 1 <= max_bodies <= MAX_BODIES:
            raise ValueError(f"max_bodies must be an integer from 1 to {MAX_BODIES}")
        self.max_bodies = max_bodies
        self.units = units.SYSTEM
        self.settings = configuration.DEFAULTS.copy()
        self.rng = random.Random(seed)
        self.speed = 10.0          # simulation time units per real second
        self.paused = False
        self.version = 0           # bumps whenever particle data changes
        self.events: list[tuple] = []
        self.notices: list[dict] = []
        self.perf = 1.0            # achieved / requested simulation speed
        self._next_id = 1
        self._pending: list[dict] = []
        self._supernova_queue: list[int] = []
        self._target_t = 0.0
        self._ema_req = 0.0
        self._ema_got = 0.0
        self.sim: rebound.Simulation | None = None
        self.meta: dict[str, dict] = {}
        self._names: list[str] = []
        self._index: dict[str, int] = {}
        self._names_dirty = True
        self._partition_dirty = True
        self._new_simulation()

    # ------------------------------------------------------------------ setup
    def _new_simulation(self):
        self.collision_demo = None
        self.last_impact = None
        self.shells = ()
        self._next_shell_id = 1
        self._shell_integrator = None
        self._tide_integrator = None
        self.shell_numerical_energy_error_j = 0.0
        self.tidal_potential_offset_j = 0.0
        self.accretion_flows = {}
        self.shell_error_history = dict(max_omitted_impulse_m_s=0.0, refused_steps=0, last_refusal='')
        self.physical_loss_ledger = PhysicalLossLedger()
        self.conservation_baseline = None
        self.ledger = None  # opt-in accounting applies to one world history
        self.removed = dict(bodies=0, mass=0.0, momentum=[0.0] * 3, angular_momentum=[0.0] * 3,
                            energy=0.0, energy_defined=True)
        sim = rebound.Simulation()
        sim.G = G
        sim.integrator = "ias15"
        # Physical compact objects need timesteps below the old sandbox floor.
        sim.integrator.min_dt = 1e-4 if self.units == units.LEGACY else 0.0
        sim.integrator.epsilon = self.settings['epsilon']
        sim.collision = "direct"
        sim.collision_resolve = self._resolve_collision
        self.sim = sim
        self._contact_guard = ContactGuard()
        self._tidal_pairs = None
        self.events.clear()
        self.notices.clear()
        self._partition_dirty = True
        self._ema_req = self._ema_got = 0.0
        self.perf = 1.0
        self.meta = {}
        self._pending = []
        self._supernova_queue = []
        self._names_dirty = True
        self._target_t = 0.0
        self.version += 1

    def clear(self):
        self.units = units.SYSTEM
        self.settings.update(collisions='auto', gravity='full',impact_material='fluid_planets')
        self._new_simulation()

    def configure(self, changes):
        configuration.settings(changes, partial=True)
        settings = configuration.settings(self.settings | changes)
        if settings['collisions'] in ('isolated_mergers', 'isolated_impacts') and (self.units != units.SYSTEM or settings['gravity'] != 'full'
                                                    or settings['escape_distance'] is not None):
            raise ValueError('Calibrated impacts require physical units, full gravity and disabled escape removal')
        if settings['collisions'] == 'auto' and self.units != units.SYSTEM:
            raise ValueError('Automatic collisions require physical units')
        if self.shells and (settings['gravity'] != 'full' or settings['collisions'] == 'heuristic'):
            raise ValueError('Unresolved ejecta require full gravity and calibrated collision handling')
        if settings['gravity'] != 'full' and any(md.get('tide') for md in self.meta.values()):
            raise ValueError('Equilibrium tides require full gravitational backreaction')
        self.settings = settings
        self._set_solver_tolerance()
        self._partition_dirty = True
        self._repartition()
        self.sim.did_modify_particles = 1
        self.version += 1

    def _set_solver_tolerance(self):
        if str(self.sim.integrator) == 'bs':
            self.sim.integrator.eps_rel = self.settings['epsilon']*.01
            self.sim.integrator.eps_abs = self.settings['epsilon']*.001
        else:
            self.sim.integrator.epsilon = self.settings['epsilon']

    def solver_name(self):
        return 'IAS15 + CTL tides' if any(md.get('tide') for md in self.meta.values()) else 'BS (ejecta)' if self.shells else str(self.sim.integrator).upper()

    def gravity_summary(self):
        snap = self.snapshot()
        passive = [not self.exerts_gravity(n, mass)
                   for n, mass in zip(snap['names'], snap['m'], strict=True)]
        omitted = float(snap['m'][passive].sum())
        total = float(snap['m'].sum())+sum(s.mass_kg/units.MASS_KG for s in self.shells)
        return dict(settings=self.settings.copy(), tracers=sum(passive), tracer_mass=omitted,
                    tidal_bodies=sum(bool(md.get('tide')) for md in self.meta.values()),
                    gas_capture_radius_rs=GAS_SINK_RADII if self.units == units.SYSTEM else 0.,
                    tracer_mass_fraction=omitted / total if total else 0.0, removed=self.removed.copy(),
                    reservoirs=len(self.shells),unresolved_fragments=sum(s.fragment_count for s in self.shells),
                    collision_demo=self.collision_demo, last_impact=self.last_impact)

    def radius_for(self, btype, mass):
        model = legacy_radius_for if self.units == units.LEGACY else radius_for
        return model(btype, mass)

    def body_radius(self, particle):
        """Physical sphere radius or a node's equivalent-volume radius."""
        return particle.r if particle.r > 0 else self.meta.get(particle.name,{}).get('volume_radius',0.)

    def rotation(self, particle):
        """Synchronise an instantaneous inventory/radius edit at current time."""
        md = self.meta.get(particle.name)
        if md is None:
            return None,False
        if md['type'] not in (ROCKY,ASTEROID):
            md.pop('rotation',None)
            return None,False
        known = self.units == units.SYSTEM and md['inventory'] is not None and particle.m > 0 and particle.r > 0
        omega = angular_velocity(md['inventory'].spin_kg_m2_s,particle.m*units.MASS_KG,
                                 particle.r*units.LENGTH_M) if known else (0.,0.,0.)
        now = self.sim.t*units.TIME_S
        old = md.get('rotation')
        if old is None or old.omega_rad_s != omega:
            old = Rotation(old.at(now) if old else (0.,0.,0.,1.),now,omega)
            md['rotation'] = old
        return old,known

    def seed_rotation(self, bid, period_s, tilt=0.):
        """An initial solid-body spin; tilt is relative to the +Y orbital pole."""
        if bid is None:
            return
        p = self.particle(str(bid))
        if (p is None or self.units != units.SYSTEM or self.meta[p.name]['type'] not in (ROCKY,ASTEROID)
                or self.meta[p.name]['inventory'] is None or not math.isfinite(period_s) or period_s <= 0
                or not math.isfinite(tilt)):
            raise ValueError('Spin initial conditions require a known solid sphere and finite positive period')
        axis = (math.sin(tilt),math.cos(tilt),0.)
        inertia = .4*(p.m*units.MASS_KG)*(p.r*units.LENGTH_M)**2
        self.meta[p.name]['inventory'] = BodyInventory(tuple(inertia*2*math.pi*x/period_s for x in axis),
                                                     self.meta[p.name]['inventory'].internal_energy_j)
        q = (0.,0.,-math.sin(tilt/2),math.cos(tilt/2))
        self.meta[p.name]['rotation'] = Rotation(q,self.sim.t*units.TIME_S,
                                               tuple(2*math.pi*x/period_s for x in axis))

    def set_tide(self, bid, k2, lag_s):
        material = Tide(k2,lag_s)
        p = self.particle(str(bid))
        if p is not None and k2 == 0:
            self.meta[p.name].pop('tide',None)
            self._tide_integrator = None
            self.version += 1
            return
        if (p is None or self.units != units.SYSTEM or self.settings['gravity'] != 'full'
                or self.meta[p.name]['type'] not in (ROCKY,ASTEROID) or self.meta[p.name]['inventory'] is None or self.shells):
            raise ValueError('Equilibrium tides require a known solid, full gravity and resolved bodies')
        if k2 and not self.meta[p.name].get('tide') and sum(bool(md.get('tide')) for md in self.meta.values()) >= MAX_TIDAL_BODIES:
            raise ValueError(f'At most {MAX_TIDAL_BODIES} deformable solids are supported')
        previous = self.meta[p.name].get('tide')
        if previous is not None:
            material = replace(material,heat_j=previous.heat_j)
        snap = self.snapshot()
        index = snap['names'].index(p.name)
        tidal_response(snap['m']*units.MASS_KG,snap['xyz']*units.LENGTH_M,snap['v']*units.VELOCITY_M_S,
                       index,p.r*units.LENGTH_M,self.rotation(p)[0].omega_rad_s,material)
        self.meta[p.name]['tide'] = material
        self._tide_integrator = None
        self.sim.did_modify_particles = 1
        self.version += 1

    def tidal_profiles(self):
        profiles = []
        for i,p in enumerate(self.sim.particles):
            md = self.meta[p.name]
            if md.get('tide'):
                if md['type'] not in (ROCKY,ASTEROID) or md['inventory'] is None:
                    raise ValueError('Equilibrium tides lost a supported solid inventory')
                profiles.append((i,md['tide'],self.rotation(p)[0].omega_rad_s))
        return profiles

    def tidal_info(self):
        snap = self.snapshot()
        data = []
        for i,p in enumerate(self.sim.particles):
            material = self.meta[p.name].get('tide')
            if material is None:
                continue
            row = dict(id=int(p.name),k2=material.k2,lag_s=material.lag_s,heat_j=material.heat_j)
            try:
                state,known = self.rotation(p)
                if not known:
                    raise ValueError('Unknown solid spin inventory')
                omega = state.omega_rad_s
                _,torque,power,_ = tidal_response(snap['m']*units.MASS_KG,snap['xyz']*units.LENGTH_M,snap['v']*units.VELOCITY_M_S,
                                                i,snap['r'][i]*units.LENGTH_M,omega,material)
            except (ValueError,ArithmeticError) as exc:
                data.append(row | dict(error=str(exc)))
                continue
            orbit = tidal_orbit(snap['m']*units.MASS_KG,snap['xyz']*units.LENGTH_M,snap['v']*units.VELOCITY_M_S,i)
            ratio = None if orbit is None else float(np.dot(omega,orbit['axis'])/orbit['mean_motion'])
            data.append(row | dict(power_w=power,spin_ratio=ratio,eccentricity=None if orbit is None else orbit['eccentricity'],
                                   torque_nm=float(np.linalg.norm(torque))))
        return data

    def is_ballistic(self, name):
        md = self.meta.get(name,{})
        return self.units == units.SYSTEM and md.get('type') == PLASMA and md.get('tidal_sample',False)

    def exerts_gravity(self, name, mass):
        """Force on resolved bodies; ballistic nodes do not attract each other."""
        return not self.is_light(self.meta.get(name,{}).get('type',ASTEROID),mass) and (
            self.settings['gravity'] == 'full' or not self.is_ballistic(name))

    def contact_radii(self, snap):
        radii = snap['r'].copy()
        for i, name in enumerate(snap['names']):
            if self.is_ballistic(name):
                radii[i] = 0
        return radii

    # ------------------------------------------------------------ bookkeeping
    def _refresh_names(self):
        if self._names_dirty or len(self._names) != self.sim.N:
            self._names = [p.name for p in self.sim.particles]
            self._index = {n: i for i, n in enumerate(self._names)}
            self._names_dirty = False

    def particle(self, name: str):
        self._refresh_names()
        idx = self._index.get(name)
        if idx is None:
            return None
        return self.sim.particles[idx]

    @property
    def capacity(self) -> int:
        return max(0, self.max_bodies - self.sim.N)

    def add_body(self, btype, mass, pos, vel, heat=0.0, *, inventory=_INITIAL_INVENTORY):
        if self.sim.N >= self.max_bodies or mass <= 0:
            return None
        if inventory is not None and not isinstance(inventory, BodyInventory):
            raise ValueError('Expected a body inventory or None')
        if self.units == units.LEGACY:
            if inventory not in (None, _INITIAL_INVENTORY):
                raise ValueError('Legacy units cannot carry SI body inventories')
            inventory = None
        bid = self._next_id
        self._next_id += 1
        name = str(bid)
        self.sim.add(
            m=float(mass), r=self.radius_for(btype, mass),
            x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
            vx=float(vel[0]), vy=float(vel[1]), vz=float(vel[2]),
        )
        # Name it *after* adding, so REBOUND copies the string into memory it
        # owns. (Passing name= to add() keeps a pointer to a temporary Python
        # buffer, which can be garbage collected.)
        self.sim.particles[self.sim.N - 1].name = name
        self.meta[name] = {"type": btype, "born": self.sim.t, "heat": float(heat),
                           "inventory": inventory}
        if btype in (ROCKY,ASTEROID):
            self.rotation(self.sim.particles[self.sim.N-1])
        self._names_dirty = True
        self._partition_dirty = True
        self.version += 1
        return bid

    # ------------------------------------------------- massive vs test particles
    def is_light(self, btype, mass) -> bool:
        return bool(self.settings['gravity'] == 'tracers' and btype in LIGHT_TYPES and mass < LIGHT_MASS)

    def _swap(self, i, j):
        ps = self.sim.particles
        a = ctypes.addressof(ps[i])
        b = ctypes.addressof(ps[j])
        buf = ctypes.create_string_buffer(PARTICLE_SIZE)
        ctypes.memmove(buf, a, PARTICLE_SIZE)
        ctypes.memmove(a, b, PARTICLE_SIZE)
        ctypes.memmove(b, buf, PARTICLE_SIZE)

    def _repartition(self):
        """Keep massive bodies first in REBOUND's array and set N_active."""
        if not self._partition_dirty:
            return
        self._partition_dirty = False
        self._contact_guard.reset()
        self._shell_integrator = None
        self._tide_integrator = None
        self._tidal_pairs = None
        sim = self.sim
        n = sim.N
        if n == 0:
            sim.N_active = 0
            self._contact_guard.collisionless = frozenset()
            self._contact_guard.sinks = ()
            return
        self._refresh_names()
        m = np.zeros(n)
        for name in self._names:
            md = self.meta[name]
            if self.is_ballistic(name):
                p = self.particle(name)
                if p.r > 0:
                    md['volume_radius'],p.r = p.r,0
        sim.serialize_particle_data(m=m)
        heavy = [not self.is_ballistic(nm) and self.exerts_gravity(nm,m[i])
                 for i, nm in enumerate(self._names)]
        k = 0
        swapped = False
        for i in range(n):
            if heavy[i]:
                if i != k:
                    self._swap(i, k)
                    heavy[i], heavy[k] = heavy[k], heavy[i]
                    swapped = True
                k += 1
        sim.N_active = k
        # Frozen-in volume nodes have no mutual self-gravity. In full mode
        # their masses still react gravitationally on every resolved body.
        sim.testparticle_type = 1 if self.settings['gravity'] == 'full' else 0
        if swapped:
            self._names_dirty = True
            self.sim.did_modify_particles = 1
        self._refresh_names()
        self._contact_guard.collisionless = frozenset(
            i for i, name in enumerate(self._names)
            if self.is_ballistic(name))
        self._contact_guard.sinks = tuple((i, self.sim.particles[i].r * GAS_SINK_RADII)
                                          for i, name in enumerate(self._names) if self.meta[name]['type'] == BLACK_HOLE)

    def remove_body(self, bid) -> bool:
        name = str(int(bid))
        self._refresh_names()
        idx = self._index.get(name)
        if idx is None:
            return False
        self.sim.remove(idx)
        self.accretion_flows.pop(name, None)
        self._partition_dirty = True
        self.meta.pop(name, None)
        self._names_dirty = True
        self.version += 1
        return True

    def _event(self, kind, pos, magnitude, size, id_a=-1, id_b=-1):
        self.events.append((kind, pos[0], pos[1], pos[2], magnitude, size, id_a, id_b))

    def notice(self, text: str):
        self.notices.append({"type": "notice", "text": text})

    # --------------------------------------------------------------- snapshot
    def snapshot(self):
        """Arrays describing every body, aligned by index."""
        self._refresh_names()
        n = self.sim.N
        m = np.zeros(n)
        r = np.zeros(n)
        xyz = np.zeros(3 * n)
        vxyz = np.zeros(3 * n)
        if n:
            self.sim.serialize_particle_data(m=m, r=r, xyz=xyz, vxvyvz=vxyz)
            for i, name in enumerate(self._names):
                if r[i] == 0:
                    r[i] = self.meta[name].get('volume_radius',0.)
        return {
            "n": n,
            "names": self._names,
            "m": m,
            "r": r,
            "xyz": xyz.reshape(n, 3),
            "v": vxyz.reshape(n, 3),
        }

    # ---------------------------------------------------------- integration
    def advance(self, real_dt: float, deadline: float):
        """Advance simulation time by speed * real_dt, within a wall-clock budget."""
        sim = self.sim
        for p in sim.particles:
            self.rotation(p)
        requested = 0.0 if self.paused else self.speed * real_dt
        t_start = sim.t
        if self.paused:
            self._target_t = sim.t
        else:
            self._target_t = max(self._target_t, sim.t - 10 * self.speed) + requested
            max_debt = max(self.speed * 0.25, 1e-3)
            if self._target_t - sim.t > max_debt:
                self._target_t = sim.t + max_debt   # we are behind: drop the debt
            stepped = False
            self._repartition()
            while sim.t < self._target_t:
                if time.perf_counter() > deadline:
                    break
                if sim.N == 0 and not self.shells:
                    sim.t = self._target_t
                    break
                try:
                    # An adaptive step may span several display ticks. Stop at
                    # this tick's target instead of publishing a future state
                    # followed by repeated frozen states while time catches up.
                    if any(md.get('tide') for md in self.meta.values()):
                        self._advance_tides(self._target_t-sim.t,deadline)
                    elif self.shells:
                        self._advance_shells(self._target_t-sim.t)
                    else:
                        step(sim, self._target_t - sim.t, self._contact_guard)
                except (ValueError,ArithmeticError) as exc:
                    if self.shells:
                        self.shell_error_history['refused_steps'] += 1
                        self.shell_error_history['last_refusal'] = str(exc)[:300]
                    self.paused = True
                    self.notice(f'Physics paused: {exc}')
                    self._shell_integrator = None
                    self._tide_integrator = None
                    break
                except rebound.NoParticles:
                    sim.t = self._target_t
                    break
                except Exception:  # never let one bad step kill the server
                    traceback.print_exc()
                    break
                stepped = True
                for i, radius in self._contact_guard.sinks:
                    hole = sim.particles[i]
                    for j in self._contact_guard.collisionless:
                        parcel = sim.particles[j]
                        if math.dist(hole.xyz, parcel.xyz) <= radius and not any(
                                {r['s'], r['r']} == {hole.name, parcel.name} for r in self._pending):
                            self._pending.append(self._collision_record(hole, parcel)[2])
                if self._pending:
                    self._process_collisions()
                    self._repartition()
                    if self.paused:
                        self._target_t = sim.t
                        break
                # Tides are checked every step so fast fly-bys are never missed.
                self._tidal_check()
                self._repartition()
                if self.paused:
                    self._target_t = sim.t
                    break
            if stepped:
                self.version += 1
        dt_sim = sim.t - t_start
        if dt_sim > 0:
            self._post_tick(dt_sim)
        # Smoothed achieved/requested speed (about a one second window).
        a = min(1.0, real_dt / 1.0)
        self._ema_req += a * (requested - self._ema_req)
        self._ema_got += a * (dt_sim - self._ema_got)
        if self.paused or self._ema_req <= 1e-9:
            self.perf = 1.0
        else:
            self.perf = max(0.0, min(1.0, self._ema_got / self._ema_req))

    def _advance_shells(self,maximum):
        if self._shell_integrator is None:
            self._shell_integrator = ShellIntegrator(self.sim,self.shells,self.settings['epsilon'])
        masses = [p.m*units.MASS_KG for p in self.sim.particles]
        positions = [tuple(x*units.LENGTH_M for x in p.xyz) for p in self.sim.particles]
        energy_before = self.sim.energy()*units.MASS_KG*units.VELOCITY_M_S**2+shell_energy(self.shells,masses,positions)
        self.shells = self._shell_integrator.advance(self.sim,self.shells,maximum,self._contact_guard)
        positions = [tuple(x*units.LENGTH_M for x in p.xyz) for p in self.sim.particles]
        energy_after = self.sim.energy()*units.MASS_KG*units.VELOCITY_M_S**2+shell_energy(self.shells,masses,positions)
        self.shell_numerical_energy_error_j += energy_after-energy_before
        self.shell_error_history['max_omitted_impulse_m_s'] = max(
            self.shell_error_history['max_omitted_impulse_m_s'],
            max(s.omitted_impulse_m_s for s in self.shells))
        for i,j in approaching_contacts(self.sim):
            self._resolve_collision(ctypes.pointer(self.sim), type('Contact',(),dict(p1=i,p2=j))())

    def _advance_tides(self,maximum,deadline=math.inf):
        if self.shells:
            raise ValueError('Equilibrium tides with unresolved ejecta are outside the supported model')
        profiles = self.tidal_profiles()
        key = tuple((i,t.k2,t.lag_s,self.sim.particles[i].m,self.sim.particles[i].r) for i,t,_ in profiles)
        if self._tide_integrator is None or key != self._tide_integrator.key:
            self._tide_integrator = TidalIntegrator(self.sim,profiles,self.settings['epsilon'],self.settings['tidal_phase'])
            self._tide_integrator.key = key
        solver = self._tide_integrator
        poses = [self.rotation(self.sim.particles[i])[0].at(self.sim.t*units.TIME_S) for i,_,_ in profiles]
        old_omega = np.array([omega for _,_,omega in profiles])
        solver.omegas = old_omega.copy()
        start = self.sim.t*units.TIME_S
        solver.advance(self.sim,maximum,self._contact_guard,deadline)
        for k,(i,material,_) in enumerate(profiles):
            p = self.sim.particles[i]
            md = self.meta[p.name]
            inertia = .4*p.m*units.MASS_KG*(p.r*units.LENGTH_M)**2
            inventory = md['inventory']
            md['inventory'] = BodyInventory(tuple(inertia*solver.omegas[k]),inventory.internal_energy_j+solver.heating[k])
            md['tide'] = replace(material,heat_j=material.heat_j+float(solver.heating[k]))
            pose = Rotation(poses[k],start,tuple((old_omega[k]+solver.omegas[k])*.5)).at(self.sim.t*units.TIME_S)
            md['rotation'] = Rotation(pose,self.sim.t*units.TIME_S,
                                      angular_velocity(md['inventory'].spin_kg_m2_s,p.m*units.MASS_KG,p.r*units.LENGTH_M))
        for i,j in approaching_contacts(self.sim):
            self._resolve_collision(ctypes.pointer(self.sim),type('Contact',(),dict(p1=i,p2=j))())

    def _post_tick(self, dt_sim: float):
        cool = math.exp(-dt_sim / HEAT_COOLING_TIME)
        for meta in self.meta.values():
            if meta["heat"] > 1e-3:
                meta["heat"] *= cool
            else:
                meta["heat"] = 0.0
        if self.settings['collisions'] in ('isolated_mergers', 'isolated_impacts') or self.paused:
            return  # No unaccounted automatic removals or stellar transformations.
        self._cull_escapers()
        while self._supernova_queue:
            before = self.physical_loss_ledger.capture(self)
            self.supernova(self._supernova_queue.pop(), natural=True)
            self.physical_loss_ledger.record('natural_supernova',before,self.physical_loss_ledger.capture(self))

    def _cull_escapers(self):
        boundary = self.settings['escape_distance']
        if boundary is None:
            return
        snap = self.snapshot()
        if snap["n"] == 0 and not self.shells:
            return
        d2 = np.einsum("ij,ij->i", snap["xyz"], snap["xyz"])
        far = np.nonzero(d2 > boundary ** 2)[0]
        shell_far = tuple(s for s in self.shells if s.radius_m-math.dist(s.centre_m,(0,0,0)) > boundary*units.LENGTH_M)
        physical_before = self.physical_loss_ledger.capture(self) if len(far) or shell_far else None
        before = self.ledger.capture(self) if self.ledger is not None and (len(far) or shell_far) else None
        energy = None
        if len(far) or shell_far:
            try:
                energy = totals(self)['energy']
            except ValueError:
                self.removed['energy_defined'] = False
        if len(far):
            mass, pos, vel = snap['m'][far], snap['xyz'][far], snap['v'][far]
            self.removed['bodies'] += len(far)
            self.removed['mass'] += float(mass.sum())
            for key, vectors in (('momentum', vel), ('angular_momentum', np.cross(pos, vel))):
                self.removed[key] = (np.asarray(self.removed[key]) + (mass[:, None] * vectors).sum(axis=0)).tolist()
        if shell_far:
            for shell in shell_far:
                self.removed['bodies'] += shell.fragment_count
                self.removed['mass'] += shell.mass_kg/units.MASS_KG
                p = shell.mass_kg*np.array(shell.velocity_m_s)
                self.removed['momentum'] = (np.array(self.removed['momentum'])+p/(units.MASS_KG*units.VELOCITY_M_S)).tolist()
                self.removed['angular_momentum'] = (np.array(self.removed['angular_momentum'])+
                    np.cross(shell.centre_m,p)/(units.MASS_KG*units.LENGTH_M*units.VELOCITY_M_S)).tolist()
        for i in sorted(far, reverse=True):
            self.remove_body(int(snap["names"][i]))
        if shell_far:
            removed_ids = {s.identifier for s in shell_far}
            self.shells = tuple(s for s in self.shells if s.identifier not in removed_ids)
            self._shell_integrator = None
        if energy is not None:
            self.removed['energy'] += energy - totals(self)['energy']
        if before is not None:
            self.ledger.record('escape_boundary', before, self.ledger.capture(self))
        if len(far) or shell_far:
            self.physical_loss_ledger.record('escape_boundary',physical_before,self.physical_loss_ledger.capture(self))

    # ------------------------------------------------------------ collisions
    def _collision_record(self, pi, pj):
        for p in (pi,pj):
            if self.meta.get(p.name,{}).get('type') in (ROCKY,ASTEROID):
                self.rotation(p)
        ni, nj = pi.name, pj.name
        ti = self.meta.get(ni, {}).get("type", ASTEROID)
        tj = self.meta.get(nj, {}).get("type", ASTEROID)
        if ti == BLACK_HOLE and tj != BLACK_HOLE:
            keep_i = True
        elif tj == BLACK_HOLE and ti != BLACK_HOLE:
            keep_i = False
        else:
            keep_i = pi.m >= pj.m
        s, r = (pi, pj) if keep_i else (pj, pi)
        ts, tr = (ti, tj) if keep_i else (tj, ti)
        ms, mr = s.m, r.m
        rec = {
            "s": s.name, "r": r.name, "ts": ts, "tr": tr,
            "impact": capture_impact(s, r, self.sim.G),
            "spheres": tuple(capture_sphere(p, self.meta.get(p.name, {}).get('inventory'), self.units,
                                            radius_m=self.body_radius(p)*units.LENGTH_M)
                             for p in (s, r)),
            "ms": ms, "mr": mr, "rs": s.r, "rr": r.r,
            "vrel": (r.vx - s.vx, r.vy - s.vy, r.vz - s.vz),
            "normal": _unit((r.x - s.x, r.y - s.y, r.z - s.z)),
            "heat_r": self.meta.get(r.name, {}).get("heat", 0.0),
        }
        return s, r, rec

    def _merge_heuristic(self, s, r):
        ms, mr = s.m, r.m
        M = ms + mr
        # The heuristic does not close spin/internal-energy budgets. Mark
        # the survivor before another callback can capture it this step.
        if s.name in self.meta:
            self.meta[s.name]['inventory'] = None
            if self.meta[s.name]['type'] in (ASTEROID, PLASMA) and self.meta.get(r.name, {}).get('tidal_sample', False):
                self.meta[s.name]['tidal_sample'] = True
        if M > 0:
            inv = 1.0 / M
            s.x = (ms * s.x + mr * r.x) * inv
            s.y = (ms * s.y + mr * r.y) * inv
            s.z = (ms * s.z + mr * r.z) * inv
            s.vx = (ms * s.vx + mr * r.vx) * inv
            s.vy = (ms * s.vy + mr * r.vy) * inv
            s.vz = (ms * s.vz + mr * r.vz) * inv
            s.m = M
            if self.meta.get(s.name, {}).get('tidal_sample', False):
                # Retain the parcel's density/volume scale when it gains mass.
                if s.r == 0:
                    self.meta[s.name]['volume_radius'] *= (M/ms)**(1/3)
                else:
                    s.r *= (M / ms)**(1 / 3)

    def _resolve_collision(self, sim_ptr, collision):
        """Called by REBOUND (from C) when two bodies overlap.

        Heuristic mode merges here and defers fragmentation. Calibrated
        mode only records the encounter; validation and mutation both happen
        after the step. No particles are added inside the native callback.
        """
        try:
            sim = sim_ptr.contents
            ps = sim.particles
            i, j = int(collision.p1), int(collision.p2)
            if i == j:
                return 0
            pi, pj = ps[i], ps[j]
            s, r, rec = self._collision_record(pi, pj)
            keep_i = s.name == pi.name
            if self.settings['collisions'] != 'heuristic':
                # REBOUND may report both pair orders. Keep distinct contacts
                # so simultaneous encounters can be rejected before mutation.
                if not any({p['s'], p['r']} == {s.name, r.name} for p in self._pending):
                    self._pending.append(rec)
                return 0
            self._merge_heuristic(s, r)
            self._pending.append(rec)
            self._names_dirty = True
            self._partition_dirty = True
            return 2 if keep_i else 1  # tell REBOUND which particle to delete
        except Exception:
            traceback.print_exc()
            return 0

    def _merge_deferred_contacts(self, pending):
        """Replay heuristic contact components without stale native references."""
        aliases = {name: name for rec in pending for name in (rec['s'], rec['r'])}
        merged = []
        for old in pending:
            a, b = aliases[old['s']], aliases[old['r']]
            if a == b:
                continue
            s, r, rec = self._collision_record(self.particle(a), self.particle(b))
            if self._absorb_parcel(s, r, rec):
                rec['absorbed_sample'] = True
            else:
                self._merge_heuristic(s, r)
            aliases = {name: rec['s'] if survivor == rec['r'] else survivor
                       for name, survivor in aliases.items()}
            self.remove_body(int(rec['r']))
            merged.append(rec)
        return merged

    def _absorb_parcel(self, s, r, rec):
        if not (rec['ts'] == BLACK_HOLE and rec['tr'] == PLASMA and self.meta[r.name].get('tidal_sample', False)
                and all(state is not None for state in rec['spheres'])):
            return False
        sources, gas_sources = [], []
        for p in self.sim.particles:
            if p.name not in (s.name,r.name):
                group = gas_sources if self.meta[p.name]['type'] == PLASMA and self.meta[p.name].get('tidal_sample',False) else sources
                group.append(GravitySource(p.m*units.MASS_KG,self.body_radius(p)*units.LENGTH_M,
                                           tuple(x*units.LENGTH_M for x in p.xyz)))
        state, angular, energy = absorb_point_sample(*rec['spheres'], self.radius_for(BLACK_HOLE, s.m+r.m)*units.LENGTH_M,
                                                    sources, ballistic_sources=gas_sources)
        flow = self.accretion_flows.get(s.name, dict(mass_kg=0., energy_j=0., angular_momentum_kg_m2_s=[0., 0., 0.]))
        self.accretion_flows[s.name] = dict(mass_kg=flow['mass_kg'] + rec['spheres'][1].mass_kg,
                                          energy_j=flow['energy_j'] + energy,
                                          angular_momentum_kg_m2_s=np.add(flow['angular_momentum_kg_m2_s'], angular).tolist())
        s.m, s.r = state.mass_kg/units.MASS_KG, state.radius_m/units.LENGTH_M
        s.xyz = tuple(x/units.LENGTH_M for x in state.position_m)
        s.vxyz = tuple(x/units.VELOCITY_M_S for x in state.velocity_m_s)
        self.meta[s.name]['inventory'] = BodyInventory(state.spin_kg_m2_s, state.internal_energy_j)
        self._event(EV_SWALLOW, s.xyz, 1., max(rec['rr'], s.r), int(s.name), int(r.name))
        return True

    def _process_collisions(self):
        pending, self._pending = self._pending, []
        mode = self.settings['collisions']
        kinds = (ROCKY,) if self.settings['impact_material'] == 'fluid_planets' else (ROCKY,ASTEROID)
        calibrated = mode in ('isolated_mergers', 'isolated_impacts') or (
            mode == 'auto' and any(r['ts'] in kinds and r['tr'] in kinds for r in pending))
        if calibrated and len(pending) > 1:
            self.paused = True
            self.notice('Collision paused: simultaneous contacts require a collective impact model')
            return
        physical_before = self.physical_loss_ledger.capture(self) if not calibrated else None
        if mode == 'auto' and not calibrated:
            try:
                pending = self._merge_deferred_contacts(pending)
            except (ValueError, ArithmeticError) as exc:
                self.paused = True
                self.notice(f'Capture paused: {exc}')
                return
        for rec in pending:
            try:
                if calibrated:
                    self._apply_isolated_collision(rec)
                else:
                    self._handle_collision(rec)
            except Exception as exc:
                if calibrated:
                    self.paused = True
                    self.notice(f'Collision paused: {exc}')
                    break
                traceback.print_exc()
        self.sim.did_modify_particles = 1
        if not calibrated:
            self.physical_loss_ledger.record('heuristic_collision',physical_before,self.physical_loss_ledger.capture(self))

    def _apply_isolated_collision(self, rec):
        """Preflight a two-body outcome before committing any particle changes."""
        if self.units != units.SYSTEM or not math.isclose(self.sim.G, units.G, rel_tol=1e-12):
            raise ValueError('Calibrated collisions require physical units and Newtonian G')
        if self.settings['gravity'] != 'full':
            raise ValueError('Calibrated impacts require full gravity; disable the tracer approximation')
        material = self.settings['impact_material']
        kinds = (ROCKY,) if material == 'fluid_planets' else (ROCKY,ASTEROID)
        if rec['ts'] not in kinds or rec['tr'] not in kinds:
            raise ValueError('Body types are outside the selected solid-impact calibration')
        if any(s is None for s in rec['spheres']):
            raise ValueError('Both bodies need known spin and internal-energy inventories')
        outcome = construct_collision(*rec['spheres'], material=material, body_types=(rec['ts'],rec['tr']),
                                      resolved_policy=self.settings['collisions'] != 'isolated_mergers',
                                      allow_gentle_contacts=self.settings['collisions'] == 'auto')
        compact = self.sim.N-2+len(outcome.remnants) > self.max_bodies
        if compact and (not outcome.central_shell or len(self.shells) >= MAX_SHELLS):
            raise ValueError('Insufficient body or supported reservoir capacity; no material was removed')
        if self.particle(rec['s']) is None or self.particle(rec['r']) is None or rec['s'] == rec['r']:
            raise ValueError('Collision body IDs no longer identify an incoming pair')
        external = tuple(GravitySource(p.m * units.MASS_KG, p.r * units.LENGTH_M,
                                       tuple(x * units.LENGTH_M for x in p.xyz))
                         for p in self.sim.particles if p.name not in (rec['s'], rec['r']))
        for old in self.shells:
            if not all(math.dist(s.position_m,old.centre_m)+s.radius_m < old.radius_m-old.fragment_radius_m
                       for s in (*rec['spheres'],*outcome.remnants)):
                external += (GravitySource(old.mass_kg,old.radius_m+old.fragment_radius_m,old.centre_m),)
        outcome = couple_collision(rec['spheres'],outcome,external,material=material,
                                   body_types=(rec['ts'],rec['tr']),allow_gentle_contacts=self.settings['collisions']=='auto')
        remnants = outcome.remnants
        shell = None
        if compact:
            identifier = self._next_shell_id
            shell = replace(form_shell(remnants[0],remnants[1:],identifier),formed_at_s=self.sim.t*units.TIME_S,
                            regime=outcome.classification.regime)
            masses = [remnants[0].mass_kg]+[s.mass_kg for s in external]
            positions = [remnants[0].position_m]+[s.position_m for s in external]
            radii = [remnants[0].radius_m]+[s.radius_m for s in external]
            model_defect(shell,masses,positions,radii)
            correction = math.fsum(-units.G_SI*s.mass_kg*p.mass_kg/math.dist(s.position_m,p.position_m)
                                   for s in remnants[1:] for p in external)
            from debris_shell import shell_potential
            correction -= math.fsum(shell_potential(shell,s.mass_kg,s.position_m) for s in external)
            shell = replace(shell,potential_offset_j=correction)
            shell_energy((*self.shells,shell),masses,positions)
            remnants = remnants[:1]
        prepared = [(s.mass_kg / units.MASS_KG, s.radius_m / units.LENGTH_M,
                     tuple(x / units.LENGTH_M for x in s.position_m),
                     tuple(v / units.VELOCITY_M_S for v in s.velocity_m_s),
                     BodyInventory(s.spin_kg_m2_s, s.internal_energy_j)) for s in remnants]
        sm = self.meta[rec['s']]
        heat = max(.5, sm['heat'], self.meta[rec['r']]['heat'])
        names = [rec['s'], rec['r']]
        output_type = ROCKY if material == 'fluid_planets' else ASTEROID
        if len(prepared) == 1:
            self.remove_body(int(rec['r']))
            names.pop()
        for mass, _radius, position, velocity, inventory in prepared[2:]:
            names.append(str(self.add_body(output_type, mass, position, velocity, heat=heat, inventory=inventory)))
        for name, (mass, radius, position, velocity, inventory) in zip(names, prepared, strict=True):
            particle = self.particle(name)
            particle.m, particle.r = mass, radius
            particle.xyz, particle.vxyz = position, velocity
            self.meta[name]['inventory'], self.meta[name]['heat'] = inventory, heat
            self.meta[name]['type'] = output_type
            self.rotation(particle)
        self._partition_dirty = True
        # Keep the constructed volume/density and spin; heuristic promotion would
        # overwrite the radius and invalidate the conserved inventory.
        total = sum(s.mass_kg for s in rec['spheres'])
        center = tuple(sum(s.mass_kg * s.position_m[i] for s in rec['spheres']) / total / units.LENGTH_M for i in range(3))
        kind = {'hit_and_run':EV_HIT_AND_RUN,'gentle_rebound':EV_HIT_AND_RUN,'contact_rebound':EV_HIT_AND_RUN,'partial_accretion':EV_ACCRETION,'erosion':EV_EROSION}.get(
            outcome.classification.regime,EV_MERGE if len(outcome.remnants)==1 else EV_SHATTER)
        if shell is not None:
            self.shells = (*self.shells,shell)
            self._next_shell_id += 1
        if outcome.central_shell:
            self.sim.integrator = 'bs'
            self._set_solver_tolerance()
        impact = outcome.contact
        relative = np.subtract(impact[1].velocity_m_s, impact[0].velocity_m_s)
        separation = np.subtract(impact[1].position_m, impact[0].position_m)
        b = min(1.,np.linalg.norm(np.cross(separation,relative))/(np.linalg.norm(separation)*np.linalg.norm(relative)))
        self.last_impact = dict(regime=outcome.classification.regime, speed_m_s=float(np.linalg.norm(relative)),
                                survivor_id=int(rec['s']),
                                angle_deg=math.degrees(math.asin(b)),
                                remnant_masses_kg=[s.mass_kg for s in outcome.remnants],
                                unresolved_fragments=0 if shell is None else shell.fragment_count)
        self._event(kind, center, 1.0,
                    rec['rs'] + rec['rr'], int(rec['s']), int(rec['r']))

    def _handle_collision(self, rec):
        if rec.get('absorbed_sample', False):
            return
        self.meta.pop(rec["r"], None)
        p = self.particle(rec["s"])
        sm = self.meta.get(rec["s"])
        if p is None or sm is None:
            return  # the survivor was itself swallowed later in the same step
        sm['inventory'] = None
        ts, tr = rec["ts"], rec["tr"]
        sid, rid = int(rec["s"]), int(rec["r"])
        pos = (p.x, p.y, p.z)
        ms, mr = rec["ms"], rec["mr"]
        vimp = _norm(rec["vrel"])

        # 1) Black holes swallow everything that crosses the event horizon.
        if ts == BLACK_HOLE:
            if tr == BLACK_HOLE:
                # About 5% of the total mass leaves as gravitational waves.
                before = self.ledger.capture(self) if self.ledger is not None else None
                p.m *= 0.95
                p.r = self.radius_for(BLACK_HOLE, p.m)
                if before is not None:
                    self.ledger.record('prescribed_black_hole_mass_loss', before, self.ledger.capture(self))
                self._event(EV_BH_MERGER, pos, 3.0, p.r * 30, sid, rid)
            else:
                p.r = self.radius_for(BLACK_HOLE, p.m)
                mag = 0.5 + min(1.5, math.log10(1.0 + 1e4 * mr / max(ms, 1e-9)) / 3.0)
                self._event(EV_SWALLOW, pos, mag, max(rec["rr"] * 3, p.r * 2), sid, rid)
            return

        # 2) Two neutron stars: a kilonova.
        if ts == NEUTRON_STAR and tr == NEUTRON_STAR:
            self._kilonova(p, rec)
            return

        # 3) Everything else: merge or shatter, depending on impact energy.
        frag_type = ASTEROID
        if ts == GAS_GIANT and tr == GAS_GIANT:
            frag_type = PLASMA
        if ts in (STAR, NEUTRON_STAR):
            # Stars engulf what hits them; their escape speed is enormous.
            shattered = False
            if tr == STAR:
                shattered = self._try_shatter(p, rec, PLASMA)
            if not shattered:
                p.r = self.radius_for(ts, p.m)
                kind = EV_MERGE if tr == STAR else EV_SWALLOW
                self._event(kind, pos, 1.2 if tr == STAR else 0.7,
                            max(rec["rr"] * 3, 2.0), sid, rid)
                if tr in (ROCKY, GAS_GIANT, ASTEROID):
                    sm["heat"] = min(1.0, sm["heat"] + 0.2)
            self._promote(rec["s"], self.particle(rec["s"]))
            return

        # Gas clouds simply coalesce; solid bodies can shatter.
        if PLASMA not in (ts, tr) and self._try_shatter(p, rec, frag_type):
            self._promote(rec["s"], self.particle(rec["s"]))
            return

        # Plain merger: a hot, molten survivor.
        p.r = self.radius_for(ts, p.m)
        r_sum = rec["rs"] + rec["rr"]
        vesc = math.sqrt(2 * G * (ms + mr) / max(r_sum, 1e-6))
        ratio = vimp / max(vesc, 1e-9)
        sm["heat"] = min(1.0, max(sm["heat"], rec["heat_r"]) + 0.25 + 0.5 * min(1.0, ratio)
                         * min(1.0, 3.0 * mr / max(ms, 1e-12)))
        self._event(EV_MERGE, pos, min(1.5, 0.15 + 0.5 * ratio * min(1.0, 3 * mr / ms)),
                    max(r_sum, 0.3), sid, rid)
        self._promote(rec["s"], self.particle(rec["s"]))

    def _try_shatter(self, p, rec, frag_type) -> bool:
        """Disruption heuristic inspired by Leinhardt & Stewart (2012).

        Q_R  = specific impact energy (reduced-mass kinetic energy / total mass)
        Q*   = energy needed to disperse half the mass  (~ escape speed^2)
        M_lr = mass of the largest remnant = M_tot * (1 - Q_R / (2 Q*))
        Returns True if the bodies shattered.
        """
        ms, mr = rec["ms"], rec["mr"]
        M = ms + mr
        if mr <= 0 or M <= 0:
            return False
        mu = ms * mr / M
        vimp = _norm(rec["vrel"])
        r_sum = rec["rs"] + rec["rr"]
        vesc = math.sqrt(2 * G * M / max(r_sum, 1e-6))
        q_r = 0.5 * mu * vimp * vimp / M
        # Small projectiles couple their energy poorly, so the target is much
        # harder to disrupt (L&S 2012 mass-ratio correction, mu_bar = 0.36).
        gamma = min(ms, mr) / max(ms, mr)
        q_star = 0.6 * vesc * vesc * ((1 + gamma) ** 2 / (4 * gamma)) ** 0.85
        ratio = q_r / max(q_star, 1e-12)
        lr_frac = min(1.0, max(0.04, 1.0 - 0.5 * ratio))
        if vimp < 1.25 * vesc or lr_frac > 0.93 or M < SHATTER_MIN_MASS:
            return False
        # Earlier callbacks in the same step may have merged more mass.
        M = p.m
        m_ej = M * (1.0 - lr_frac)
        n = int(round(4 + 12 * (1.0 - lr_frac)))
        # Fewer fragments in crowded scenes keeps the simulation real-time.
        n_max = 16 if self.sim.N < 200 else (8 if self.sim.N < 400 else 4)
        room = max(0, self.capacity - 50)
        n = max(0, min(n_max, n, room, int(m_ej / MIN_FRAGMENT_MASS)))
        if n < 2:
            return False

        # Fragment masses follow a rough power law (a few big ones, many small).
        w = [self.rng.random() ** 1.6 + 0.05 for _ in range(n)]
        sw = sum(w)
        masses = [m_ej * x / sw for x in w]
        m_lr = M - m_ej
        ts = rec["ts"]
        r_lr = self.radius_for(ts, m_lr)
        v_esc_lr = math.sqrt(2 * G * m_lr / max(r_lr, 1e-6))
        normal = rec["normal"]
        vdir = _unit(rec["vrel"], normal)
        severity = min(1.0, ratio / 2.0)

        x_cm = (p.x, p.y, p.z)
        v_cm = (p.vx, p.vy, p.vz)
        frags = []
        for mf in masses:
            d = _unit(_add(self._rand_unit(), _add(_mul(normal, 0.8), _mul(vdir, 0.5))))
            speed = v_esc_lr * (1.0 + 0.4 * self.rng.random()) + vimp * self.rng.uniform(0.1, 0.45) * severity
            rf = self.radius_for(frag_type, mf)
            off = _mul(d, r_lr + rf * 1.5 + self.rng.uniform(0.0, 2.0) * rf)
            frags.append([mf, off, _mul(d, speed), rf])
        # Zero the fragments' net momentum so total momentum is conserved
        # exactly. (REBOUND ignores overlapping bodies that are moving apart,
        # so fragments may start close to the remnant without re-merging.)
        pf = (0.0, 0.0, 0.0)
        for f in frags:
            pf = _add(pf, _mul(f[2], f[0]))
        u_mean = _mul(pf, 1.0 / m_ej)
        p.m = m_lr
        p.r = r_lr
        heat_new = 1.0
        sm = self.meta.get(rec["s"])
        if sm is not None:
            sm["heat"] = 1.0
        for mf, off, u, _rf in frags:
            pos = _add(x_cm, off)
            vel = _add(v_cm, _sub(u, u_mean))
            self.add_body(self._promoted_type(frag_type, mf), mf, pos, vel, heat=heat_new, inventory=None)
        contact = _add(x_cm, _mul(normal, r_lr))
        self._event(EV_SHATTER, contact, 1.0 + min(2.0, ratio / 2.0), r_sum * 1.5,
                    int(rec["s"]), int(rec["r"]))
        return True

    def _kilonova(self, p, rec):
        M = p.m
        pos = (p.x, p.y, p.z)
        n = min(12, self.capacity)
        if n >= 4:
            m_ej = 0.03 * M
            p.m = M - m_ej
            vesc = math.sqrt(2 * G * M / max(rec["rs"] + rec["rr"], 1e-6))
            vel0 = (p.vx, p.vy, p.vz)
            dirs = self._sphere_dirs(n)
            for d in dirs:
                mf = m_ej / n
                rf = self.radius_for(PLASMA, mf)
                self.add_body(PLASMA, mf, _add(pos, _mul(d, 2.0 + rf * 2)),
                              _add(vel0, _mul(d, 0.6 * vesc * self.rng.uniform(0.8, 1.2))), heat=1.0, inventory=None)
        # Adding ejecta can reallocate REBOUND's particle array.
        p = self.particle(rec["s"])
        p.r = self.radius_for(NEUTRON_STAR, p.m)
        self._event(EV_KILONOVA, pos, 2.5, 20.0, int(rec["s"]), int(rec["r"]))
        self._promote(rec["s"], self.particle(rec["s"]))

    # -------------------------------------------------------------- promotion
    @staticmethod
    def _promoted_type(btype, m):
        if btype == ASTEROID and m >= ASTEROID_TO_ROCKY:
            btype = ROCKY
        if btype == ROCKY and m >= ROCKY_TO_GAS:
            btype = GAS_GIANT
        if btype == GAS_GIANT and m >= GAS_TO_STAR:
            btype = STAR
        if btype == NEUTRON_STAR and m >= NEUTRON_TO_BH:
            btype = BLACK_HOLE
        return btype

    def _promote(self, name, p):
        meta = self.meta.get(name)
        if meta is None:
            return
        old = meta["type"]
        if meta.get('tidal_sample', False):
            # No fragment reassembly law: retain its material/radius instead
            # of promoting it back into the same tidal breakup repeatedly.
            self._partition_dirty = True
            return
        new = self._promoted_type(old, p.m)
        radius = self.radius_for(new, p.m)
        if new != old or radius != p.r:
            meta['inventory'] = None
        if new != old:
            meta["type"] = new
            pos = (p.x, p.y, p.z)
            if new == STAR:
                self._event(EV_IGNITION, pos, 1.5, self.radius_for(STAR, p.m) * 4, int(name))
            elif new == BLACK_HOLE:
                self._event(EV_COLLAPSE, pos, 2.5, 30.0, int(name))
        p.r = radius
        self._partition_dirty = True
        if meta["type"] == STAR and p.m >= STAR_COLLAPSE:
            self._supernova_queue.append(int(name))
        self.version += 1

    # ------------------------------------------------------------- supernova
    def supernova(self, bid, natural=False) -> bool:
        if self.settings['collisions'] in ('isolated_mergers', 'isolated_impacts'):
            self.notice('Supernovae are disabled in isolated collision experiments.')
            return False
        name = str(int(bid))
        p = self.particle(name)
        meta = self.meta.get(name)
        if p is None or meta is None or meta["type"] != STAR:
            return False
        n = min(48, self.capacity)
        if n < 8:
            self.notice("Too many bodies for a supernova - clear some debris first.")
            return False
        M = p.m
        r = p.r
        pos = (p.x, p.y, p.z)
        vel = (p.vx, p.vy, p.vz)
        m_rem = 0.25 * M
        rem_type = BLACK_HOLE if (natural or m_rem >= NEUTRON_TO_BH) else NEUTRON_STAR
        m_ej = M - m_rem
        vesc = math.sqrt(2 * G * M / max(r, 1e-6))
        v_base = max(2.5 * vesc, 30.0)
        dirs = self._sphere_dirs(n)
        w = [self.rng.uniform(0.75, 1.25) for _ in range(n)]
        sw = sum(w)
        ej = []
        for d, wi in zip(dirs, w, strict=True):
            mf = m_ej * wi / sw
            ej.append((mf, d, v_base * self.rng.uniform(0.75, 1.25)))
        pf = (0.0, 0.0, 0.0)
        for mf, d, s in ej:
            pf = _add(pf, _mul(d, mf * s))
        u_mean = _mul(pf, 1.0 / m_ej)
        p.m = m_rem
        meta['inventory'] = None
        meta["type"] = rem_type
        self._partition_dirty = True
        meta["heat"] = 1.0
        p.r = self.radius_for(rem_type, m_rem)
        for mf, d, s in ej:
            rf = self.radius_for(PLASMA, mf)
            self.add_body(PLASMA, mf, _add(pos, _mul(d, r * 1.2 + rf * 1.5)),
                          _add(vel, _sub(_mul(d, s), u_mean)), heat=1.0, inventory=None)
        self._event(EV_SUPERNOVA, pos, 3.0, max(40.0, r * 12), int(name), 1 if rem_type == BLACK_HOLE else 0)
        if M < 8000 and not natural:
            self.notice("Fun fact: real stars need at least ~8 Suns of mass to explode like this.")
        self.version += 1
        return True

    # ------------------------------------------------------- tidal disruption
    def _tidal_check(self):
        if self.settings['collisions'] in ('isolated_mergers', 'isolated_impacts'):
            return
        if self.sim.N < 2:
            return
        if self._tidal_pairs is None or self._partition_dirty:
            # Masses, radii, types and array order stay fixed between body
            # edits. Repartitioning invalidates these pairs after every edit;
            # direct checks before repartitioning also rebuild the cache.
            snap = self.snapshot()
            types = [self.meta.get(nm, {}).get("type", ASTEROID) for nm in snap["names"]]
            heavy = np.array([i for i, kind in enumerate(types) if kind in HEAVY_TYPES], dtype=int)
            victims = np.array([i for i, kind in enumerate(types) if kind in TIDAL_DENSITY], dtype=int)
            m, r = snap["m"], snap["r"]
            # Row-major pair order preserves the first-disruption rule.
            hi, vi = np.nonzero((victims[None, :] != heavy[:, None])
                                & (m[victims][None, :] * 10.0 < m[heavy][:, None])
                                & (m[victims][None, :] >= TIDAL_MIN_MASS))
            h, cand = heavy[hi], victims[vi]
            if self.units == units.LEGACY:
                dens = np.array([TIDAL_DENSITY[types[i]] for i in cand])
                r_t = TIDAL_K * np.cbrt(m[h] / dens)
            else:
                # A single stellar encounter uses the stellar tidal radius;
                # 2.44 is the circular, synchronous fluid Roche coefficient.
                factor = np.array([1.0 if types[i] == STAR else 2.44 for i in cand])
                r_t = factor * r[cand] * np.cbrt(m[h] / m[cand])
            valid = r_t > (r[h] + r[cand]) * 1.05
            self._tidal_pairs = h[valid], cand[valid], r_t[valid] ** 2
            self._tidal_xyz = np.empty(3 * self.sim.N)
        h, cand, radius2 = self._tidal_pairs
        if len(h) == 0:
            return
        self.sim.serialize_particle_data(xyz=self._tidal_xyz)
        xyz = self._tidal_xyz.reshape(-1, 3)
        delta = xyz[cand] - xyz[h]
        hit = np.nonzero(np.einsum('ij,ij->i', delta, delta) < radius2)[0]
        if len(hit):
            first = hit[0]
            self._disrupt(self._names[cand[first]], self._names[h[first]])

    def _disrupt(self, victim_name, heavy_name):
        pv = self.particle(victim_name)
        ph = self.particle(heavy_name)
        vm = self.meta.get(victim_name)
        if pv is None or ph is None or vm is None:
            return
        gas = self.units == units.SYSTEM and vm['type'] in (STAR, GAS_GIANT)
        n = min(56 if gas else 14, self.capacity + 1) // 2 * 2
        if n < 4:
            return
        inventory = vm['inventory']
        if inventory is not None and any(inventory.spin_kg_m2_s):
            self.paused = True
            self.notice('Tidal breakup of a rotating body requires a rotating source model')
            return
        physical_before = self.physical_loss_ledger.capture(self)
        vt = vm["type"]
        frag_type = PLASMA if vt in (STAR, GAS_GIANT) else ASTEROID
        M = pv.m
        rv = pv.r
        pos = (pv.x, pv.y, pv.z)
        vel = (pv.vx, pv.vy, pv.vz)
        hpos = (ph.x, ph.y, ph.z)
        axis = _unit(_sub(pos, hpos))
        perp = _unit(_cross(axis, (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0))
        normal = _cross(axis, perp)
        vid, hid = int(victim_name), int(heavy_name)
        self.remove_body(vid)
        for offset, rf in source_samples(rv, n, point=gas):
            fpos = _add(pos, _add(_mul(axis, offset[0]), _add(_mul(perp, offset[1]), _mul(normal, offset[2]))))
            # Debris stays debris (no promotion), so tides can't shred it again.
            parcel_inventory = None if inventory is None else BodyInventory(internal_energy_j=inventory.internal_energy_j/n)
            bid = self.add_body(frag_type, M/n, fpos, vel, heat=vm['heat'], inventory=parcel_inventory)
            self.particle(str(bid)).r = rf
            self.meta[str(bid)]['tidal_sample'] = True
            if gas:
                self.meta[str(bid)]['volume_radius'] = rf
                self.particle(str(bid)).r = 0
        self._event(EV_TIDAL, pos, 1.6, rv * 4, hid, vid)
        after = self.physical_loss_ledger.capture(self)
        if physical_before is not None and after is not None and all(
                s['energy_j'] is not None for s in (physical_before, after)):
            # Freeze the energy-reference difference when replacing a smooth
            # source with a discrete point Hamiltonian. This is not heat.
            self.tidal_potential_offset_j += physical_before['energy_j'] - after['energy_j']
        self.physical_loss_ledger.record('tidal_disruption',physical_before,self.physical_loss_ledger.capture(self))

    # ------------------------------------------------------------ user tools
    def _dominant(self, pos, snap, exclude=None):
        """Index of the body pulling hardest on `pos` (largest m / d^2)."""
        if snap["n"] == 0 and not self.shells:
            return None
        d = snap["xyz"] - np.asarray(pos)
        d2 = np.einsum("ij,ij->i", d, d) + snap["r"] ** 2
        score = snap["m"] / d2
        for k, name in enumerate(snap['names']):
            if not self.exerts_gravity(name,snap['m'][k]):
                score[k] = 0
        if exclude is not None:
            score[exclude] = -1
        i = int(np.argmax(score))
        return i if score[i] > 0 else None

    def initial_velocity(self, pos, mass, mode, drag, snap, tracer=False):
        """Velocity for a new body plus the attractor index and its velocity kick.

        orbit  - a circular, prograde orbit around the strongest attractor. If
                 the new body is heavier than the attractor, both share the
                 orbit around their common centre of mass.
        launch - the drag vector, scaled so dragging 1/4 of the distance to
                 the attractor gives roughly circular-orbit speed.
        """
        a = self._dominant(pos, snap)
        if a is None:
            if mode == "launch":
                return _mul(drag, 0.05), None, (0.0, 0.0, 0.0)
            return (0.0, 0.0, 0.0), None, (0.0, 0.0, 0.0)
        xa = tuple(snap["xyz"][a])
        va = tuple(snap["v"][a])
        ma = float(snap["m"][a])
        rel = _sub(tuple(pos), xa)
        d = max(_norm(rel), 1e-6)
        v_circ = math.sqrt(G * (ma + (0 if tracer else mass)) / d)
        if d < float(self.contact_radii(snap)[a]):
            return va, a, (0.0, 0.0, 0.0)   # inside the attractor: just match its motion
        if mode == "launch":
            scale = v_circ / (0.25 * d)
            return _add(va, _mul(drag, scale)), a, (0.0, 0.0, 0.0)
        t = _cross((0.0, 1.0, 0.0), rel)
        if _norm(t) < 1e-6 * d:
            t = _cross((1.0, 0.0, 0.0), rel)
        t = _unit(t)
        if mass > ma and not tracer:
            v_new = _add(va, _mul(t, v_circ * ma / (ma + mass)))
            kick = _mul(t, -v_circ * mass / (ma + mass))
            return v_new, a, kick
        return _add(va, _mul(t, v_circ)), a, (0.0, 0.0, 0.0)

    def spawn(self, btype, pos, mode="orbit", drag=(0, 0, 0), mass_mult=1.0):
        if self.sim.N >= self.max_bodies:
            self.notice(f"Body limit reached ({self.max_bodies}). Delete some debris or clear the scene.")
            return None
        mass = DEFAULT_MASS[btype] * mass_mult
        if mass <= 0 or not math.isfinite(mass):
            raise ValueError("mass must be positive and finite")
        snap = self.snapshot()
        separation = snap["xyz"] - np.asarray(pos)
        touching = np.einsum("ij,ij->i", separation, separation) <= (self.contact_radii(snap) + self.radius_for(btype, mass)) ** 2
        if np.any(touching):
            self.notice("Cannot place a body overlapping another body. Move it farther away.")
            return None
        vel, a, kick = self.initial_velocity(pos, mass, mode, drag, snap, tracer=self.is_light(btype, mass))
        if a is not None and _norm(kick) > 0:
            pa = self.sim.particles[a]
            pa.vx += kick[0]
            pa.vy += kick[1]
            pa.vz += kick[2]
        return self.add_body(btype, mass, pos, vel)

    def belt(self, pos, count=60, mass_mult=1.0):
        """A ring of asteroids around whatever dominates `pos` (works for planetary rings too)."""
        snap = self.snapshot()
        a = self._dominant(pos, snap)
        count = min(int(count), self.capacity)
        if count <= 0:
            self.notice("Body limit reached - no room for an asteroid belt.")
            return 0
        mass = DEFAULT_MASS[ASTEROID] * mass_mult
        if a is None:
            for _ in range(count):
                off = _mul(self._rand_unit(), self.rng.uniform(0, 20))
                self.add_body(ASTEROID, mass, _add(pos, off), _mul(self._rand_unit(), 0.05))
            return count
        xa = tuple(snap["xyz"][a])
        va = tuple(snap["v"][a])
        ma = float(snap["m"][a])
        rel = _sub(tuple(pos), xa)
        base_r = max(_norm((rel[0], 0.0, rel[2])), snap["r"][a] * 1.6)
        for _ in range(count):
            rr = base_r * self.rng.uniform(0.92, 1.08)
            th = self.rng.uniform(0, 2 * math.pi)
            y = self.rng.gauss(0, 0.012 * rr)
            p = (xa[0] + rr * math.cos(th), xa[1] + y, xa[2] + rr * math.sin(th))
            v = math.sqrt(G * ma / rr) * self.rng.uniform(0.985, 1.015)
            # prograde tangent = up x radial
            t = (math.sin(th), 0.0, -math.cos(th))
            self.add_body(ASTEROID, mass * self.rng.uniform(0.5, 1.5), p, _add(va, _mul(t, v)))
        return count

    def predict(self, btype, pos, mode, drag, mass_mult, samples=220, wall_budget=0.025):
        """Forecast the path of a body that is about to be placed.

        Builds a small throw-away REBOUND simulation with the most influential
        bodies, adds the new body, integrates forward, and returns its path
        relative to the attractor (so orbits around moving planets read clearly).
        """
        t0 = time.perf_counter()
        mass = DEFAULT_MASS[btype] * mass_mult
        snap = self.snapshot()
        vel, a, kick = self.initial_velocity(pos, mass, mode, drag, snap, tracer=self.is_light(btype, mass))
        if snap["n"] == 0:
            return {"points": [], "hit": False, "attractor": -1, "vel": vel, "radius": self.radius_for(btype, mass)}
        gap = np.linalg.norm(snap["xyz"] - np.asarray(pos), axis=1)
        surfaces = self.contact_radii(snap)
        if np.any(gap <= surfaces + self.radius_for(btype, mass)):
            aid = int(snap["names"][a]) if a is not None else -1
            return {"points": [tuple(pos)], "hit": True, "attractor": aid, "vel": vel, "radius": self.radius_for(btype, mass)}
        d = snap["xyz"] - np.asarray(pos)
        score = snap["m"] / (np.einsum("ij,ij->i", d, d) + snap["r"] ** 2)
        for i, name in enumerate(snap['names']):
            if not self.exerts_gravity(name,snap['m'][i]):
                score[i] = 0
        limit = self.settings['forecast_limit'] or snap['n']
        order = list(np.argsort(-score)[:limit])
        if a is not None and a not in order:
            order.append(a)
        included = set(order)
        omitted_mass = float(sum(snap['m'][i] for i in range(snap['n']) if i not in included
                                 and self.exerts_gravity(snap['names'][i],snap['m'][i])))
        # Match the live force model: active bodies first, then passive tracers.
        # The proposed body also belongs to the correct partition.
        def passive(i):
            return self.is_light(btype, mass) if i == -1 else (
                self.is_ballistic(snap['names'][i]) or not self.exerts_gravity(snap['names'][i],snap['m'][i]))
        order.append(-1)
        order.sort(key=passive)
        mini = rebound.Simulation()
        mini.G = G
        mini.integrator = "ias15"
        mini.integrator = str(self.sim.integrator)
        if str(mini.integrator) == 'bs':
            mini.integrator.eps_rel = self.settings['epsilon']*.01
            mini.integrator.eps_abs = self.settings['epsilon']*.001
        else:
            mini.integrator.min_dt = self.sim.integrator.min_dt
            mini.integrator.epsilon = self.sim.integrator.epsilon
        a_local = None
        r_new = self.radius_for(btype, mass)
        for k, i in enumerate(order):
            if i == -1:
                test = k
                mini.add(m=mass, r=r_new, x=pos[0], y=pos[1], z=pos[2], vx=vel[0], vy=vel[1], vz=vel[2])
                continue
            vx, vy, vz = snap["v"][i]
            if a is not None and i == a:
                vx, vy, vz = vx + kick[0], vy + kick[1], vz + kick[2]
                a_local = k
            x, y, z = snap["xyz"][i]
            mini.add(m=float(snap["m"][i]), r=float(snap["r"][i]),
                     x=float(x), y=float(y), z=float(z), vx=float(vx), vy=float(vy), vz=float(vz))
        mini.N_active = sum(not passive(i) for i in order)
        mini.testparticle_type = 1 if self.settings['gravity'] == 'full' else 0
        gas = frozenset(k for k, i in enumerate(order)
                        if i != -1 and self.is_ballistic(snap['names'][i]))
        sinks = tuple((k, mini.particles[k].r * GAS_SINK_RADII) for k, i in enumerate(order)
                      if i != -1 and self.meta[snap['names'][i]]['type'] == BLACK_HOLE)
        for k in gas:
            mini.particles[k].r = 0
        hit = {"flag": False, "stop": False}

        def on_collision(sim_ptr, c):
            if int(c.p1) == test or int(c.p2) == test:
                hit["flag"] = True
            # Any collision changes the system. Do not integrate background
            # bodies through singular overlaps or invent their future outcome.
            hit["stop"] = True
            sim_ptr.contents.stop()
            return 0

        mini.collision = "direct"
        mini.collision_resolve = on_collision

        # How far ahead to look: one orbit if bound, otherwise a fly-by.
        horizon = 200.0
        if a is not None:
            ma = float(snap["m"][a])
            pa = mini.particles[a_local]
            rel = (pos[0] - pa.x, pos[1] - pa.y, pos[2] - pa.z)
            vrel = (vel[0] - pa.vx, vel[1] - pa.vy, vel[2] - pa.vz)
            dist = max(_norm(rel), 1e-6)
            mu = G * (ma + (0 if self.is_light(btype, mass) else mass))
            energy = 0.5 * _dot(vrel, vrel) - mu / dist
            if energy < 0:
                sma = -mu / (2 * energy)
                horizon = min(2 * math.pi * math.sqrt(sma ** 3 / mu) * 1.02, 6000.0)
            else:
                horizon = min(8.0 * dist / max(_norm(vrel), 1e-6), 6000.0)
        a0 = None
        if a_local is not None:
            pa = mini.particles[a_local]
            a0 = (pa.x, pa.y, pa.z)
        points = [tuple(pos)]
        times = [0.0]
        def append_forecast_state():
            pt = mini.particles[test]
            location = np.array(pt.xyz)
            if a0 is not None:
                location += np.array(a0)-mini.particles[a_local].xyz
            if np.isfinite(location).all():
                points.append(tuple(location))
                times.append(mini.t)
        guard = ContactGuard(collisionless=gas, sinks=sinks)
        forecast_shells = self.shells
        shell_integrator = ShellIntegrator(mini,forecast_shells,self.settings['epsilon']) if forecast_shells else None
        profiles = [(k,self.meta[snap['names'][i]]['tide'],self.rotation(self.particle(snap['names'][i]))[0].omega_rad_s)
                    for k,i in enumerate(order) if i >= 0 and self.meta[snap['names'][i]].get('tide')]
        tidal_integrator = TidalIntegrator(mini,profiles,self.settings['epsilon'],self.settings['tidal_phase']) if profiles else None
        failed = False
        try:
            for k in range(1, samples + 1):
                target = horizon * k / samples
                start = mini.t
                exhausted = False
                while mini.t < target:
                    # integrate(target) can take arbitrarily many native steps
                    # before returning. Yield between steps without relaxing
                    # IAS15's tolerance or minimum timestep.
                    if time.perf_counter() - t0 >= wall_budget:
                        exhausted = True
                        break
                    # Sample at the requested time, never overshoot it and
                    # accidentally integrate backwards to the next sample.
                    previous = mini.t
                    if tidal_integrator is not None:
                        tidal_integrator.advance(mini,target-mini.t,guard,t0+wall_budget)
                        for i,j in approaching_contacts(mini):
                            on_collision(ctypes.pointer(mini),type('Contact',(),dict(p1=i,p2=j))())
                    elif shell_integrator is None:
                        step(mini, target - mini.t, guard)
                    else:
                        forecast_shells = shell_integrator.advance(mini,forecast_shells,target-mini.t,guard)
                        for i,j in approaching_contacts(mini):
                            on_collision(ctypes.pointer(mini),type('Contact',(),dict(p1=i,p2=j))())
                    pt = mini.particles[test]
                    if mini.t <= previous or not all(math.isfinite(value) for value in (mini.t, pt.x, pt.y, pt.z)):
                        raise ArithmeticError("Forecast step did not produce a finite advancing state")
                    if any(math.dist(mini.particles[i].xyz, mini.particles[j].xyz) <= radius
                           for i, radius in sinks for j in gas):
                        hit['stop'] = True
                    if hit["stop"]:
                        break
                if mini.t == start:
                    break
                append_forecast_state()
                if hit["stop"] or exhausted:
                    break
        except Exception:
            failed = True
            if mini.N > test and mini.t > times[-1]:
                append_forecast_state()
        aid = int(snap["names"][a]) if a is not None else -1
        return {"points": points, "hit": hit["flag"], "attractor": aid, "vel": vel, "radius": r_new,
                "times": times, "horizon": horizon, "complete": not failed and not hit['stop'] and mini.t >= horizon,
                "included_bodies": len(order) - 1, "omitted_bodies": snap['n'] - len(order) + 1,
                "omitted_active_mass": omitted_mass}

    # --------------------------------------------------------------- helpers
    def _rand_unit(self):
        z = self.rng.uniform(-1.0, 1.0)
        phi = self.rng.uniform(0.0, 2 * math.pi)
        s = math.sqrt(max(0.0, 1 - z * z))
        return (s * math.cos(phi), z, s * math.sin(phi))

    def _sphere_dirs(self, n):
        """n roughly even directions (Fibonacci sphere), randomly rotated."""
        golden = math.pi * (3 - math.sqrt(5))
        rot = self.rng.uniform(0, 2 * math.pi)
        out = []
        for k in range(n):
            y = 1 - 2 * (k + 0.5) / n
            rad = math.sqrt(max(0.0, 1 - y * y))
            th = golden * k + rot
            out.append((rad * math.cos(th), y, rad * math.sin(th)))
        return out

    # --------------------------------------------------------------- presets
    def orbit(self, center_pos, center_vel, center_mass, radius, phase=0.0, incl=0.0, ecc=0.0):
        """Position/velocity for an orbit around a primary (prograde, counter-clockwise from above).

        For ecc > 0 the body starts at apoapsis = radius.
        """
        c, s = math.cos(phase), math.sin(phase)
        rel = (radius * c, 0.0, radius * s)
        t = (s, 0.0, -c)  # up x radial
        if incl:
            ci, si = math.cos(incl), math.sin(incl)
            rel = (rel[0], rel[2] * si, rel[2] * ci)
            t = (t[0], t[2] * si, t[2] * ci)
        v = math.sqrt(G * center_mass / radius * (1 - ecc))
        return _add(center_pos, rel), _add(center_vel, _mul(t, v))

    def add_satellite(self, parent_id, btype, mass, distance, phase=0.0):
        """Replace a primary's centre-of-mass state with a circular pair."""
        if parent_id is None or self.capacity == 0:
            return None
        parent = self.particle(str(parent_id))
        total = parent.m + mass
        center = (parent.x, parent.y, parent.z)
        velocity = (parent.vx, parent.vy, parent.vz)
        pos, vel = self.orbit(center, velocity, total, distance, phase)
        shift = _mul(_sub(pos, center), mass / total)
        kick = _mul(_sub(vel, velocity), mass / total)
        parent.x, parent.y, parent.z = _sub(center, shift)
        parent.vx, parent.vy, parent.vz = _sub(velocity, kick)
        return self.add_body(btype, mass, _sub(pos, shift), _sub(vel, kick))

    def load_preset(self, name: str) -> dict:
        """Load a named scenario. Returns a camera hint for the client."""
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {name!r}")
        self.clear()
        self.speed = PRESET_SPEEDS[name]
        rng = self.rng
        cam = {"focus": [0, 0, 0], "distance": 400.0, "pitch": 0.6}
        origin = (0.0, 0.0, 0.0)

        if name == "solar":
            sun = 1000.0
            self.add_body(STAR, sun, origin, origin)
            for r_orb, m, ph, days, tilt in ((23.226, .000166, .3, 58.6462, .034),
                                            (43.398, .002448, 2., 243.025, 177.36),
                                            (91.422, .000323, 4.1, 1.025956, 25.19)):
                p, v = self.orbit(origin, origin, sun + m, r_orb, ph)
                bid = self.add_body(ROCKY, m, p, v)
                self.seed_rotation(bid,days*86400,math.radians(tilt))
            ep, ev = self.orbit(origin, origin, sun + 0.003, 60, 5.2)
            earth = self.add_body(ROCKY, 0.003, ep, ev)
            self.seed_rotation(earth,86164.0905,math.radians(23.44))
            moon = self.add_satellite(earth, ROCKY, 3.7e-5, 384_400_000 / units.LENGTH_M, 1.0)
            self.seed_rotation(moon,27.321661*86400,math.radians(6.68))
            for _ in range(60):
                p, v = self.orbit(origin, origin, sun, rng.uniform(132, 192), rng.uniform(0, 6.283), rng.gauss(0, 0.02))
                self.add_body(ASTEROID, 4.7e-7 * rng.uniform(0.01, 1), p, v)
            jp, jv = self.orbit(origin, origin, sun + units.JUPITER_MASS, 312.24, 0.9)
            jupiter = self.add_body(GAS_GIANT, units.JUPITER_MASS, jp, jv)
            for distance_m, m, ph in ((421_700_000, 4.49e-5, 0.0),
                                      (671_100_000, 2.41e-5, 2.1),
                                      (1_070_400_000, 7.45e-5, 4.2)):
                bid = self.add_satellite(jupiter, ROCKY, m, distance_m / units.LENGTH_M, ph)
                period = 2*math.pi*math.sqrt((distance_m/units.LENGTH_M)**3/(G*(units.JUPITER_MASS+m)))*units.TIME_S
                self.seed_rotation(bid,period)
            sp, sv = self.orbit(origin, origin, sun + 0.2857, 574.92, 3.3)
            saturn = self.add_body(GAS_GIANT, 0.2857, sp, sv)
            # Resolve Titan; metre-sized ring material needs a statistical model,
            # not a few massive super-particles forcing every body's timestep.
            titan = self.add_satellite(saturn, ROCKY, 6.77e-5, 1_221_870_000 / units.LENGTH_M, 0.4)
            period = 2*math.pi*math.sqrt((1_221_870_000/units.LENGTH_M)**3/(G*(.2857+6.77e-5)))*units.TIME_S
            self.seed_rotation(titan,period)
            up, uv = self.orbit(origin, origin, sun + 0.04365, 1151.4, 4.4)
            self.add_body(GAS_GIANT, 0.04365, up, uv)
            np_, nv = self.orbit(origin, origin, sun + 0.0515, 1804.2, 5.5)
            self.add_body(GAS_GIANT, 0.0515, np_, nv)
            cam = {"focus": [0, 0, 0], "distance": 1300.0, "pitch": 0.62}

        elif name == "binary":
            ma, mb, sep = 1000.0, 600.0, 40.0
            vrel = math.sqrt(G * (ma + mb) / sep)
            xa, xb = -sep * mb / (ma + mb), sep * ma / (ma + mb)
            self.add_body(STAR, ma, (xa, 0, 0), (0, 0, vrel * mb / (ma + mb)))
            self.add_body(STAR, mb, (xb, 0, 0), (0, 0, -vrel * ma / (ma + mb)))
            p, v = self.orbit((xa, 0, 0), (0, 0, vrel * mb / (ma + mb)), ma, 9.0, 1.0)
            self.add_body(ROCKY, 0.003, p, v)
            for r_orb, btype, m, ph in ((150, GAS_GIANT, 1.0, 0.5), (230, ROCKY, 0.004, 3.0), (300, GAS_GIANT, 0.2, 5.0)):
                p, v = self.orbit(origin, origin, ma + mb, r_orb, ph)
                self.add_body(btype, m, p, v)
            cam = {"focus": [0, 0, 0], "distance": 420.0, "pitch": 0.7}

        elif name == "black_hole":
            bh = 20000.0
            hole_id = self.add_body(BLACK_HOLE, bh, origin, origin)
            # A star on a plunging orbit: it will be torn apart near periapsis.
            apo, peri = 3.0, 0.05
            sma = (apo + peri) / 2
            mu = G * (bh + 1000)
            v_apo = math.sqrt(mu * (2 / apo - 1 / sma))
            source_id = self.add_body(STAR, 1000.0, (-apo, 0, 0), (0, 0, -v_apo))
            bp, bv = self.orbit(origin, origin, bh + 1500, 40, 1.2)
            self.add_body(STAR, 1500.0, bp, bv)
            pp, pv = self.orbit(bp, bv, 1500.003, 0.6, 0.0)
            self.add_body(ROCKY, 0.003, pp, pv)
            apo2, peri2 = 70.0, 15.0
            sma2 = (apo2 + peri2) / 2
            v2 = math.sqrt(G * (bh + 600) * (2 / apo2 - 1 / sma2))
            self.add_body(STAR, 600.0, (0, 0, apo2), (v2, 0, 0))
            for _ in range(45):
                p, v = self.orbit(origin, origin, bh, rng.uniform(55, 75), rng.uniform(0, 6.283), rng.gauss(0, 0.03))
                self.add_body(ASTEROID, DEFAULT_MASS[ASTEROID], p, v)
            cam = {"focus": [0, 0, 0], "distance": 6.0, "pitch": 0.35, "display_scale": 0.05}

        elif name == "smash":
            self.add_body(ROCKY, 0.003, (-0.4, 0.0, 0.0), (2.5, 0.0, 0.0))
            self.add_body(ROCKY, 0.0026, (0.4, 0.0, 0.0), (-2.5, 0.0, 0.0))
            cam = {"focus": [0, 0, 0], "distance": 3.0, "pitch": 0.35}

        elif name == "formation":
            sun = 1000.0
            self.add_body(STAR, sun, origin, origin)
            # Reproducible cold, thin annulus. No preselected pairs, collision
            # times, forces or outcomes: local instability follows full gravity.
            disk = random.Random(42)
            for index in range(64):
                mass = disk.uniform(.00035, .0005)
                p, v = self.orbit(origin, origin, sun + mass, disk.uniform(60, 60.4),
                                  disk.uniform(-.004,.004) if index < 8 else disk.uniform(0,2*math.pi), disk.gauss(0,.000001))
                circular = math.sqrt(sun / math.hypot(*p))
                v = tuple(x + disk.gauss(0, .003)*circular for x in v)
                self.add_body(ROCKY, mass, p, v)
            cam = {"focus": [0, 0, 0], "distance": 150.0, "pitch": .6, "display_scale": 0.0, "follow": -1}

        elif name == "galaxies":
            mbh, nstars = 8000.0, 110
            sep = 500.0
            vrel = math.sqrt(2 * G * 2 * mbh / math.hypot(sep, 200.0))  # parabolic encounter
            for sign, tilt, spin in ((-1, 0.0, 1), (1, 0.7, -1)):
                c = (sign * sep / 2, 0.0, sign * 100.0)
                cv = (-sign * vrel / 2, 0.0, 0.0)
                self.add_body(BLACK_HOLE, mbh, c, cv)
                for _ in range(nstars):
                    r_orb = 16 + 54 * rng.random() ** 0.8
                    p, v = self.orbit(c, cv, mbh, r_orb, rng.uniform(0, 6.283), tilt)
                    if spin < 0:  # flip the disk's sense of rotation
                        v = _sub(_mul(cv, 2), v)
                    bid = self.add_body(PLASMA, 0.05, p, v)
                    if bid is not None:
                        self.meta[str(bid)]['tidal_sample'] = True
                        p = self.particle(str(bid))
                        self.meta[str(bid)]['volume_radius'],p.r = p.r,0
            cam = {"focus": [0, 0, 0], "distance": 700.0, "pitch": 0.9}

        else:  # The validated remaining scenario is empty.
            cam = {"focus": [0, 0, 0], "distance": 350.0, "pitch": 0.6}
        if self.sim.N > 1 and name != "galaxies":
            # Zero the total momentum so the scene stays where the camera is.
            self.sim.move_to_com()
        if name == 'solar':
            if earth is not None:
                self.set_tide(earth,.299,638.)
            if moon is not None:
                self.set_tide(moon,.024,100.)
        if name == 'black_hole':
            # Frame the encounter after the COM translation, not the distant
            # companion system. R still exposes the complete system.
            hole = self.particle(str(hole_id))
            source = self.particle(str(source_id)) if source_id is not None else hole
            cam['focus'] = [(a+b)/2 for a,b in zip(hole.xyz,source.xyz,strict=True)]
        self._target_t = self.sim.t
        self.version += 1
        return {"type": "preset", "name": name, "camera": cam, "speed": self.speed}

    def load_collision_demo(self, case):
        # Use the same live engine and radius model as every sandbox encounter.
        if case not in DEMO_CASES:
            raise ValueError('Unknown collision encounter')
        if self.max_bodies < 2:
            raise ValueError('Collision demonstrations require two body slots')
        hint = self.load_preset('smash')
        particles = list(self.sim.particles)
        states, camera, info = demo_initial_conditions(case,[p.m for p in particles],[p.r for p in particles])
        for particle,(position,velocity) in zip(particles,states,strict=True):
            particle.xyz,particle.vxyz = position,velocity
        self.speed, self.paused = .005, True
        self.collision_demo = info
        conservation_report(self,reset=True)
        self.version += 1
        hint.update(camera=camera,speed=self.speed,collision_demo=info)
        return hint

    def load_tidal_demo(self):
        if self.max_bodies < 6:
            raise ValueError('The lunar experiment needs capacity for the Solar System seed bodies')
        hint = self.load_preset('solar')
        earth_id = next(p.name for p in self.sim.particles if p.m == .003)
        moon_id = next(p.name for p in self.sim.particles if p.m == 3.7e-5)
        for name in list(self.meta):
            if name not in (earth_id,moon_id):
                self.remove_body(int(name))
        earth,moon = self.particle(earth_id),self.particle(moon_id)
        self.set_tide(int(earth.name),0.,0.)
        radius = 6*earth.r
        position,velocity = self.orbit(earth.xyz,earth.vxyz,earth.m+moon.m,radius,1.,ecc=.05)
        moon.xyz,moon.vxyz = position,velocity
        a = radius/1.05
        period = 2*math.pi*math.sqrt(a**3/(G*(earth.m+moon.m)))*units.TIME_S
        self.seed_rotation(int(moon.name),period/1.2)
        self.sim.move_to_com()
        self._partition_dirty = True
        self._tide_integrator = None
        self.speed = .05
        hint.update(camera=dict(focus=list(moon.xyz),distance=radius*3,pitch=.6,yaw=.5,
                                display_scale=0.,follow=int(moon.name)),speed=self.speed,tidal_demo=True)
        return hint
