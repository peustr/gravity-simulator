# Scene quality standard

The interactive sandbox is the product. Numerical unit tests are necessary but
do not establish that a scene is usable or that its physical model is adequate.
Every built-in scene must pass the same release process.

## Required gates

| Gate | Required evidence |
|---|---|
| Scientific validity | Declared model/domain, independent analytical or published references, convergence, and uncertainty/approximation limits. A conserved result can still be physically wrong. |
| Physical transitions | Finite positive states; explained mass, momentum and energy transfers; local creation of material; no instantaneous redistribution across a scene or mass-only stellar ignition presented as physical evolution. |
| Scene purpose | The process in the table below occurs through shared physics. Initial conditions, physical duration and playback speed are recorded. |
| Continuous presentation | An uninterrupted, timestamped sequence includes startup, approach, the peak event and aftermath. Inspect the peak frame as well as the final frame. |
| Interaction | Load, play/pause, speed changes, select/follow, zoom, placement/forecast, save/load/restart and scene switching remain coherent. No lost selection, stale bodies or unexpected welcome/confirmation overlays. |
| Performance | Measure frame intervals, hitches and achieved simulation rate on documented consumer hardware. Recording/software-renderer timings cannot certify consumer-GPU performance. |

A failed gate blocks release. An unavailable renderer, absent reference, missing
sequence or unmeasured hardware target is **BLOCKED**, not PASS. Reports identify
the exact revision, engine, renderer, device, seed and settings. Relevant evidence
is invalidated by subsequent changes. Unit-test counts and coverage are not
release criteria.

## Scene promises

| Scene | Observable acceptance |
|---|---|
| Solar system | The eight planetary primaries start with plausible masses/orbital scales and remain bound over the declared reference interval. Moon close-ups and orbital forecasts remain smooth and legible. |
| Binary stars | The stellar binary stays bound over multiple orbits. Perturbations/ejections follow dynamics; the camera and playback remain coherent. |
| Black hole feast | Stellar material deforms/disrupts locally; captured mass grows the hole and surviving debris follows explainable trajectories. Gas is distinguishable from stars. Birth geometry, momentum and the capture prescription are validated, including resolution dependence. |
| Planet smash | Merging, hit-and-run and disruption approach physical contact, preserve their supported budgets and leave inspectable outcomes. Effects remain localized and do not obscure the event. |
| Planet formation | A planetary disk is visible in context. At least one body grows through multiple generations of accretion from three or more initial embryos; changing to a single staged pair is not equivalent. Repeat accretion remains within the model's supported domain. |
| Tidal encounter | Both disks and their encounter are visible. Tails arise continuously through gravitational interaction. Particle removal, coalescence and capture require a model appropriate to the represented material. |
| Empty space | The empty clock and pause state behave correctly. Placement, previews, follow, editing, save/restart and clear operate without inherited scene state. |

The reference interval and performance budget are part of each scene's contract.
The backend observes 12 seconds of preset playback, or 40 seconds for Formation's
cold embryo concentration within a disk. It finishes the requested physical interval
within a separate wall-time cutoff; achieved interactive rate is measured separately.
Long physical timescales require suitable model/time controls and honest labels;
visual flashes, hidden force changes and geometric enlargement cannot substitute
for the promised process.

## Automated and human review

- Run the scene audit for **all** presets, not only scenes mentioned in a bug
  report. It reports each promise and common invariant separately, including
  missing coverage. A failure cannot be suppressed by increasing a tolerance or
  redefining the scene's promise to fit its current output.
- Capture every rendered frame for transient brightness analysis. Save a timed
  frame sequence and the brightest frame. For the default camera/control paths,
  a cosmetic effect whitening more than 35% of the viewport is a failure.
- Record the documented target engine/renderer. A fallback is useful diagnostic
  evidence but cannot approve a different rendering path. Headless checks cannot
  approve appearance.
- Watch each full sequence at normal playback speed. Check spatial continuity,
  object/material identity, contact timing, camera behavior, readability and
  visual consistency. Numerical reports and still images do not replace this.
- A physics change also needs its independent reference checks. A presentation
  change must retain the same authoritative physical state.

CI must publish per-scene reports and rendered evidence and fail on automated
regressions. Release additionally requires review of the complete sequences and
documented performance evidence on an accessible hardware class. An unvalidated
physical prescription remains a model gap even if the image is attractive.
