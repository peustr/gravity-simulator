# Physical units and contact sizes

New scenes use `au60-solar1000-v1`. Python's `units.py` is authoritative;
the protocol supplies its conversion factors to the client.

| Quantity | One simulation unit in SI |
|---|---|
| Length L | 149,597,870,700 / 60 metres |
| Mass M | (1.3271244 × 10²⁰ / G) / 1,000 kg |
| Time T | √(L³ / GM) seconds |
| Velocity | L / T m/s |
| Density | M / L³ kg/m³ |

These definitions give dimensionless `G = 1`. The AU is the exact
[IAU 2012 definition](https://www.iau.org/static/resolutions/IAU2012_English.pdf).
Solar GM = 1.3271244 × 10²⁰ m³/s² and solar radius = 6.957 × 10⁸ m are
[IAU 2015 nominal conversion constants](https://arxiv.org/abs/1510.07674).
[CODATA](https://physics.nist.gov/cgi-bin/cuu/Value?bg) gives
G = 6.67430 × 10⁻¹¹ m³ kg⁻¹ s⁻²; inferred masses inherit G's measurement
uncertainty. The speed of light is exactly 299,792,458 m/s.

## Radius approximations

REBOUND's particle `r` is always the contact radius, in simulation length units.
It is used for overlap rejection, collisions, forecasts, escape-speed estimates
and disruption. A saved radius is restored exactly, even if it differs from the
default model; mass/type-changing events calculate a new model radius.

| Body | Default physical radius |
|---|---|
| Rocky | Uniform bulk density 5,514 kg/m³, approximately Earth-like |
| Asteroid | Uniform bulk density 2,000 kg/m³ |
| Gas giant | Jovian mean radius × min(1, (mass / Jupiter mass)^(1/3)) |
| Star | Solar radius × (mass / solar mass)^0.8 below one solar mass, exponent 0.57 above |
| Neutron star | Fixed 12 km |
| Black hole | Schwarzschild radius 2GM/c²; Newtonian gravity still applies |
| Plasma | Effective pressureless parcel at 1 kg/m³ |

Jupiter's mean radius is 69,911 km; its mass is about 0.954594234 simulation
units ([NASA planetary parameters](https://ssd.jpl.nasa.gov/planets/phys_par.html)).
The rocky and giant models omit compression, composition, irradiation and age.
The stellar power law is a rough main-sequence scaling, not an evolution track;
manually selecting a star outside main-sequence masses does not make it physical.
The neutron-star radius omits mass dependence and the equation of state. Plasma
has no well-defined material surface: its radius is an explicit effective parcel
model, with no pressure or hydrodynamics. These choices are approximations,
not precision mass–radius predictions.

Disruption uses the fluid Roche estimate `2.44 R_victim (M_primary/m_victim)^(1/3)`.
Strength, spin and orbit-dependent disruption physics remain outside this model.
The existing impact, promotion and explosion prescriptions remain approximate.

## Scenarios and time resolution

The solar preset uses approximate planetary masses and orbital distances, a
384,400 km Earth–Moon separation, three Jovian moon distances, and Titan.
Satellite pairs start with circular relative velocities and preserve their
parent's centre-of-mass position and momentum. Orbital phases are illustrative;
this is not an ephemeris. Saturn's ring material is not resolved; statistical
ring models belong to the specialised-mode milestone. Solar playback starts at
x0.1 (one simulation unit per real second); Io then takes about 0.45 seconds per
orbit rather than 0.045 seconds at x1. The belt uses low-mass tracers; they have
no gravitational back-reaction. The formation preset is an embryo disk, not a
calibrated accretion model.

The black-hole preset uses a stellar-mass hole and a star passing inside its
physical Roche estimate. The impact preset launches two Earth-like bodies at
several mutual escape speeds. Both use slower simulated time to show these short
events. The `galaxies` preset is labelled **Tidal encounter**: its two stellar-mass
primaries and tracer disks illustrate tidal tails, not actual galaxies. Its
initial relative speed uses the full three-dimensional separation for a
parabolic encounter.

Physical scenes allow IAS15 to choose timesteps without a minimum floor. The
server's wall-clock budget limits progress, not accuracy tolerance. One native
step can exceed the budget. Direct collision detection and the truncated
20-body forecast still need the convergence/contact validation in Milestone 3;
compact-object dynamics are Newtonian, not relativistic. Forecasts end at the
first contact between any bodies; only contact with the proposed body receives
an impact marker. The preview does not invent post-collision outcomes. Radial
compact-object captures can still produce IAS15 convergence warnings; passing
outcome checks do not establish accuracy for those encounters.

## Presentation and compatibility

Godot linearly interpolates authoritative position snapshots with a small
buffer (target 50 ms) and an achieved-speed estimate. Convex interpolation keeps
relative positions within their sampled bounds even when updates are sparse.
The display never advances beyond its newest snapshot, including during a
physics stall or disconnect. Pausing, restarting or replacing a scene resets
the timeline. This presentation interpolation does not solve gravity; sparse
samples cannot recover unresolved fast orbits.

Godot keeps `physical_radius`, `rendered_radius` and mouse-picking extent separate.
**V** cycles display enlargement 1, 2 and 0 (physical mesh sizes). Enlarged meshes
are limited to a screen-space size when zooming in; they never shrink below the
physical radius. Visibility markers, glows, rings and jets remain illustrative.
Selection uses generous pixel targets. The placement ghost uses the contact
radius returned by Python plus the selected display enlargement. Forecasts and
placement commands never contain display enlargement.

Version-2 scene files store the unit/radius model and a camera `display_scale`.
Changing these unit or model definitions requires a new identifier.
Version-1 files load as `legacy-sandbox-v1`, preserving masses, radii, coordinates,
velocities, times, speeds, random state and the old radius/disruption rules.
They retain the old minimum timestep of 1e-4 and are labelled **legacy units** in
the HUD. Re-saving writes version 2 with the legacy identifier; it does not
reinterpret sandbox values as measured SI quantities. Clear or load a preset to
start a physical scene. Unknown unit identifiers are rejected before replacement.

Protocol 2 requires versioned commands and uses new binary packet kinds, so
older clients cannot silently interpret the new radius semantics. State packets
include the scene's unit flag. Rendering uses float32 coordinates and may lose
small separations at large distances; Python/REBOUND retains double precision.
