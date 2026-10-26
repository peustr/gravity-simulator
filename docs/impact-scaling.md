# Head-on disruption scaling

`physics_server/disruption.py` provides standalone numerical primitives. The live
collision handler does not call them. They calculate disruption curves, not a
complete collision classification or a particle outcome.

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

## API contract

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
