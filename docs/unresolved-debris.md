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

## Time and storage limits

These inventories describe **one instant**. Stored potentials cannot be reused
after moving resolved bodies, and aggregate moments cannot recover individual
trajectories or resample uniquely when capacity increases. There is no reservoir
advection, force coupling, accretion, expiry or persistence integration yet.
An explicit evolution and transfer model is required before live use.

Each collision retains O(k) explicit states plus O(1) reservoir data, where k is
the retained particle count. Creation still examines the full proposed fragment
list and evaluates pair potentials in O(N²) time. Storage across repeated
collisions is not yet bounded by a reservoir lifecycle policy.

Validation compares every inventory component and material volume against the
fully explicit outcome across all classified regimes and capacities, including
zero capacity. It also covers inertial-frame changes, opposing spins, a single
fragment, stable selection, cross-potential accounting and release of the hidden
fragment objects. Numerical closure targets are 10⁻¹² relative to physical term
scales; they are not error bounds for a future statistical evolution model.
