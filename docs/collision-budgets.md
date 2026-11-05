# Spherical collision budgets

`collision_outcomes.py` defines immutable SI sphere inventories and conservative
allocations. `collision_models.py` connects them to the
[calibrated mass classifier](impact-scaling.md); `World` applies accepted outcomes
outside REBOUND callbacks. Ejecta layouts, energy fractions and restitution are
prescriptions, not calibrated fragment distributions or hydrodynamics.

Collision outcomes are constructed in the pair’s centre-of-mass rest frame, then
translated back to the scene. This resolves physical contact at orbital distances
without subtracting large absolute coordinates during remnant construction.

## Persistent body inventories

`SphereState` contains mass, physical radius, position, velocity, spin angular
momentum and internal energy. Live metadata retains the intrinsic fields in
`BodyInventory`. Spin is angular momentum, not angular velocity. Internal energy
has a fixed material reference excluding self-binding; it is not visual heat or
a predicted temperature. New physical bodies explicitly start with zero spin and
zero energy above that reference. Gravity and visual cooling leave these fields
unchanged.

`inventory=None` means unknown. Heuristic collisions, tides and stellar
transformations invalidate affected inventories. Missing values are never
reconstructed from visual heat. Collision records copy incoming states before
native mutation; unknown inventories or legacy units cannot supply calibrated
inputs.

Versions 1–3 load with unknown intrinsic inventories. Version 4 adds per-body
spin/internal energy; version 5 also saves compact ejecta, ownership IDs, solver,
error history, explicit-loss ledger and comparison baseline. Legacy-unit bodies
retain null inventories. Restoration validates a separate world before replacing
the live one. See [compact ejecta](unresolved-debris.md) and
[orbital restart semantics](orbital-dynamics.md).

## Automatic model selection

Fresh worlds, Clear and every preset select `collisions: auto`, full gravity and
`impact_material: fluid_planets`. The Experiment menu exposes automatic versus
heuristic-only handling and planet versus small-body material assumptions.

- Planet calibration selects rocky–rocky pairs.
- Small-body calibration selects solid pairs (rocky and asteroid), within its
  1–100 km target-radius and other published limits.
- Other pairs use the documented heuristic rules. A selected solid pair outside
  its calibration or construction domain pauses intact; there is no heuristic
  fallback.

Automatic callbacks only record contacts. A simultaneous batch containing a
calibrated pair pauses before mutation. Other contact components merge each body
once, then apply heuristic outcomes. Tides, supernovae and boundary removal remain
available; their inventory changes are recorded separately.

Versions 1–2 retain tracer/heuristic defaults. Later files retain saved settings;
an omitted collision selector means heuristic. An omitted material selector means
planet calibration. Unknown external heat or spin does not block an impact:
external gravity uses only mass, radius and position.

## Live isolated mergers

`isolated_mergers` accepts only classified merging/graze-and-merge;
`isolated_impacts` also accepts separated outcomes. These saved/API modes use the
same constructors and selected material as automatic mode, but require physical
units, full gravity and `escape_distance: null`. Automatic tides, supernovae and
removal are disabled. For example:

```json
{"collisions":"isolated_impacts","gravity":"full","escape_distance":null}
```

## Classified construction

`construct_collision(a, b, material=..., body_types=..., resolved_policy=True)`
returns classification, corrected contact states, remnants and an escape
certificate. It requires known, nonrotating inputs in the published domain.
`World` validates feasibility, external gravity and capacity before mutation,
then updates bodies and invalidates contact, forecast and partition caches.
Unsupported inputs pause with an explanation and leave incoming bodies intact.
A constructed remnant can carry spin, but a later calibrated encounter involving
that spin is unsupported.

### Contact reconstruction

`surface_contact` projects a shallow sample (relative separation error at most
`1e-4`) onto the summed physical radii R, retaining COM state and separation
direction. For sampled separation d and relative radial/tangential velocities:

```text
v_t,contact = (d/R) v_t
v_r,contact = −sqrt[v_r² + |v_t|²(1 − d²/R²) + 2GM(1/R − 1/d)]
```

This preserves isolated point-mass energy and angular momentum. It is a local
correction, not an exact earlier collision time. Classification uses the corrected
state. Deep overlaps, separating samples and nonpositive radicands are rejected.

### Remnant policy

- Merging preserves volume, mass, COM velocity and orbital-plus-spin angular
  momentum. Remaining energy becomes internal energy. A negative internal
  inventory or spin at/above `I sqrt(GM/R³)` rejects the spherical remnant.
