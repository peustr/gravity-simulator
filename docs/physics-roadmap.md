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

Hardware compatibility/performance qualification is ongoing across machines.
No individual's hardware or personal benchmark is a prerequisite for development.

Work in order. A milestone is complete only when its acceptance criteria and
required checks pass. Mark its checklist entry `[x]`, strike through its title,
and make the next milestone active. Keep this document as the current plan;
store generated measurements in ignored `benchmarks/`, not in this document.

## Milestones

- [x] ~~1. Accuracy and performance baseline~~
- [x] ~~2. Physical units and independent display sizes~~
- [ ] **3. Trustworthy orbital dynamics — active**
- [ ] **4. Credible impact outcomes**
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

Validate close encounters and collision detection; revisit the IAS15 minimum
timestep; evaluate symplectic integration for eligible long-lived planetary
systems. Investigate IAS15 convergence warnings during radial compact-object
capture, and bound forecast work between native integration calls to meet the
forecast latency target without loosening accuracy. Make tracer/full gravity
choices explicit, considering collective
debris mass. Define removal boundaries and forecast accuracy limits.

Acceptance: documented long-duration error targets and convergence under tighter
tolerances; no missed benchmark contacts; explicit approximation settings and
measured runtime cost. Solver switching requires its own validation.

## 4. Credible impact outcomes

Model accretion, erosion, disruption, and hit-and-run encounters using calibrated
impact laws. Include geometry, material, spin, and energy partition. Preserve
unresolved debris in an accounted reservoir/statistical model when particle
limits prevent explicit fragments.

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
