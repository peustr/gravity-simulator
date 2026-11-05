# Compact ejecta

`physics_server/debris_shell.py` is the live unresolved-material model. It
compresses symmetric ejecta from supported head-on disruptions when the complete
resolved outcome exceeds explicit-particle capacity. Classification and the
prescribed mass/energy allocation precede representation selection. No material
is discarded to fit the particle cap.

## Representation and gravity

The resolved policy uses equal-mass fragments at the vertices of a tetrahedron,
octahedron, cube, icosahedron, dodecahedron or icosidodecahedron (4, 6, 8, 12, 20
or 30 fragments), moving radially about a central remnant. A compact record
retains fragment count, mass, centre/velocity, shell radius/expansion speed,
individual physical radius, fragment binding/internal energy, formation time,
model parameters and error diagnostics. It has zero intrinsic angular momentum
and contains no hidden native particles.

For unit vertex directions **uᵢ**, finite-shape self-potential is `−κ GM²/R`,
where `κ = Σᵢ<ⱼ 1/|uᵢ−uⱼ| / N²`. Isolated central-remnant expansion obeys
`R̈ = −G(κM + M_core)/R²`; symmetry makes this the exact finite-fragment
homologous solution until external forces deform it. The coefficient is not the
uniform-shell value 1/2.

External interactions use a spherical shell: constant potential and zero field
inside, Newtonian monopole outside. Forces and reactions between all resolved
bodies and compact records advance in one REBOUND Bulirsch–Stoer ODE. Native
direct summation supplies resolved-body forces. Disjoint and nested shells are
supported; intersecting shell surfaces and resolved spheres touching the debris
layer are rejected. Bodies inside a cavity can undergo supported resolved
collisions.

## Accuracy and refusal

The ODE integrates a force-defect envelope for frozen angular shape, external
tidal deformation and omitted nonspherical fields. Accumulated impulse must
remain below 0.5% of initial expansion speed. This is a model diagnostic, not a
universal trajectory-error theorem. Live tests compare compact and resolved
constructions, including a third gravitating body.

Each step checks geometry, positive expansion and dynamic-energy closure within
`1e-9` of its local energy scale. Failed trials leave live time, bodies and
inventories unchanged and pause with an explanation. Native BS also advances
resolved central-shell constructions, avoiding IAS15 time underflow at exact
force balance. Other scenes normally retain IAS15.

At most eight records are stored. Unsupported layouts or full storage leave the
collision unapplied. Raising capacity does not reconstruct an existing record.
Recollapse, matter crossing the debris layer, arbitrary angular structure and
debris accretion require a more general model. Full gravity and calibrated
collision handling are required while compact records are active.

## Accounting, persistence and display

The conservation report includes unresolved mass, COM momentum/angular momentum,
expansion kinetic energy, fragment binding/internal energy, finite-shape
self-potential and interactions. The initial resolved-to-spherical external
potential difference is a separate constant model offset, never heat. Numerical
energy drift, integrated force-defect impulse and explicit removal/transform
budgets are separate fields. The maximum model impulse and last refusal survive
removal and save/restart.

Version-5 experiments retain records, monotonic ownership IDs, active solver,
numerical/model history and the explicit-loss ledger. Restoration validates
geometry and inventories before replacing the world. Integrator workspace is
rebuilt; restart is not bitwise identical. Older formats remain readable.
Boundary removal transfers a whole record to the loss inventory only when all
member centres lie beyond the boundary; it never clips part of a record.

Godot receives negative-ID translucent shell views that cannot be selected or
followed as individual bodies. Centres follow buffered authoritative positions.
Brightness, layer thickness and display enlargement are artistic; physics uses
saved SI geometry.

Generate loadable resolved/compact comparisons with
`python3 tools/dev.py impact-references --output benchmarks/impact-references`.
See [collision budgets](collision-budgets.md) for construction prescriptions and
[impact scaling](impact-scaling.md) for calibration domains.
