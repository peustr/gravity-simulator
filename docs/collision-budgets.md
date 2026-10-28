# Spherical collision budgets

`physics_server/collision_outcomes.py` provides SI state and inventory calculations
for isolated, homogeneous spheres. `physics_server/collision_models.py` connects
these constructors to the calibrated mass classifier. Planet smash uses the
resolved `isolated_impacts` path with its original initial conditions. Other
presets retain heuristic outcomes. `isolated_mergers` remains available for
merger-only experiments.

## State and energy convention

`SphereState` owns immutable mass, radius, position, velocity, spin angular
momentum and nonnegative internal energy. Spin is **angular momentum**, not angular
velocity. Internal energy has a fixed material reference and excludes self-binding;
it is not the renderer's dimensionless `heat` value or a temperature.

## Persistent body inventories

`body_state.BodyInventory` owns immutable `spin_kg_m2_s` and `internal_energy_j`.
New physical bodies default to zero spin and zero energy above the fixed material
reference. Gravity and visual cooling leave these intrinsic values unchanged;
there is no thermal or spin evolution model yet. This initial condition does not
assert that a body's temperature is zero.

Live metadata uses `inventory=None` when these budgets are unknown. Heuristic
mergers, fragmentation, stellar transformations and tidal debris invalidate them;
they do not compute the missing spin or energy. Collision records copy a pair of
`SphereState` values into `spheres` before native mutation, in survivor/removed
order. An unknown inventory, legacy units or an unrepresentable spherical state
produces `None` for that member. Later callbacks in the same step see an unknown
inventory for a previously merged survivor. Classification/construction must check
model applicability separately; a captured state is not an acceptance certificate.

Version-4 scene files require each body's `inventory` to be either null or an
object containing exactly `spin_kg_m2_s` (three finite SI components, magnitudes
at most 10¹⁰⁰) and `internal_energy_j` (finite, 0–10¹⁰⁰ J). Legacy-unit scenes
permit only null. Versions 1–3 load with unknown inventories while preserving
their existing body data and version-specific physics settings. Visual heat
cannot reconstruct missing internal energy. Invalid files are rejected before
the live world is replaced. Reservoir persistence is not supported yet. Live
diagnostics and removal accounting still measure orbital quantities only.

## Live isolated mergers

Set physics options together through a saved scene's `physics` object or the
`physics` command (other existing settings are retained for partial commands):

```json
{"collisions":"isolated_mergers","gravity":"full","escape_distance":null}
```

The mode requires physical units, full gravity and disabled escape removal.
It uses the `fluid_planets` calibration for exactly two rocky bodies with known
inventories and nonrotating inputs. All density, mass, speed, geometry, shallow
contact and remnant-spin feasibility limits still apply. It accepts only
classified merging or graze-and-merge outcomes. An extra body, unsupported state
or non-merging outcome pauses at the detected encounter with an explanatory
notice and both particles intact. There is no heuristic fallback. The detected
contact may overlap by the documented contact-guard tolerance; this is not a
rollback to an exact earlier collision time.

The native callback records one immutable encounter and leaves both particles
unchanged. After the native step, all model validation and output construction
precede deletion/mutation. The survivor keeps its ID and receives the constructed
mass, volume-preserving radius, COM position/velocity, spin and internal energy.
The other body is removed; partition/contact/forecast caches are invalidated.
No heuristic type promotion overwrites the radius or inventories. A merge event
and artistic glow indicate contact; glow does not measure deposited energy.

Tidal shredding, supernovae and automatic removal are disabled in this mode.
Orbital stepping and visual cooling continue. A spinning survivor retains its
inventory, but another collision involving it is rejected because the calibration
requires nonrotating inputs. New scenes and saves omitting `collisions` use
`heuristic`; version-4 files persist the selected mode. Existing saves with unknown
inventories cannot supply calibrated input states. Switch modes explicitly or
prepare supported initial conditions before resuming a rejected encounter.

`isolated_impacts`, selectable in **Experiment → Calibrated collisions**, also
constructs separated remnants. Planet smash enables it automatically; other
presets restore heuristic collisions. It retains the same two-body, material and
spin restrictions. The resolved policy keeps the classified largest remnant and
runner, and divides debris equally into the minimum number of fragments no
heavier than the largest remnant, at most 32 bodies total. A deterministic
spherical shell at eight combined-volume radii supplies offsets; a two-remnant
layout follows the contact axis. Half of the available post-binding/rotation
energy feeds expansion and half becomes internal energy. These are explicit
resolution/geometry prescriptions, not calibrated ejecta distributions. All
budgets and the escape certificate must pass before live mutation. Insufficient
body slots pause the intact encounter; no unresolved reservoir is yet applied.
Constructed radii and inventories survive save/restart. Benchmarks report the
complete SI body inventory separately from orbital-only diagnostics.

## Spherical energies

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
more, `all_pairs_escape_bound` uses each initial separation dᵢⱼ, positive radial
speed uᵢⱼ and individual mass mⱼ:

```text
Bᵢ = Σⱼ≠ᵢ 2Gmⱼ / (dᵢⱼ uᵢⱼ)
2(Bᵢ + Bⱼ) < uᵢⱼ  for every pair
```

If every radial speed remains at least half its initial value, integrating each
force bound Gmⱼ/(dᵢⱼ + uᵢⱼt/2)² to infinity gives Bᵢ. A pair's radial acceleration
is at least −(|aᵢ|+|aⱼ|), because transverse motion contributes nonnegatively.
The strict inequality therefore prevents any pair from being the first to slow
to half its initial speed, proving continued separation. This sufficient bound
retains actual masses/distances; replacing them by global minima recovers the
more conservative u_min² > 8GM/d_min bound.

Both checks require a 10⁻¹² relative positive margin. Marginal/parabolic cases and
inconclusive multi-body layouts are rejected.
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
