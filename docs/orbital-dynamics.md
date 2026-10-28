# Orbital dynamics and accuracy controls

The live solver uses REBOUND IAS15 with Newtonian, unsoftened gravity.
Physical scenes default to `epsilon = 1e-9` and `min_dt = 0`: difficult encounters
slow simulated time instead of imposing an inaccurate timestep floor.
Version-1 legacy scenes retain their original `min_dt = 1e-4`; the physical
reference gates below do not certify that legacy model.

## Contact handling

`physics_server/dynamics.py` limits proposed steps using pairs'
surface gaps, radial closing speeds and pair escape speeds. No step crosses
the next guard check. Pair checks are reused across shorter native steps and
invalidated after edits, collisions and fragment generation. Near contact,
the guard allows travel on a scale of `1e-4` of the summed physical radii so
REBOUND's direct overlap detector can resolve contact. Separating ejecta can
leave overlaps; outside surfaces, outgoing pairs are rechecked using their
mutual-gravity turnaround timescale. IAS15 still controls gravitational integration error.

This avoids tunnelling in the tested fast/grazing encounters and stops radial
capture before the singular centre. It is not an exact continuous collision
solver or a proof for arbitrary simultaneous many-body encounters. Contact
geometry and velocities are numerical approximations with the tested bounds
below. Impact outcomes, tides and fragment generation remain separate models.

IAS15's global predictor convergence ratio is undefined when all accelerations
are zero. For exactly force-free states (one body, no active gravitating bodies,
or zero G), the step uses IAS15's individual convergence criterion and restores
the configured criterion afterwards. It does not suppress convergence warnings
or loosen gravitational tolerances. Contact detection remains active.

## Explicit approximations

The **Physics** section of the **Experiment** menu provides these options:

- **Full gravity, including debris:** every particle exerts gravity. With this
  unchecked, asteroids and plasma below 0.5 mass units are passive tracers.
  Tracers feel active bodies' gravity but exert none, including on each other.
  Their nonzero masses still participate in contacts and inventories. The menu
  reports their collective mass fraction; a small fraction alone does not bound
  local force errors. Choose full gravity for self-gravitating debris.
- **Include all bodies in forecasts:** include the current scene and proposed
  body with the same full/tracer force partition. With this unchecked, select
  up to 20 bodies by gravitational influence plus the selected attractor.
  Omitted forces and contacts have no general error bound. Tracer masses do not
  contribute to the influence ranking or act as placement attractors.
- **Remove bodies beyond the boundary:** remove bodies outside a sphere centred
  on the fixed simulation origin. The default is 15,000 length units (250 AU).
  This is a computational boundary, not a test that a body is unbound. Disable
  removal for long excursions or translating systems. Re-enabling the menu
  option restores the default distance.

Defaults retain tracer gravity, a 20-body forecast limit and the removal
boundary. Full gravity can cost more for large debris populations; it never
silently falls back to tracers. Switching force models changes the equations
and their conservation properties; set a new restart point for comparisons.
Clear and built-in presets retain the selected physics settings.

Version-3 saves and restart points retain these settings and cumulative removal
inventory: body count, mass, momentum, orbital angular momentum and the change
in all-body Newtonian mechanical energy at removal. An `energy_defined` flag
records undefined potential at coincident centres; other losses remain counted.
This inventory is not a radiation model. Clearing/loading a preset starts a new
inventory. Version-1/2 files receive the previous default approximation choices;
their stored body values and unit model are preserved.

The validated `physics` command accepts partial updates to `settings`; version-3 and newer
files store the complete `physics` object:

```json
{"gravity":"full","epsilon":1e-9,"forecast_limit":0,"escape_distance":null,"collisions":"heuristic"}
```

