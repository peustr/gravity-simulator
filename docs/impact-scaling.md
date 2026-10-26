# Impact scaling and non-grazing classification

`physics_server/disruption.py` provides head-on numerical primitives and a
restricted non-grazing classifier. The live collision handler does not call
them. Neither calculation creates particles or assigns fragment velocities.

## Reference model

[Leinhardt & Stewart (2012), ApJ 745, 79](https://doi.org/10.1088/0004-637X/745/1/79)
([open paper](https://arxiv.org/abs/1106.6084)), equations 5, 23, 28 and 44:

For total mass M, smaller/larger mass ratio γ and reference density
ρ₁ = 1000 kg/m³, define R_C1 = (3M / 4πρ₁)^(1/3).

```text
Q_equal = c* (4/5) π ρ₁ G R_C1²
Q*_RD   = Q_equal [(1 + γ)² / (4γ)]^[2/(3μ̄) − 1]
Q_R     = ½ [γ / (1 + γ)²] v²
x       = Q_R / Q*_RD
M_lr/M  = 1 − x/2                 for x ≤ 1.8
        = 0.1 (x/1.8)^(-1.5)      for x > 1.8
```

| Explicit calibration | c* | μ̄ | Source domain |
|---|---|---|---|
| `fluid_planets` | 1.9 ± 0.3 | 0.36 ± 0.01 | Strengthless planetary impacts |
| `planetesimals` | 5 ± 2 | 0.37 ± 0.01 | Gravity-dominated small-body compilation |

Central values are used. Section 3.1.4 and Table A.2 describe the fits: small-body
targets span roughly 0.3–100 km; planet targets include about 0.1–10 Earth masses.
The compiled critical speeds span metres/second to tens of kilometres/second.
These are calibration coverage descriptions, not universal validity bounds.
Material strength, porosity and spin can substantially change outcomes.

## Head-on curve API

`estimate_head_on_disruption(mass_a_kg, mass_b_kg, speed_m_s, material=...)`
requires positive finite masses, nonnegative finite contact speed and an explicit
calibration. It returns Q*_RD and Q_R in J/kg, the largest-remnant mass, and the
remaining mass in kg. `largest_remnant_fraction(x)` also exposes the dimensionless
curve. Results are immutable and independent of particle capacity.

Inputs are **SI**, not scene units. No default material, scene conversion, body
type mapping or radius inference is supplied. Reference density is a
normalisation, not the actual body density. The caller must establish head-on
geometry and material applicability; the function cannot check either from
scalar masses and speed. It must not be used directly on arbitrary contacts.

The zero-energy limit is mathematical. Selecting perfect merging, accretion,
erosion or disruption requires additional collision logic. Oblique and
hit-and-run encounters, strength-dominated objects, gas envelopes, stellar and
compact objects, relativistic speeds and rotating targets have no supported
outcome calculation here. Remaining mass has no assigned fragment sizes,
velocities, composition or energy partition.

## Verification

Tests compare the dimensionless curve with rounded Table 1 predictions using
that table's fitted threshold. A separate check compares the global small-body
calibration with the equal-mass threshold within its 40% parameter scatter;
this is distinct from numerical error. Analytic checks cover binding energy,
the mass-ratio exponent, scale changes, exchange symmetry, the transition at
x = 1.8 and mass accounting. They do not establish hydrodynamic accuracy across
the full calibration domain.

## Non-grazing contact API

`classify_non_grazing(impact, unit_system=..., material=..., body_types=(A, B))`
accepts the immutable `Impact` measurements. Unit system must be `si` or the
physical scene identifier `au60-solar1000-v1`; legacy scenes are rejected.
Masses, radii, relative vectors and gravity are converted together. Material
selection is explicit. Both body types must be ROCKY (0) or ASTEROID (5).

The classifier assumes nonrotating, spherical, gravity-dominated solids with
equal bulk densities. It applies the following implementation envelope:

| Calibration | Larger body's size | Smaller/larger mass ratio | Contact speed |
|---|---|---|---|
| `fluid_planets` | 0.1–10 Earth masses | 0.1–1 | 0 < v ≤ 80 km/s |
| `planetesimals` | 1–100 km radius | 0.025–1 | 0 < v ≤ 5 km/s |

One Earth mass here is 5.9722 × 10²⁴ kg. These limits are engineering screens
informed by the reference coverage, not measured validity boundaries for every
combination. Choosing a calibration asserts its material assumptions; type and
density alone cannot establish strength, porosity or internal structure.

All values must be finite, with positive masses/radii and physical Newtonian G.
Both densities must be 1000–8000 kg/m³ and agree within 10⁻⁶ relative tolerance.
Size, mass-ratio and density endpoints allow 10⁻¹² relative rounding slack.
The pair must approach with centre separation within 10⁻⁴ of the summed physical
radii. This admits shallow sampled overlap, not arbitrary initial interpenetration.
The measured angle is used without extrapolation to exact contact.

With target radius R, projectile radius r and b = sin θ, require b < R/(R+r).
Equality and all grazing contacts raise `ValueError`, including slow contacts.
Other unsupported inputs also raise `ValueError`; none falls back to merging.
This geometric boundary is an idealisation: actual near-boundary impacts can
contain features of both disruption and hit-and-run.

LS12 equations 11, 12, 15 and 53 give the oblique corrections:

```text
l = min(2r, (R+r)(1−b))
α = (3r l² − l³)/(4r³)
μ_α = α Mp Mt / (Mt + α Mp)
Q'*_RD = Q*_RD (μ/μ_α)^[2 − 3μ̄/2]
R' = (R³ + α r³)^(1/3)
V'_esc = sqrt[2G(Mt + α Mp)/R']
```

The energy Q_R still uses the full pair's reduced mass; the interaction
correction applies to the threshold. Below V'_esc all mass merges. Otherwise
use x = Q_R/Q'*_RD and the largest-remnant curve:

| Regime | Condition after the merging check |
|---|---|
| `partial_accretion` | x < 2Mp/(Mt+Mp) |
| `erosion` | 2Mp/(Mt+Mp) ≤ x < 1 |
| `disruption` | 1 ≤ x < 1.8 |
| `supercatastrophic_disruption` | x ≥ 1.8 |

Energy-boundary equality belongs to the higher-energy regime. The perfect-merger
gate is strict and introduces a prescribed mass jump; it is not a smooth
dissipation calculation. Tests probe both sides of each boundary, the
equal-density assumption, Table 1 interacting fractions, oblique energy scaling,
body exchange, rotation, scene-to-SI conversion and input exclusions.

`ContactOutcome` returns the regime, largest/remaining mass in kg, Q_R and
Q'*_RD in J/kg, α, and V'_esc in m/s. The result is immutable and independent of
particle capacity. Remaining mass is unassigned: no second-remnant, spin,
fragment distribution or energy budget is calculated. Grazing/hit-and-run
classification and live application are separate roadmap steps.
