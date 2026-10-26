# Impact scaling and classification

`physics_server/disruption.py` provides head-on numerical primitives and a
classifier for supported solid-body contacts. The live collision handler does
not call them. Neither calculation creates particles or assigns velocities.

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

## Contact API

`classify_contact(impact, unit_system=..., material=..., body_types=(A, B))`
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

With target radius R, projectile radius r and b = sin θ, grazing starts at
b = R/(R+r), including a 10⁻¹² absolute rounding allowance. This boundary is an
idealisation; actual near-boundary impacts can mix disruption and hit-and-run.
Unsupported inputs raise `ValueError`; none falls back to merging.
`classify_non_grazing` accepts the same arguments but rejects all grazing contacts.

## Non-grazing outcomes

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

## Grazing outcomes

Grazing additionally requires `fluid_planets`, two ROCKY bodies, total mass
0.2–2 Earth masses, γ ≥ 1/9 and θ ≤ 75°. Mass limits allow 10⁻¹² relative
rounding slack; the angle limit allows 10⁻¹² in b. Grazing planetesimals remain
unsupported. These screens do not establish a calibrated result at every
combination of size, density, angle and speed.

[Genda, Kokubo & Ida (2012)](https://arxiv.org/html/1109.4330), equation 16,
provides the graze-and-merge boundary for nonspinning rocky protoplanets. Its
samples cover γ = 1/9–1, θ = 0–75° and v = 1–3 times mutual surface escape speed.
We use the equation in the linked preprint with **linear** Γ:

```text
Γ = (1−γ)/(1+γ)
v_esc = sqrt[2G(Mt+Mp)/(R+r)]
v_merge/v_esc = (2.43Γ + 1.86)(1−b)^(5/2) − 0.0408Γ + 1.08
```

The surface escape normalisation differs from the non-grazing interacting-mass
scale. At x ≥ 2Mp/(Mt+Mp), LS12 erosion/disruption takes precedence. Otherwise,
v < v_merge gives `graze_and_merge` (all mass in one eventual remnant), and
v ≥ v_merge gives `hit_and_run`. The label describes the eventual outcome,
not a simulated separation and return. Higher-energy target erosion still
uses LS12; the Genda fit supplies only the low-speed merging boundary.

In hit-and-run, the idealised target retains Mt. LS12 equations 46–52 estimate
the runner by reversing the impact: a chord volume from the target strikes Mp.
For l = (R+r)(1−b), h = l/r and common density ρ:

```text
A = r² [acos(1−h) − (1−h)sqrt(h(2−h))]
L = 2 sqrt(Rl − l²/4)
M_interact = ρ A L
M_runner = min(Mp, head_on_largest_remnant(Mp, M_interact, v))
M_unassigned = Mp − M_runner
```

The cap prevents counting the intact target's material twice. This model omits
target erosion during hit-and-run and material exchange. Tests check analytic
chord volumes, independent area quadrature, intact/eroded runners, Genda's
Figure 2 outcomes, selected reported critical speeds within 0.04 v_esc fit error,
regime boundaries, units, symmetry, exclusions and mass closure across a grid.
Fit error is distinct from numerical rounding and the paper's ±0.01 v_esc
transition sampling uncertainty.

## Result and limitations

`ContactOutcome` is immutable and independent of particle capacity. It returns
the regime, largest-remnant mass, `runner_mass_kg`, remaining unassigned mass,
Q_R and Q'*_RD in J/kg, α and `merging_speed_m_s`. That speed is V'_esc for
non-grazing contacts and the Genda boundary for grazing contacts. All masses
are in kg and their sum equals the incoming inventory within floating-point
rounding. Runner mass is zero outside hit-and-run; it does not estimate the
second-largest fragment of a disruptive event. Such fragments remain unassigned.
The separate [spherical merger constructor](collision-budgets.md) accounts for
spin and energy when a single remnant is feasible; it is not connected to this
classifier. Runner/fragment velocities, energy partitions and live application
require further models. Classification's mass closure alone does not establish
momentum, angular-momentum or energy conservation.
