# Physics realism roadmap

Goal: maximise physical accuracy on broadly accessible consumer computers.
Support ordinary laptops and desktops with 8–16 GB RAM and integrated graphics;
scale scene size and simulation speed to available compute. Prefer slower
simulated time over silently reducing accuracy during difficult encounters.

## Hardware and performance targets

Published consumer specifications inform the design envelope: ASUS lists
8–16 GB RAM, Core i5/i7 U-series CPUs and integrated UHD/Iris Xe graphics for the
[Vivobook 15](https://www.asus.com/us/laptops/for-home/vivobook/asus-vivobook-15-x1504/techspec/),
and 16 GB RAM with Ryzen CPUs and Radeon graphics for the
[Zenbook 14 family](https://www.asus.com/au/laptops/for-home/zenbook/zenbook-14-um3402/).
These are examples of accessible hardware classes, not device-specific support
requirements or measured simulation performance.

- Baseline: an ordinary 64-bit consumer CPU, 8 GB system RAM, integrated graphics.
- Reference: a mainstream Core i5/Ryzen 5 class CPU, 16 GB RAM, integrated graphics.
- Larger systems may use stronger CPUs or GPUs; no dedicated GPU should be
  required for the core physics engine.
- Initial responsiveness goals: physics advance p95 within 11 ms, forecast p95
  within 33 ms, and rendered frame p95 within 33.3 ms at 1280×720. Aim for 16.7 ms
  frames where practical. These are engineering targets, not certified results.
- Compare repeated measurements on the same hardware/settings. Preserve physical
  accuracy by reducing simulated speed or explicitly selecting a cheaper valid
  model; graphics settings and body population are separate controls.

Work in order. A milestone is complete only when its acceptance criteria and
required checks pass. Mark its checklist entry `[x]`, strike through its title,
and make the next milestone active. Store generated measurements in ignored
`benchmarks/`.

## Delivery rule: visible, shared physics

Each checklist item must name its physical effect, supported domain, existing
demo and observable result before implementation. Completion requires both a
numerical reference and an application check of that result. Demo variants may
change initial conditions; all use the shared engine. Every preset remains part
of regression testing, including those unaffected by the new physics.

Release acceptance follows [the scene quality standard](scene-quality.md).
Failed or blocked scene gates keep the current work open regardless of unit-test
coverage. Review complete event sequences on the target rendering path.

Use physical time controls, measurements and comparisons to expose slow effects;
label assumptions and artistic display choices. Freeze the model references,
numerical tolerances and demo acceptance cases before coding each milestone.
Additional features require a scope decision rather than extending its checklist.

## Milestones

- [x] ~~1. Accuracy and performance baseline~~
- [x] ~~2. Physical units and independent display sizes~~
- [x] ~~3. Trustworthy orbital dynamics~~
- [x] ~~4. Credible impact outcomes~~
- [x] ~~Scene quality and collision demonstration~~
- [ ] **5. Rotation and tidal evolution**
- [ ] **6. Composition and thermal history**
- [ ] **7. Stellar evolution and compact objects**
- [ ] **8. Specialised simulation modes**

## 1. Accuracy and performance baseline

- [x] Measure mass, linear momentum, orbital angular momentum, and Newtonian
  mechanical energy; identify tracer approximations and non-conservative rules.
- [x] Account explicitly for escape removal and prescribed black-hole mass loss,
  without describing mechanical energy changes as computed radiation.
- [x] Validate circular/eccentric Kepler orbits, two-body scattering, hierarchical
  systems, and collision mass/momentum conservation against stated tolerances.
- [x] Provide seeded, repeatable benchmark workloads for planetary systems,
  binaries, debris, and close encounters, with machine/version metadata.
- [x] Measure tick and forecast latency and simulation throughput; profile
  integration (including gravity/collision detection), collision outcomes, tides,
  packing, and forecasting separately from unprofiled timings.
- [x] Provide a rendered frame-time measurement command (`benchmark-visual`).
- [x] Validate the rendered measurement workflow on a machine with a display.
- [x] Define broad consumer hardware classes and explicit initial performance
  targets, with published specification references.

Acceptance: physical reference gates pass, representative runtime costs are
measurable, known modelling changes are distinguished from integrator error, and
the benchmark workflows produce valid reports. Real-machine performance
qualification continues across hardware classes; cloud/headless measurements
must not be presented as rendered or consumer-device results.

## 2. Physical units and independent display sizes

- [x] Define explicit unit conversions and authoritative physical constants.
- [x] Separate physical, rendered, and selection radii throughout placement,
  collision detection, orbit forecasts, and Godot presentation.
- [x] Adopt defensible density or mass–radius models and rebuild scenarios with
  consistent initial conditions.
- [x] Migrate saved scenes and the Python/Godot protocol without silently
  changing the meaning of existing values.
- [x] Verify that visual enlargement cannot change physics; run the physical
  accuracy gates and compare runtime cost with the baseline.

Acceptance: changing visual enlargement cannot change physical outcomes;
unit conversions and scenario orbits pass the baseline checks. Migrate saves and
the Python/Godot protocol explicitly when their meaning changes.

Implementation reference for units, radii, scenarios and compatibility:
[physical model](physical-model.md).

## 3. Trustworthy orbital dynamics

- [x] Validate long-duration circular/eccentric orbits and hierarchical systems;
  document error targets and convergence as IAS15 tolerances tighten.
- [x] Validate fast, grazing and compact-object contacts across timestep and
  tolerance changes. Resolve radial-capture convergence warnings without hiding
  them or imposing an inaccurate minimum timestep.
- [x] Evaluate symplectic integration on eligible planetary systems against
  IAS15, including runtime, drift and close-encounter limitations. Keep solver
  switching disabled until independently validated.
- [x] Make full gravity and tracer approximations explicit and persistent;
  quantify omitted collective debris mass and gravitational back-reaction.
- [x] Check forecast deadlines between individual native steps, preserve solver
  tolerances, sample in forward time, and test interruption inside one sample.
- [x] Validate forecast accuracy limits beyond the isolated two-body case,
  including omitted perturbers, tracer forces and contact timing.
- [x] Define configurable removal boundaries and account for their losses.
- [x] Pass the Python 3.10–3.14 Linux/Windows CI matrix, including standalone
  and covered self-tests. The tidal-disruption case must reliably reach 60
  simulation units within its 20-second cutoff on supported runners, without
  relaxing contact error bounds or solver tolerances.
- [x] Measure default/full-gravity costs and forecast p95 latency against the
  33 ms target; pass `tools/dev.py check`.

Acceptance: documented long-duration error targets and convergence under tighter
tolerances; no missed benchmark contacts; explicit approximation settings and
measured runtime cost. Solver switching requires its own validation.

Reference problems, numerical bounds and model limitations:
[orbital dynamics](orbital-dynamics.md).

## 4. Credible impact outcomes

Calibrated solid-body impacts, physical inventories and compact ejecta are
available in the running sandbox, with explicit model domains and diagnostics.
Reference encounters, live preset controls, restart and performance workflows
cover the delivery requirements below.

### Current implementation

| Component | Available behavior | Remaining limitation |
|---|---|---|
| Contact state and saves | Immutable impact state; spin/internal energy, compact ejecta, solver/error/loss histories and tidal-sample identities | Older or heuristically transformed bodies can have unknown inventories |
| Classification and construction | Planet and small-body controls; live regimes, prescribed conserved layouts and loadable examples | Published domains, general rotating laws, strong fields and simultaneous contacts restrict applicability |
| Unresolved material | Live symmetric ejecta coupled to resolved bodies, disjoint/nested clouds, bounded storage and transactional refusal | Head-on expanding shells only; no surface crossing, recollapse or automatic reconstruction |
| Diagnostics | SI inventories across bodies/clouds, explicit-loss residuals, model offsets, force-defect and numerical diagnostics | Unknown intrinsic inventories or incomplete loss history leave affected values unavailable |

### Delivery requirements

- [x] **Live calibrated outcomes.** Apply merging, graze-and-merge, partial
  accretion, erosion, disruption and hit-and-run in the existing calibrated
  solid-body domains. Supply a bounded, documented remnant-layout and energy-split
  policy so callers do not have to invent fragment states. Label prescribed ejecta
  parameters honestly. Provide an application control and runnable reference
  scenes. Validate before mutation; unsupported encounters remain intact with a
  useful explanation, without silently reverting to heuristic outcomes.
- [x] **Encounters in populated scenes.** Account for surrounding bodies and
  changes in their interaction potential, with a quantitative bound on the
  isolated-impact approximation. Apply supported outcomes outside the native
  callback, update particle/forecast/contact caches, and handle successive
  encounters without losing inventories. Demonstrate supported impacts with a
  third gravitating body and repeated supported contacts; explicitly reject
  encounters outside the calibration, including unsupported incoming spin.
- [x] **Operational unresolved debris.** Choose and implement a representation
  that can evolve the ejecta produced by the live outcome policy, including its
  interaction with remnants and other bodies. Coordinate shared-body updates,
  ownership and bounded storage; preserve complete inventories through transfers.
  Changing explicit-particle capacity must not change the classified regime or
  discard material. Demonstrate the same impact with resolved and unresolved
  debris and bounded error against a resolved reference. Full storage or exceeded
  model limits must leave the encounter unapplied.
- [x] **Complete accounting and persistence.** Report mass, linear momentum,
  orbital plus spin angular momentum, and kinetic, binding, mutual and internal
  energies across bodies and unresolved material. Separate numerical error,
  approximation error and explicit losses. Save/restart must retain reservoirs,
  model parameters, error history and ownership without changing future behavior
  beyond documented integrator restart differences. Preserve old-save migration
  and clearly expose the active collision model and unsupported states.
- [x] **Release validation and maintenance.** Exercise every supported regime,
  grazing boundaries, populated scenes, successive contacts, capacity changes and
  save/restart through the live path. Require reference agreement and complete
  budget closure within documented numerical/model tolerances. Measure the
  existing representative workloads against the performance targets above and
  verify rendered Solar System smoothness. Pass repository checks, self-tests
  and CI. Consolidate superseded or unused implementations and duplicate prose;
  keep one documented runtime path per supported model.

### Scope

Mass-outcome calibrations retain their published applicability limits. Ejecta
layouts and energy fractions remain explicit modelling prescriptions unless
independently calibrated. General rotating-impact laws, tidal evolution,
thermodynamic/composition models, gas/stellar/compact-object collision laws and
hydrodynamics belong to later milestones. General cloud coalescence and resampling
are outside the current shell model.

Implementation contracts: [impact measurements](impact-measurements.md),
[calibration domains](impact-scaling.md), [collision budgets and live mode](collision-budgets.md),
[compact ejecta and ownership](unresolved-debris.md).

## Before Milestone 5: collision demonstration

Make the existing collision physics accessible and its contact/results legible.
Reuse Milestone 4's laws and shared construction policy. Rotation-dependent laws
and thermal/material response are delivered in Milestones 5 and 6 respectively.

- [x] **Selectable encounters.** Planet smash offers gentle merging, intact
  hit-and-run and disruptive encounters directly in the application, with replay.
  No generated files or manual placement are required to observe these cases.
- [x] **Inspectable contact.** Close camera and slow playback make physical
  surfaces and contact timing observable. Indicate visual enlargement; ensure
  the transient flash leaves the persistent remnants/debris easy to inspect.
- [x] **Results and regression.** Show encounter speed/angle, regime and remnant
  masses, with access to the conservation report. Identify calibrated mass laws
  and prescribed scattering/ejecta choices. Verify all three live encounters,
  resolved/compact budget agreement and continued operation of all seven presets.
  Planet formation must demonstrate observable embryo mass growth through shared
  rocky collisions at documented physical timescales.

Done when these three encounters can be selected, watched and replayed through
the normal UI, with numerical outcomes matching the existing reference gates;
Planet formation visibly grows embryos, and all seven presets pass live checks.

## 5. Rotation and tidal evolution

Visible outcome: planets/moons and impact remnants rotate according to physical
spin; spin-orbit exchange, precession and tidal heating are measurable in the
existing Solar System and Planet smash demos. Slow secular effects use measured
rates/history and documented time controls rather than hidden coefficient boosts.

Begin with solid planets, moons and resolved solid remnants. Use a documented
constant-time-lag equilibrium-tide model and a bounded axisymmetric gravity/shape
model. Declare material parameters, small-deformation limits and a published
rotating-impact law/domain before implementation; unsupported states remain
explicit. General deformable bodies and gas/stellar tides are outside this scope.

- [x] **Physical spin and orientation.** Extend the existing angular-momentum
  inventories with authoritative orientation and consistent moments of inertia.
  Solar System textures/axes and Planet smash remnants follow simulation time;
  inspector period/axis values, protocol migration and save/restart agree with
  the physical state.
- [x] **Coupled tidal evolution.** Apply equal/reaction forces and torques;
  transfer angular momentum between orbit and spin and record nonnegative tidal
  heating. Expose Love numbers and time lags. A supported Solar System satellite
  variant demonstrates synchronisation/circularisation through measured changes.
- [ ] **Rotational flattening and gravity.** Derive bounded flattening and J2
  from the declared interior/spin model, with consistent force, torque and energy
  accounting. Solar System moon orbits show the predicted precession; displayed
  shape, physical reference radii and any spherical-contact approximation are
  identified separately.
- [ ] **Rotating solid impacts.** Extend the supported input domain using the
  selected published law, initially a bounded aligned-spin case. Planet smash
  compares otherwise identical encounters with different spins and shows the
  resulting remnant motion/rotation. Retain total angular momentum and energy,
  including stored tidal energy at transitions to contact models;
  revise ejecta partitions consistently. Unsupported compact allocations must
  resolve within capacity or refuse intact, preserving their inventories.
- [ ] **Reference and live release checks.** Verify free rotation, analytic
  small-eccentricity tidal rates, synchronisation and J2 precession; compare
  spinning/zero-spin impacts and their inventories. Inspect the named live demos,
  test all seven presets separately, migration/restart and runtime costs, and
  pass repository checks and CI. Clean up superseded paths in the same change.

Acceptance gates for controlled references: orientation error below `1e-6` rad
after 100 rotations; tidal/precession rates within 1% of same-model analytic
limits with convergence under tighter stepping. Angular-momentum and total-energy
residuals, including deposited heat, stay below `1e-8` of uncancelled component
scales; instantaneous collision budgets retain their `1e-12` closure gates.
These are numerical checks, not empirical calibration-error claims.

## 6. Composition and thermal history

Visible outcome: composition, irradiation and deposited heat explain measured
temperature, phase, radius and atmosphere changes. Solar System demonstrates
distance/material dependence; Planet smash shows supported impact heating and
subsequent cooling; Planet formation retains material inventories through encounters.

Use globally averaged material/thermal models with documented energy references
and validity ranges. Detailed climate, chemistry, fluid flow and hydrodynamic
atmospheric escape remain outside this scope. Existing collision fits retain
their applicability limits; material labels alone do not extend a calibration.

- [ ] **Material inventories and physical radii.** Track rock, metal, ice and gas
  masses through creation, impacts, debris, removal and restart. Expose assumed
  properties in the inspector. Use supported density/compressibility relations;
  radius changes account for self-binding work and invalidate geometry caches.
- [ ] **Thermal state and heating.** Define heat capacity, reference energy and
  the conversion between thermal energy and temperature. Account for impact and
  tidal heating plus absorbed radiation from declared stellar luminosities.
  Set explicit preset initial conditions; migrated unknown states remain unknown
  until initialised rather than deriving temperatures from artistic glow.
- [ ] **Radiative cooling and presentation.** Include albedo, emissivity and
  outgoing thermal radiation in the energy balance. Solar System reports flux,
  effective temperatures and cooling histories; Planet smash's supported hot
  remnants cool visibly when they emit in visible wavelengths. Keep model-driven
  emission distinguishable from transient artistic impact effects.
- [ ] **Phase changes.** Include latent heat and bounded solid/liquid/vapour
  fractions for the selected materials. A supported Planet smash case shows the
  heating/cooling phase plateau and associated material/radius change. Expose
  limits where a spherical globally averaged remnant ceases to be applicable.
- [ ] **Atmosphere retention/loss.** Begin with Jeans escape for a specified
  isothermal exobase in its supported regime; expose exobase assumptions rather
  than equating them with bulk temperature. A Solar System body variant compares
  retention/loss rates. Account for escaping material, energy and angular
  momentum, with consistent radius/atmosphere display and saved state.
- [ ] **Reference and live release checks.** Check inverse-square flux,
  radiative equilibrium, constant-property cooling, latent-heat plateaus and
  escape limiting cases. Demonstrate the named effects through existing demos,
  verify material/energy inventories, protocol migration and restart, test all
  seven presets, measure runtime and pass repository checks/CI. Remove obsolete
  thermal/display paths.

Acceptance gates for controlled references: flux/equilibrium/cooling agree with
same-model analytic solutions within 0.1% and converge under tighter stepping;
material masses close within `1e-12` and energy within `1e-8` of uncancelled
component scales, including absorbed/emitted radiation and explicit losses.
Phase/escape rates must also match the chosen published prescription within its
declared numerical tolerance. Effective temperature is labelled separately from
surface/climate predictions; model-parameter uncertainty remains explicit.

## 7. Stellar evolution and compact objects

Use published tracks/fits for age/composition-dependent stellar properties,
winds, remnants, and supernova kicks. Add calibrated accretion prescriptions.
Evaluate targeted post-Newtonian precession and compact-binary radiation reaction
with a physical speed of light and explicit domains of validity.

Acceptance: evolution and supported relativistic examples match analytical or
published benchmarks. Visual lensing is not evidence of relativistic dynamics.

## 8. Specialised simulation modes

Evaluate tree gravity for large populations, statistical debris, dedicated gas
or impact hydrodynamics, and averaged long-term evolution where justified by an
intended experience and measurements on accessible hardware.

Acceptance: each selected mode has a defined domain, physical references,
accuracy controls, and performance measurements. Hybrid coupling needs separate
conservation and convergence tests; full general relativity is outside this plan.