`epsilon` accepts `1e-12` through `1e-6`; `forecast_limit` accepts 0 (all bodies)
or 1–1321; `escape_distance` accepts a positive distance up to `1e9` or null.
Advanced values can be set through a scene file or the protocol. The server's
periodic info response reports current settings, tracer mass and removal totals.
`collisions` defaults to `heuristic` when omitted from older saves. The opt-in
`isolated_mergers` and `isolated_impacts` modes require full gravity, physical units and no removal
boundary; see [supported live collisions](collision-budgets.md#live-isolated-mergers).

## Forecast scope and deadlines

Forecasts use a copied initial state, the live tolerance/minimum timestep and
the same contact guard. They stop at the first contact between any included
bodies, without inventing post-impact outcomes. Only contact with the proposed
body produces an impact marker. Background tides, explosions, escape removal
and subsequent edits are not forecast.

The 25 ms interactive budget is checked before every native step, including
inside an unfinished path sample. Expiry returns the finite partial path;
sampling only moves forward and never exceeds its target time. A single native
step and setup can exceed the budget, so this is not a hard deadline. A short
line does not imply a collision. All-body forecasts can be shorter because of
their higher cost; included forces still follow the selected scene model.

## Repeatable accuracy gates

Run `python3 tools/dev.py accuracy`. JSON reports go to ignored `benchmarks/`
and include machine/solver versions, errors, limits and solver timings.

| Reference | Horizon / variations | Acceptance |
|---|---|---|
| Circular and eccentric Kepler orbits | 1,000 periods; eccentricity 0 and 0.6 | Relative position error ≤ `1e-6` of semimajor axis; normalised energy error ≤ `1e-9` |
| Tolerance sweep | Eccentricity 0.8, 100 periods; epsilon `1e-6`, `1e-9`, `1e-12` | Default/tight position error ≤ `1e-7`; refinement does not increase error beyond the larger of the loose-tolerance error and a `1e-8` roundoff/phase floor |
| Hierarchical star–planet–moon | 100 planetary periods | Default vs `1e-12` relative positions agree within `1e-6` length units; normalised energy error ≤ `1e-9` |
| Fast contacts and near misses | Rectilinear speed 10,000; impact parameters 0, 0.999 and 1.001 summed radii; two initial dt and epsilon choices | No missed hits or false hits; penetration ≤ `1e-4` radius; contact-time error ≤ `0.002` surface-crossing times |
| Radial Newtonian capture | Analytic free fall, including initially receding bound trajectories that turn around, with the same dt/tolerance sweep | Same contact bounds; impact speed error ≤ `1e-4` |
| Forecast/live force consistency | One perturbed moon orbit, both gravity modes, all bodies | Position agreement ≤ `1e-7` length units; separately report omitted-mass error for limited forecasts |
| WHFast evaluation | Two separated planets, 200 inner periods, 40/80 steps per inner orbit | Normalised energy error ≤ `1e-5`, reduced by at least half with refinement |

Energy error is divided by initial kinetic energy plus the magnitude of initial
potential energy. Short-orbit, hyperbolic scattering, hierarchy and
merger conservation gates also run. Results apply to these problems, horizons
and sampled states; they do not guarantee arbitrary chaotic trajectories.

WHFast is evaluated only on an isolated, conservative planetary benchmark.
Its fixed timestep requires resolving the shortest orbit and it lacks this
application's validated encounter/contact path. It is not offered as a live
solver. IAS15 remains the general-purpose choice for moons, encounters and edits.

Measure runtime separately, with repeated runs on the same hardware:

```sh
python3 tools/dev.py benchmark --profile
python3 tools/dev.py benchmark --gravity full --forecast-limit 0
```

These commands measure achieved speed, tick/forecast latency and the cost of
the selected approximations. Measure rendering separately with `benchmark-visual`.

References: [IAS15, Rein & Spiegel (2015)](https://arxiv.org/abs/1409.4779),
[WHFast, Rein & Tamayo (2015)](https://arxiv.org/abs/1506.01084), and
[REBOUND IAS15 implementation](https://github.com/hannorein/rebound/blob/main/src/integrator_ias15.c).
