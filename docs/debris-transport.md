# Expanding-cloud transport

`physics_server/debris_transport.py` evolves a compact debris cloud and one resolved
body with a conservative, restricted model. It is standalone; the live simulator
does not use it. General cloud shapes, reservoir coalescence and persistence
integration remain outside this implementation. The separate
[bounded lifecycle API](debris-lifecycle.md) transfers complete records without
resetting their model or error history and promotes single-fragment reservoirs.

## Supported initial states

`start_transport(fragments, body)` needs the fragment states **before compression**.
An existing budget snapshot does not contain enough information to recover them.
The constructor retains only fixed-size reservoir data and scalar model parameters.

Multiple fragments must have outward homologous velocities: relative to their
centre of mass, **vᵢ = H rᵢ** for one positive H, within 10⁻¹² of the cloud velocity
scale. The expansion mode must have positive escape energy. Rotating, contracting,
bound and nonhomologous clouds are rejected. Individual spherical fragments may
have spin, which remains a separate, constant inventory.

A single fragment is the ordinary two-body special case, with no internal scale
motion. It can follow a bound orbit. In all cases, the cloud's enclosing support
and the resolved body's sphere must remain separated. A debris cloud surrounding
its primary cannot be represented by this far-field model.

## Internal motion and gravity

The relative pattern expands without changing shape or orientation:

```text
rᵢ(t) = s(t) rᵢ(0)
J = Σ mᵢ |rᵢ(0)|²
K_expansion = ½ J (ds/dt)²
U_fragments(s) = U_fragments(1) / s
d²s/dt² = U_fragments(1) / (J s²)
```

Fragment radii, material volume, own self-binding, spin energy and internal energy
remain constant. Only fragment separations scale; the enclosing extent is bounded
by `s * initial_centre_extent + max_fragment_radius`. Expanding s keeps initially
non-overlapping fragments separated.

The mutual potential formula is exact for the prescribed scaled pattern. The
scale acceleration is the projection of self-gravity onto this one expansion
mode. It is exact for symmetric central configurations; arbitrary fragment
patterns have transverse or unequal radial accelerations that the closure omits.
The constructor measures the maximum difference between resolved self-acceleration
and the projected acceleration. Along the model pattern that defect scales as
1/s². Positive mode energy is not an independent certificate that every fragment
in the unrestricted Newtonian problem escapes.

## Complete timestep and error controls

`advance_transport(state, duration_s, max_relative_force_error=...,
max_omitted_velocity_change_m_s=..., max_relative_energy_error=...)` takes one
kick–drift–kick step. It evolves both centres with equal/opposite monopole gravity,
and evolves s and ds/dt with the internal force above. Positions, expansion energy,
mutual fragment potential and cloud/body monopole potential all change consistently.
Linear and total angular momentum are conserved analytically; the Hamiltonian's
numerical energy error converges quadratically as the timestep decreases.

Three checks can reject a step without modifying the input:

- Force accuracy uses the closest approach along the **whole drift segment** and
  the largest cloud extent, not just endpoint geometry. Support overlap or an
  excessive [far-field force bound](unresolved-debris.md#far-field-gravity-exchange)
  rejects the step.
- A cumulative force-defect impulse integrates the omitted self-gravity and
  external tidal acceleration bounds along accepted model paths. It must stay
  below the supplied velocity-change limit. This controls approximation use; it
  is **not** a rigorous bound on the actual trajectory's displacement or velocity
  error once that trajectory departs from the model pattern.
- Cumulative numerical energy error is measured against the initial dynamic
  energy, scaled by the initial absolute kinetic and potential terms. Fixed
  fragment binding, spin and internal reservoirs cannot mask integration drift.
  Steps that numerically reverse an escaping expansion are also rejected.

The caller must reduce the timestep or choose another representation on rejection.
Reducing the timestep cannot remove a cumulative model error or repair an invalid
cloud shape. There is no silent fallback, deleted mass, energy correction or heat
injection. The returned `CloudTransport` is immutable.

## Energy convention

`state.budget(origin_m=..., frame_velocity_m_s=...)` returns the current **model**
inventory. Its mutual potential includes both the evolving internal pair potential
and cloud/body monopole coupling. `energy_offset_j` separately records the initial
resolved-versus-monopole coupling difference and any roundoff in the expansion
projection. Adding that constant to model energy reproduces the initial resolved
energy; it is not a physical potential or an internal-energy reservoir.

At later times the actual coupling potential of the prescribed shape differs from
the monopole by the instantaneous potential-error bound. Including the initial
offset gives a discrepancy bound of that value plus `abs(energy_offset_j)`, apart
from rounding. This does not certify the energy of a different, fully resolved
trajectory. `energy_error_j` reports numerical drift in the model's dynamic energy;
it excludes bulk centre-of-mass kinetic energy and fixed inventory terms.

Reference tests require second-order convergence toward resolved N-body evolution
of a symmetric expanding cloud and toward a Kepler orbit for one fragment. They
also check inventory closure, changing potential, inertial-frame transformations,
noncentral force defects, invalid shapes, accumulated limits and close encounters
hidden between endpoints. These restricted references do not validate arbitrary
ejecta clouds or long-term tidal deformation.
