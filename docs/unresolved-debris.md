# Unresolved debris inventories

`physics_server/debris.py` partitions an already constructed collision outcome
into explicit spherical states and a compact unresolved-material inventory. It
does not select the collision regime, construct new physical fragments, mutate
the live simulation or evolve the reservoir.

## Capacity contract

`partition_debris(outcome, max_explicit_debris=...)` accepts the immutable result
of [`construct_collision`](collision-budgets.md#classified-construction).
The capacity is a nonnegative integer counting optional debris slots **after**
reserving the largest remnant and any hit-and-run runner. Those one or two
primaries replace the two incoming bodies and always remain explicit.

Debris is selected by decreasing mass, with ties resolved by its original layout
order. Zero capacity leaves all debris unresolved. Capacity above the fragment
count retains every fragment and produces no reservoir. Selection changes no
mass, radius, position, velocity, spin, internal energy, regime or escape
certificate; it only chooses the representation of the precomputed outcome.

The returned `DebrisPartition` stores the classification, escape certificate,
primary states, explicit debris states, optional `DebrisReservoir`, and the
gravitational potential between explicit and unresolved material. It does not
retain the original outcome or the unresolved fragment states.

## Reservoir state

`summarize_debris(states)` accepts one or more non-overlapping `SphereState`
objects. It stores fixed-size aggregate data:

- Fragment count, total mass, summed physical volume, centre-of-mass position
  and velocity, and an enclosing extent measured from the centre to the furthest
  fragment surface.
- Orbital angular momentum relative to the reservoir centre and velocity,
  separately from summed fragment spin angular momentum.
- Velocity-dispersion energy, summed rotational energy, fragment self-binding,
  mutual potential within the reservoir, and internal energy.

The reservoir is not a new sphere. Opposing spins can sum to zero while their
rotational energies remain positive. Unresolved orbital angular momentum is not
relabelled as spin, velocity dispersion is not relabelled as heat, and the binding
energy is not recomputed as though fragments had merged.

For reservoir mass M, centre R, mean velocity V, central orbital angular momentum
L_c, summed spin S and dispersion energy K_d, its budget about origin o in a
frame moving at u uses:

```text
P = M (V − u)
L = (R − o) × P + L_c + S
K_translation = ½ M |V − u|² + K_d
```

`reservoir.budget(origin_m=..., frame_velocity_m_s=...)` returns the same inventory
fields as `collision_budget`. `partition.budget(...)` adds the explicit and
reservoir inventories and includes the cross potential exactly once:

```text
U_mutual = U_explicit + U_unresolved + U_cross
U_cross = Σ_explicit i Σ_unresolved j (−G m_i m_j / distance_ij)
```

Cross potential is calculated from the fragment states before compression. It
is not approximated by placing the reservoir mass at its centre. The quantities
are evaluated in a common inertial frame; extreme absolute coordinates or boosts
can lose floating-point precision just as for individual spherical states.

## Far-field gravity exchange

`physics_server/debris_gravity.py` supplies an instantaneous gravity estimate and
a momentum substep between a reservoir and a resolved `SphereState`. Neither
operation moves bodies or advances a debris cloud through time.

`estimate_gravity(reservoir, body)` treats each distribution as a monopole at
its centre of mass. The two enclosing supports must not overlap. Let M and m
be their masses, d their centre separation, a the reservoir extent, and
R = a + body.radius_m. Conservative bounds on the instantaneous approximation are:

```text
|force error| ≤ 12 G M m R² / (d − R)⁴
|potential error| ≤ G M m R² / (d − R)³
omitted internal tidal acceleration ≤ 2 G m a / (d − R)³
omitted tidal torque ≤ M a × tidal_acceleration_bound
```

The mass-weighted first-order terms vanish at the centres of mass. Taylor
remainder bounds use a force second directional derivative no larger than
24/r⁴ and a potential Hessian norm no larger than 2/r³, before multiplying by
G and the masses. The tidal bound follows from the force gradient norm 2/r³.
These are geometric bounds for fixed spherical constituents; they exclude
roundoff and do not bound a future trajectory or changing support.

`gravity_kick(reservoir, body, duration_s, max_relative_force_error=...,
max_tidal_velocity_change_m_s=...)` rejects estimates beyond the supplied
accuracy limits. Relative force error is measured against the monopole force
magnitude. The tidal limit bounds the omitted velocity change over the
**frozen-position substep**, not over a complete physical timestep.

An accepted kick applies impulse **J** to the reservoir and −**J** to the body,
preserving linear and orbital-plus-intrinsic angular momentum analytically.
Mass, volume, shape extent, spin, dispersion and internal energies are unchanged.
Its `GravityKick` result includes updated immutable states, the estimate, impulse,
omitted tidal velocity/angular-momentum bounds, and the pair's kinetic increment:

```text
kinetic_work = J · (V_reservoir − V_body) + ½ |J|² (1/M + 1/m)
```

Work can be negative. It is not heat and must not be added to internal energy.
A kick alone does not conserve isolated total energy; a complete integrator must
also evolve positions and gravitational potential, with a separate error test.
The monopole potential estimate never replaces the stored exact snapshot cross
potential. Small impulses can be quantized when added to large absolute stored
velocities; an audit-frame change cannot recover that lost precision.

Tests compare force, potential, tidal acceleration and torque bounds against
fully resolved fragment calculations, check quadratic far-field convergence,
and verify paired momentum/angular-momentum identities, work, inertial-frame
transformations and rejection at inadequate accuracy. These are substep checks,
not long-term cloud evolution validation.

## Time and storage limits

These inventories describe **one instant**. Stored potentials cannot be reused
after moving resolved bodies, and aggregate moments cannot recover individual
trajectories or resample uniquely when capacity increases. The separate
[expanding-cloud transport model](debris-transport.md) evolves a restricted radial
expansion mode with changing extent and gravitational potentials. It must be
initialized from fragment states before compression; it cannot reconstruct a cloud
from this snapshot alone. General shape evolution, tidal deformation, accretion,
expiry and persistence integration remain unsupported.

Each collision retains O(k) explicit states plus O(1) reservoir data, where k is
the retained particle count. Creation still examines the full proposed fragment
list and evaluates pair potentials in O(N²) time. The separate
[reservoir store](debris-lifecycle.md) bounds retained transport records across
events with fixed slots and explicit admission refusal. It preserves complete
state on handoff and supports exact promotion of one-fragment reservoirs;
automatic coalescence and multi-fragment resampling are unsupported.

Validation compares every inventory component and material volume against the
fully explicit outcome across all classified regimes and capacities, including
zero capacity. It also covers inertial-frame changes, opposing spins, a single
fragment, stable selection, cross-potential accounting and release of the hidden
fragment objects. Numerical closure targets are 10⁻¹² relative to physical term
scales; they are not error bounds for a future statistical evolution model.
