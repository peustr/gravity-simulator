# Spherical collision budgets

`physics_server/collision_outcomes.py` provides SI state and inventory calculations
for isolated, homogeneous spheres. `physics_server/collision_models.py` connects
these constructors to the calibrated mass classifier. Both modules are separate
from the live handler; no persistent state, particles or renderer fields are changed.

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

## Multiple-remnant allocation

`allocate_remnants(a, b, layout, expansion_fraction=...)` accepts two touching,
approaching or stationary spheres and at least two immutable `RemnantSpec` entries.
Each entry prescribes a mass, radius and relative position offset. Mass and total
volume must match the incoming inventory to 10⁻¹² relative tolerance; overlapping
layouts are rejected. Masses and radii are never adjusted to make a layout fit.
The allocator recentres the offsets at the incoming centre of mass and preserves
their relative spacing. Returned states follow the layout's order.

For centred offsets **rᵢ**, spherical moments Iᵢ and incoming angular momentum **L**
in the centre-of-mass frame, the combined inertia tensor determines a common
angular velocity:

```text
J = Σ [mᵢ (|rᵢ|² identity − rᵢ rᵢᵀ) + Iᵢ identity]
J ω = L
v_rotation,i = ω × rᵢ
Sᵢ = Iᵢ ω
```

This is the minimum kinetic energy needed to carry **L** for the prescribed
layout, allowing both orbital motion and spin. Intrinsic spherical moments allow
collinear layouts to carry angular momentum along their axis. Inertia condition
numbers above 10¹² are rejected as numerically unresolved. Each remnant must also
pass the same spherical spin screen as a single remnant.

Subtract the final self-binding, mutual potential and minimum kinetic energy from
the incoming centre-of-mass energy to obtain the excess energy E. Negative E
rejects the layout. For an explicitly supplied fraction f between zero and one:

```text
H = sqrt(2 f E / Σ mᵢ |rᵢ|²)
vᵢ = v_centre + ω × rᵢ + H rᵢ
internal_energyᵢ = (mᵢ / M) (1 − f) E
```

Radial expansion adds no net momentum or angular momentum and is perpendicular
to the rotational velocity. It assigns f E to outward motion; the remainder is
shared as uniform specific internal energy. Pair separations are initially
nondecreasing, but fragments may remain gravitationally bound and reaccrete.
No particle-capacity limit enters this calculation.

Masses, radii, spacing and f are caller choices, not a calibrated ejecta model.
In particular, supplying classified runner/debris masses does not establish a
hit-and-run escape trajectory. Spin rejection excludes this common-rotation
allocation; it does not prove that every angular-momentum partition is infeasible.
Neither an allocation nor its rejection selects a different collision regime.

## Classified construction

`construct_collision(a, b, material=..., body_types=..., layout=None,
expansion_fraction=None)` accepts SI `SphereState` inputs and returns an immutable
`ConstructedCollision` with the classification, corrected contact states, remnants
and an escape certificate. It requires nonrotating inputs and enforces the
[classifier's material, size, density and geometry limits](impact-scaling.md).

For `merging` and `graze_and_merge`, it calls `merge_spheres`; layout and energy-split
arguments are rejected. Other regimes require an explicit layout and energy split:

- Entry 0 has the classified largest-remnant mass.
- For hit-and-run, entry 1 has the classified runner mass.
- Remaining entries sum to the classified unassigned mass, with no fragment larger
  than the largest remnant. All radii retain the incoming volume-averaged density.
- Every separated remnant must pass the escape check below. Thus a budget-closed
  allocation that could immediately reaccrete is insufficient for this constructor.

Mass and radius comparisons use 10⁻¹² relative tolerance. No layout, mass split,
energy fraction or collision regime is silently changed after a rejection.
The supported set is narrower than the classifier's: some classified mergers fail
the spherical spin screen, and some dispersive proposals cannot establish escape.
Bound disks, satellite formation and returning debris are unsupported here.
The lower-level `allocate_remnants` remains available for bound budget calculations.

### Surface reconstruction

`surface_contact(a, b)` accepts approaching samples within 10⁻⁴ relative distance
of surface contact. Samples already within 10⁻¹² pass through. For other samples,
let d be separation, R the sum of radii, and v_r and **v_t** the radial and
tangential parts of relative velocity. The correction preserves the sampled
separation direction, centre of mass, linear momentum, spin and internal energy:

```text
v_t,contact = (d/R) v_t
v_r,contact = −sqrt[v_r² + |v_t|²(1 − d²/R²) + 2GM(1/R − 1/d)]
```

This conserves orbital angular momentum and isolated point-mass energy. A
nonpositive radicand rejects a sample with no approaching surface state under
these invariants. For shallow overlaps, the input potential is explicitly
−Gm₁m₂/d, consistent with an unsoftened point-mass step; it is not an extended-sphere
overlap potential. Deep overlaps and separating samples are rejected.

This local correction does not recover the exact contact time or orbital phase.
Classification uses the corrected state, so near-boundary labels and masses can
differ from classification of the raw sample. Layouts must use that corrected
classification. External fields, softened gravity and native callback application
require separate treatment before live integration.

### Escape checks

`remnant_escape_check(states)` certifies escape only for isolated, fixed spherical
remnants under Newtonian gravity. All pairs must be non-overlapping and receding.
For two remnants, `two_body_hyperbolic` requires relative v² > 2GM/d. For three or
more, `all_pairs_escape_bound` uses total mass M, minimum pair separation d₀ and
minimum pairwise radial speed u₀:

```text
u₀² > 8GM/d₀
```

This is a sufficient bound, not a necessary escape threshold. If every pair keeps
separating at least at u₀/2, all distances exceed d₀ + u₀t/2. The magnitude of the
relative gravitational acceleration is bounded by 2GM/(d₀ + u₀t/2)²; its integral
to infinity is 4GM/(d₀u₀), less than u₀/2 under the condition above. Radial
acceleration also has a nonnegative transverse-motion term. Therefore no pair can
be the first to slow to u₀/2, establishing continued separation and escape.

Both checks require a 10⁻¹² relative positive margin between their squared-speed
terms. Marginal/parabolic cases and inconclusive multi-body layouts are rejected.
Requiring all remnants to escape also rejects cases where a runner escapes while
some debris remains bound. These certificates do not apply in an external field,
with expanding radii, or with additional dissipation.

## Applicability and validation

The constructors assume
fixed spherical shapes and no material strength, pressure-driven expansion,
radiation, external gravitational work, composition changes or equation of state.
Internal energy records an accounted reservoir without predicting temperature.
The low-level budget APIs account for input spins; calibrated construction requires
nonrotating inputs. Prescribed spacing, fragment subdivisions and energy fractions
remain uncalibrated. Fluid-shape stability and full-scene integration require further models.

Tests check analytic binding-energy release, incoming/orbital spin transfer,
mass/momentum/angular-momentum/energy closure, body exchange, inertial-frame
changes, energy and spin exclusions, immutable state and invalid inputs. Multiple
remnants include unequal and collinear layouts, classified intact/eroded runner
masses, and zero/partial/full expansion-energy allocation. Construction checks
span every classified regime, shallow samples on either side of contact, invalid
mass/density assignments, bound outcomes and independent N-body propagation of
intact and eroded runner cases. Their conservation
residuals are bounded by 10⁻¹² times the sums of the corresponding physical term
magnitudes before cancellation, rather than by a potentially zero net budget.
These are numerical closure bounds for the test cases, not accuracy claims for
fragment sizes, directions or internal-energy fractions.
