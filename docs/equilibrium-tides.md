# Equilibrium tides

Configured solid spheres use a linear quadrupolar constant-time-lag model.
The response includes all resolved perturbers together, including cross terms
between their fields. Gas and stellar deformation, dynamical tides, fluid flow
and unresolved ejecta coupled to deformable bodies are outside this model.

For the trace-free external tidal tensor `E = Σ Gm/r³ (3nnᵀ − 1)`, define
`c = k₂R⁵/(6G)` and its material derivative `D = dE/dt − [Ω×, E]`.
Stored tidal energy is `−c(E:E)/2`; dissipation is `c Δt (D:D) ≥ 0`.
Differentiating this potential and the Rayleigh function gives Cartesian forces;
the source receives their reaction and the opposite orbital torque. Heat enters
the existing internal-energy inventory. Moment of inertia remains `2MR²/5`.
The isolated-pair limit is the Mignard force in
[Wisdom & Tian (2015), equations 3–4](https://web.mit.edu/wisdom/www/wisdom-tian.pdf).

The supported domain requires full gravity, known solid inventories, exterior
perturbers, at most 16 deformable solids, total forcing
`Σ(m/M)(R/r)³ ≤ 0.01`, rotational deformation `Ω²R³/(GM) ≤ 0.01`, and
`Δt |D| ≤ 0.1 |E|`. The forcing rate `|D|/|E|` must stay below 0.2 times
the body's dynamical frequency. Unsupported evolution pauses with an explanation.
Other solids have unspecified tidal material properties until configured.

Close planetary encounters can leave this weak-deformation domain before
contact. Disable the participating body's equilibrium tide to use the spherical
calibrated collision model. This model does not extrapolate weak tides through
strongly deforming impacts.

Symmetric tidal kicks surround native adaptive gravity integration. An implicit
midpoint solve couples orbital velocities and spin and deposits its positive
dissipation. A separate trial state permits step rejection without changing live
inventories. Phase, energy and attitude checks bound each complete step.
`physics.tidal_phase` controls the phase limit, from 0.01 to 0.2; smaller values
resolve tidal forcing more finely. Forecasts use the same model on their included
bodies, subject to their existing time and body limits.

## Scenes and controls

Solar System configures Earth with `k₂ = 0.299`, `Δt = 638 s`, and the Moon
with `k₂ = 0.024`, `Δt = 100 s`. These are adopted constant-response parameters,
not a frequency-dependent calibration of oceans or lunar rheology. Present-day
evolution is slow; the inspector reports spin/orbit ratio, osculating eccentricity,
power and deposited energy. Spin/orbit Δ is measured since observation began.
Osculating eccentricity includes periodic variations; secular damping is much
slower than one orbital period.

**Scenarios → Solar System · lunar tides** isolates the existing Earth–Moon pair.
Press Play to begin. Earth is rigid in this experiment; the Moon starts on an eccentric orbit at six
Earth radii, spinning at 1.2 times the mean orbital frequency. The lunar material
coefficients are unchanged. This is a controlled satellite experiment, not a
reconstruction of early lunar history. It exposes measured synchronising spin
and gradual eccentricity damping without making tides artificially faster.

Select a solid and use **Tides…** to edit its Love number and time lag. A zero
Love number disables deformation. Changes are explicit user edits in conservation
accounting. Deposited joules do not imply a temperature or drive artistic glow.
Version-9 saves retain material constants and deposited heat; older files remain
readable with their previous force model and no invented tidal properties.
