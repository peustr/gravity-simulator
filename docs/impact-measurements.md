# Impact measurements

`physics_server/impacts.py` captures an immutable pair state before the native
collision callback changes either body's mass, position or velocity. Each
deferred collision record carries it as `impact`. It owns scalar values and
tuples, so merging, removal and native particle-array growth cannot alter it.
A is the callback's designated survivor, B the other body; A is not necessarily
the more massive body. Inputs use the scene's existing simulation units and
physical contact radii, including legacy radius rules for legacy scenes.

The record also carries `spheres`: immutable absolute SI states with spin and
internal energy when those inventories are known. See the
[persistent inventory contract](collision-budgets.md#persistent-body-inventories)
for unknown-state handling, chained collisions and save migration.

For relative position **r** = **x**B − **x**A, relative velocity **v** = **v**B − **v**A,
total mass M and reduced mass μ = mA mB / M:

| Quantity | Definition |
|---|---|
| Normal | **r** / \|**r**\|, from A to B |
| Radial speed | **r** · **v** / \|**r**\|; negative for approach |
| Impact parameter b | \|**r** × **v**\| / (\|**r**\| \|**v**\|), equal to sin θ |
| Relative kinetic energy | ½ μ \|**v**\|², measured in the pair's centre-of-mass frame |
| Specific impact energy Q_R | Relative kinetic energy / M |
| Pair orbital angular momentum | μ (**r** × **v**), about the pair's centre of mass |
| Mutual surface escape speed | √[2 G M / (RA + RB)] |

Head-on motion has b = 0 and tangential motion b = 1; the radial speed
distinguishes approach from separation. The angle is measured at the detected
overlap, without extrapolation back to exact surface contact. Coincident centres
have undefined normal, radial speed and b; zero relative speed also leaves b
undefined. These values are `None`. Zero summed radii leave the surface escape
speed undefined. For zero total mass, reduced mass and both kinetic-energy
measures are zero.

These measurements use physical masses even for passive tracers. Escape speed
is a physical-mass reference scale, not a change to the selected force model.
Angular momentum excludes body spin; kinetic energy excludes gravitational
potential, self-binding and thermal energy. Recording these quantities does not
establish conservation across the generated collision outcome.

Automatic dispatch uses calibrated outcomes for rocky pairs and heuristic
models for other pairs, including stellar and compact-object rules. The heuristic disruption threshold and fragment
prescription are not a calibrated material model, and available particle slots
can still turn fragmentation into a merger. The captured measurements do not
classify hit-and-run events or assign remnant spin.

The standalone [impact scaling API](impact-scaling.md) provides SI head-on curves
and solid-body classification, including supported rocky grazing contacts, with
explicit scene-unit conversion.
The [calibrated modes](collision-budgets.md#live-isolated-mergers) call
the conserved outcome constructor after the native step. They defer all
particle changes until validation succeeds; unsupported encounters pause intact.

`tests/test_impacts.py` checks hand-calculated oblique impacts, head-on and
tangential geometry, body exchange, translation, velocity boosts, rotation,
degenerate states and capture before native merging/fragmentation.
