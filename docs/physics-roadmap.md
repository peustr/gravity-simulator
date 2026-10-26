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

Complete these checkpoints in order:

- [x] **4.1 Contact measurements:** capture immutable pre-merge state, contact
  angle, relative kinetic energy and orbital angular momentum. Check analytic
  values, coordinate/body-order invariance and capture through native merging.
- [x] **~~4.2 Calibrated classification~~:** select and document impact laws and
  their mass, velocity, material and geometry domains. Compute accretion,
  erosion, disruption and hit-and-run classifications and remnant masses
  independently of particle capacity; validate reference and boundary cases.
- [ ] **4.3 Conserved outcomes — next:** generate remnants and fragments with accounted
  mass, momentum, orbital/remnant spin angular momentum and energy partition.
- [ ] **4.4 Unresolved debris:** preserve material and its physical budgets in
  an accounted reservoir/statistical model when explicit particle capacity runs
  out; verify capacity changes cannot change the selected collision regime.
- [ ] **4.5 Integration and validation:** apply the validated laws in their
  supported domains, migrate persistent physical state, validate grazing and
  reference impacts, and measure runtime on the representative workloads.

Current measurement contract and model limits: [impact measurements](impact-measurements.md).

Checkpoint 4.2 implementation steps:

- [x] **4.2a Head-on disruption curves:** explicit material calibrations and SI
  inputs, mass-ratio scaling, largest-remnant mass and super-catastrophic branch;
  published curve references, dimensional checks and boundary tests.
- [x] **4.2b Non-grazing classification:** enforce applicability and unit
  conversion, account for oblique interacting mass, and distinguish merging,
  partial accretion, erosion and disruption independently of particle capacity.
  Check reference geometry, regime boundaries and unsupported inputs.
- [x] **4.2c Grazing classification:** distinguish graze-and-merge from
  hit-and-run, estimate both surviving remnants and unassigned mass, and validate
  reference encounters and boundaries without consulting particle capacity.

Classification acceptance: the documented solid-body domains have explicit
rejection outside their limits, published curve/geometry and grazing references,
boundary and invariance checks, and closed remnant/unassigned mass inventories.
Grazing support is limited to rocky protoplanets; grazing planetesimals need a
separate calibrated merging law. Creating particles and closing momentum,
angular-momentum and energy budgets belong to 4.3–4.5.

Numerical model and API: [impact scaling](impact-scaling.md).

Acceptance: representative impacts match reference outcomes and close their
mass, momentum, angular-momentum, and energy budgets within documented errors;
particle limits do not silently change the collision regime.

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
