# Solid-body rotation

Resolved rocky planets, moons and asteroids use a homogeneous spherical rotor:
`I = 2MR²/5`, `ω = S/I`. This is the same moment of inertia used by the collision
budgets. The server owns a body-to-world quaternion `(x, y, z, w)`, its SI epoch
and inertial angular velocity. Between changes to spin or inertia, quaternion
exponentiation gives exact torque-free rotation without accumulating timestep
error. Gravity remains spherical and independent of attitude.

Changing an inventory or radius rebases orientation at the change time before
applying the new rate. Conserved collision remnants inherit the surviving body's
reference pose and use their resulting angular momentum; new fragments receive
an identity reference pose. Unknown spin remains unknown and does not drive a
decorative rotation. A new sandbox solid starts with explicitly zero spin.

## Existing scenes

Solar System seeds approximate sidereal rotation periods and obliquities for
Mercury, Venus, Earth, Mars and the Moon. Earth uses 86,164.0905 seconds and
23.44 degrees; Venus rotates retrograde. Galilean moons and Titan start at their
initial circular orbital frequencies. These are initial conditions, not the
result of a tidal locking calculation. Pole azimuths and material phases are
illustrative, not an ephemeris. Reference values: [NASA planetary fact
sheets](https://nssdc.gsfc.nasa.gov/planetary/factsheet/).

Planet smash and Planet formation use the same rotation path: angular momentum
already retained by their shared collision model becomes visible material
rotation. Selecting a solid shows its period in hours and inertial spin axis;
pausing freezes its material orientation. The procedural surface and molten
pattern remain artistic, without predicted composition or temperature.

## Persistence and transport

Version-8 and newer saves retain the quaternion, epoch and rate. Loading validates their
consistency with the physical inventory and radius before replacing the live
world. Versions 1–7 remain readable: their existing spin is retained, with an
identity reference pose at load time because no prior attitude was stored.

An additive protocol-2 pose packet leaves position/event packets and body
capacity unchanged; see the [wire layout](../README.md#protocol-if-you-want-to-build-your-own-front-end). The renderer
resamples the reported constant-rate segments, including whole turns, within
its buffered simulation timeline. It stops at the newest received orientation.
It does not apply forces or torques. Unknown spin and rates outside the float32
presentation range are identified separately in the inspector.

## Scope and references

The free-rotation reference compares material vectors with Rodrigues' rotation
formula over 100 turns, with the roadmap's `1e-6` rad numerical error limit.
Pause/resume, inertia edits, restart, whole-turn resampling and live scene
controls are part of acceptance.

[Equilibrium tides](equilibrium-tides.md) supply supported torques and heating.
J2, flattening and general rotating-impact mass laws are not implemented. Existing collision applicability limits and conditional
sticking assumptions remain in force. A spherical rotor does not establish
material strength or stability at arbitrary spin.
