# Spherical collision budgets

`physics_server/collision_outcomes.py` provides SI state and inventory calculations
for isolated, homogeneous spheres. It is separate from the collision classifier
and the live handler. No persistent state, particles or renderer fields are changed.

## State and energy convention

`SphereState` owns immutable mass, radius, position, velocity, spin angular
momentum and nonnegative internal energy. Spin is **angular momentum**, not angular
velocity. Internal energy has a fixed material reference and excludes self-binding;
it is not the renderer's dimensionless `heat` value or a temperature.

For mass m, radius R and spin angular momentum **S**, the uniform-sphere model is:

```text
I = (2/5) m R²
K_spin = |S|² / (2I)
U_self = −(3/5) G m²/R
```

`collision_budget(states, origin_m=..., frame_velocity_m_s=...)` reports mass,
linear momentum, orbital-plus-spin angular momentum, translational and rotational
kinetic energy, self-binding, mutual potential and internal energy. Its total
energy is the sum of those five energy components. Mutual potential is −Gm₁m₂/d,
valid for non-overlapping spherical distributions. Overlap beyond 10⁻¹² relative
rounding slack is rejected. An empty inventory is zero.

Compare budgets in the same inertial frame. A nearby origin and frame velocity
help resolve small collision energies against large orbital values. Extremely
large absolute coordinates/velocities can still lose relative precision when
stored as floats; changing the audit frame cannot recover information already lost.

## Single-remnant construction

`merge_spheres(a, b)` requires touching spheres (10⁻¹² relative tolerance), with
approaching or stationary separation. It constructs a remnant at the pair's centre
of mass with its mass-weighted velocity and volume-preserving radius:

```text
M = m₁ + m₂
R_final³ = R₁³ + R₂³
S_final = S₁ + S₂ + μ (relative_position × relative_velocity)
```

Internal energy is obtained from the isolated pair's energy balance in its
centre-of-mass frame. The calculation includes relative kinetic energy, incoming
spin energy, both initial self-binding terms, pair potential, final self-binding
and final spin energy. It never subtracts two large bulk kinetic energies to
recover a small collision energy. An energy deficit is rejected, not replaced
with negative internal energy or an arbitrary heat floor.

A single spherical remnant is also rejected when |S_final| ≥ I sqrt(GM/R³),
where equatorial centrifugal acceleration reaches surface gravity. This is a
necessary retention screen, not a demonstration of fluid-shape stability.
Neither rejection selects a different collision regime automatically.

This is a conditional outcome constructor, not a merger criterion. It assumes a
fixed spherical shape and no material strength, pressure-driven expansion, radiation, mass loss,
external gravitational work, composition changes or equation of state. Internal
energy therefore records an accounted reservoir without predicting temperature.
Input spins are accounted mathematically; the classifier still assumes nonrotating
bodies. Shallow native overlaps need contact reconstruction before use. Remnant
stability, multiple remnants, fragments and full-scene integration require further
models.

Tests check analytic binding-energy release, incoming/orbital spin transfer,
mass/momentum/angular-momentum/energy closure, body exchange, inertial-frame
changes, energy and spin exclusions, immutable state and invalid inputs.