- Intact hit-and-run retains individual masses/radii, tangential velocity and
  existing heat. A frictionless normal impulse uses restitution `sqrt(0.5)`;
  half the normal relative kinetic energy becomes internal energy, shared by
  mass. Both survivors remain available for follow/selection.
- Other outcomes retain the classified largest remnant and runner, subdividing
  debris equally so no fragment exceeds the largest remnant. At most 32 bodies
  are constructed. Head-on single-remnant outcomes use a central remnant plus
  the next symmetric shell count (4, 6, 8, 12, 20 or 30); other layouts use a coarse
  spherical distribution or, for two remnants, the contact axis.
- Initial offsets use eight combined-volume radii. Half the energy available
  after binding/rotation feeds homologous expansion; half becomes internal
  energy. Capacity selects resolved or supported [compact ejecta](unresolved-debris.md)
  without changing classified masses. Unsupported layouts/full storage pause.

### Surrounding gravity

Let R enclose incoming/outgoing spheres about the pair COM, Dₖ be external centre
separations and r_c the contact separation. External spheres must lie outside
that region. With `H = Σ 2Gmₖ/(Dₖ−R)³`, require `2RH/(GM/r_c²) ≤ 1e-4`.
The exact incoming-minus-outgoing external potential is credited/debited to
internal energy by mass. Its magnitude must be at most `1e-4` of the larger of
relative kinetic energy and `Gm₁m₂/r_c`; all internal energies remain nonnegative.

These are instantaneous approximation limits, not long-term trajectory or
empirical remnant-mass error bounds. Subsequent gravity can deflect or recapture
remnants. An impact wholly inside a compact shell's cavity retains its constant
potential; outside-shell interactions use its monopole and the same screening.

## Spherical energies

For a uniform sphere, `I = 2mR²/5`, rotational energy is `|S|²/(2I)` and self-binding
is `−3Gm²/(5R)`. `collision_budget(states, origin_m=..., frame_velocity_m_s=...)`
sums mass, momentum, orbital-plus-spin angular momentum, translational/rotational
kinetic, self-binding, mutual potential and internal energy. Pair potential
`−Gm₁m₂/d` requires non-overlapping spheres (`1e-12` rounding slack). Compare budgets
in the same inertial frame; a nearby origin/velocity reduces cancellation.

**Experiment → Conservation report** includes resolved bodies and compact ejecta.
It shows raw changes and residuals corrected for explicit edits, removals and
heuristic transformations. The signed loss ledger retains complete aggregates
and the last 64 event details. Unknown inventories, overlapping surfaces or
incomplete loss history leave affected values unavailable. Model potential
offsets, integrated force-defect impulse and shell-step numerical energy drift
are separate diagnostics. Clear/presets reset the baseline; saves retain it.

## Allocation and escape APIs

`allocate_remnants(a, b, layout, expansion_fraction=f)` accepts touching spheres
and at least two `RemnantSpec` entries. Requested mass/volume must close to
`1e-12`; overlapping layouts, excessive spin and ill-conditioned inertia are
rejected. Offsets are recentred at the incoming COM without changing spacing.
The combined inertia tensor, including fragment spherical moments, solves
`J ω = L`; `ω × rᵢ` and `Iᵢω` carry orbital and intrinsic angular momentum with
minimum kinetic energy. If E remains after binding and rotation:

```text
H = sqrt(2 f E / Σ mᵢ |rᵢ|²)
vᵢ = v_COM + ω × rᵢ + H rᵢ
internal_energyᵢ = (mᵢ/M) (1−f) E
```

The low-level allocator permits bound fragments. Classified construction requires
an escape certificate; custom callers may supply a layout/fraction instead of
`resolved_policy`, retaining classified masses and mean density.

`remnant_escape_check` requires non-overlapping, receding remnants. Two-body
escape requires `v² > 2GM/d`. For multiple remnants, the sufficient impulse bound
`Bᵢ = Σ 2Gmⱼ/(dᵢⱼ uᵢⱼ)` requires `2(Bᵢ+Bⱼ) < uᵢⱼ` for every pair. Integrating
forces while each radial speed stays above half its initial value closes this
bootstrap bound. Symmetric central ejecta instead use positive radial energy
`.5 M_debris V² − κ G M_debris²/R − G M_core M_debris/R` with the finite-shape κ.
Positive margins are `1e-12` relative. These certificates concern isolated fixed
spheres, not guaranteed escape in an external field.

Tests cover independent energy values, conservation to `1e-12` of uncancelled
term scales, frame changes, regime boundaries, live contacts, capacity refusal,
compact/resolved references and restart. These are numerical/model checks, not
calibration of ejecta sizes, directions or thermodynamics.
