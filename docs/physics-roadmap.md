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

## Milestones

- [x] ~~1. Accuracy and performance baseline~~
- [x] ~~2. Physical units and independent display sizes~~
- [x] ~~3. Trustworthy orbital dynamics~~
- [ ] **4. Credible impact outcomes — active**
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

**Incomplete.** Completion requires calibrated solid-body impacts in the running
sandbox, conserved physical inventories, useful unresolved-debris evolution at
particle limits, and measured accuracy/performance. Standalone model tests and
isolated-merger support do not satisfy that goal.

### Current implementation

| Component | Available behavior | Remaining limitation |
|---|---|---|
| Contact state and saves | Immutable pre-impact measurements; version-4 body spin/internal-energy inventories | Older or heuristically transformed bodies have unknown inventories |
| Classification | Calibrated solid-body regimes and remnant masses within documented domains | Most classified outcomes are not applied live |
| Outcome construction | Automatic dispatch uses conserved rocky outcomes in every preset; weak external fields are screened and their interaction energy is accounted for | Ejecta layout/energy split are prescribed; strong fields, simultaneous contacts, spinning inputs and insufficient fragment slots are rejected |
| Unresolved material | Snapshot inventories, restricted cloud transport and bounded ownership APIs | No live coupling or persistence; transport cannot represent debris surrounding its remnant or general multi-body interactions |
| Diagnostics | Orbital quantities and removal accounting | No complete live spin, internal-energy and reservoir ledger |

### Delivery requirements

This is the complete delivery checklist for Milestone 4. Implementation batches
may address part of an item; they do not create additional numbered milestones.
An item closes only when its runtime behavior and acceptance checks are delivered.
Changing these requirements or supported domains requires an explicit scope decision.

- [ ] **Live calibrated outcomes.** Apply merging, graze-and-merge, partial
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
- [ ] **Operational unresolved debris.** Choose and implement a representation
  that can evolve the ejecta produced by the live outcome policy, including its
  interaction with remnants and other bodies. Coordinate shared-body updates,
  ownership and bounded storage; preserve complete inventories through transfers.
  Changing explicit-particle capacity must not change the classified regime or
  discard material. Demonstrate the same impact with resolved and unresolved
  debris and bounded error against a resolved reference. Full storage or exceeded
  model limits must leave the encounter unapplied. The existing far-field,
  outward-cloud solver is insufficient for this requirement; resolve that
  representation mismatch before extending its lifecycle machinery.
- [ ] **Complete accounting and persistence.** Report mass, linear momentum,
  orbital plus spin angular momentum, and kinetic, binding, mutual and internal
  energies across bodies and unresolved material. Separate numerical error,
  approximation error and explicit losses. Save/restart must retain reservoirs,
  model parameters, error history and ownership without changing future behavior
  beyond documented integrator restart differences. Preserve old-save migration
  and clearly expose the active collision model and unsupported states.
- [ ] **Release validation and maintenance.** Exercise every supported regime,
  grazing boundaries, populated scenes, successive contacts, capacity changes and
  save/restart through the live path. Require reference agreement and complete
  budget closure within documented numerical/model tolerances. Measure the
  existing representative workloads against the performance targets above and
  verify rendered Solar System smoothness. Pass repository checks, self-tests
  and CI. Consolidate superseded or unused implementations and duplicate prose;
  keep one documented runtime path per supported model.

### Scope and completion boundary

Mass-outcome calibrations retain their published applicability limits. Ejecta
layouts and energy fractions remain explicit modelling prescriptions unless
independently calibrated. General rotating-impact laws, tidal evolution,
thermodynamic/composition models, gas/stellar/compact-object collision laws and
hydrodynamics belong to later milestones. Research extensions such as general
cloud coalescence or resampling are optional unless the chosen live debris model
needs them to meet the requirements above.

Milestone 4 closes when users can enable the calibrated model in the application,
run the supported reference encounters in populated scenes, retain material and
budgets across capacity limits and restart, and meet the validation gates.
The isolated two-body demo alone is insufficient. General-purpose impact support
outside the stated domains is not claimed.

Implementation contracts: [impact measurements](impact-measurements.md),
[calibration domains](impact-scaling.md), [collision budgets and live mode](collision-budgets.md),
[debris inventories](unresolved-debris.md), [current transport limits](debris-transport.md),
and [reservoir ownership](debris-lifecycle.md).

## 5. Rotation and tidal evolution

Track spin and orientation; implement validated tidal dissipation,
circularisation, synchronisation, and relevant rotational flattening. Improve
disruption criteria and debris energy/angular-momentum distributions. Expose
uncertain material/dissipation parameters.

Acceptance: benchmark systems reproduce expected secular evolution at measured
cost, with explicit validity limits.

## 6. Composition and thermal history

Track bulk rock/metal/ice/gas, irradiation, albedo, thermal emission, internal and
impact heating, approximate phase changes, atmosphere retention/loss, and
consistent radius changes. Begin with globally averaged thermal models.

Acceptance: stellar flux, orbital distance, and deposited energy produce
quantitatively checked responses. Detailed climate is a separate model.

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
