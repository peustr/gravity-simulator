# Bounded reservoir lifecycle

`physics_server/debris_lifecycle.py` owns immutable cloud records in a fixed number
of slots. It provides admission, checked model advancement, whole-record transfer,
handoff and exact promotion of single-fragment reservoirs. It is standalone and
single-threaded; the live collision handler and save format do not use it yet.

## Records and ownership

`ReservoirRecord` contains a `CloudTransport`, its formation time and optional
immutable collision classification. `time_s` is formation time plus the transport
model's elapsed time. The record retains the model's energy offset, initial energy
reference, numerical drift and accumulated force-defect impulse.

`ReservoirStore(capacity)` accepts a nonnegative integer slot count, including zero.
IDs are unsigned 64-bit integers supplied by the caller. `capacity`, `ids` and
`get(id)` expose the configured bound, current IDs and immutable records.

| Operation | Ownership and failure behavior |
|---|---|
| `deposit(id, record)` | Caller relinquishes ownership only after successful admission. Full stores, duplicate IDs and local aliases of a transport state are rejected. |
| `advance(id, duration_s, ...)` | Uses the transport model's explicit error limits. Replaces the stored record only after all checks pass. Formation time and classification stay unchanged. |
| `transfer_to(id, destination)` | Moves the complete record with its ID and error history. Destination validation occurs before removing the source. |
| `release(id)` | Removes and returns the complete record to its next owner. This is a handoff, not deletion of material. |
| `promote_singleton(id)` | Returns one exact `SphereState` plus the complete source record, then frees the slot. Multi-fragment reservoirs are rejected. |

Caller-assigned IDs and ownership must be coordinated across stores; there is no
global registry. Use `transfer_to` for cross-store moves rather than depositing
copies into multiple owners. Validation failures leave both stores unchanged.
Missing IDs fail explicitly, so replaying a completed transfer or promotion cannot
withdraw the same stored material again.

The resolved body inside `CloudTransport` is coupling context, **not** another
body owned by the store. Advancing one entry retains the transport model's isolated
cloud/body domain. Independently advancing several entries that share a physical
body would double-count or overwrite its response and is unsupported. A store is
not a many-cloud gravity solver, and summing coupled budgets that share a source
body would double-count that body's inventory.

## Promotion and model validity

A one-fragment reservoir uniquely retains the original sphere's mass, radius,
position, velocity, spin and internal energy. Promotion preserves these quantities,
physical volume and every budget component. The returned `PromotedFragment.record`
keeps classification, epoch, coupling context and accumulated approximation errors;
changing representation must not reset those errors.

Multiple fragments cannot be reconstructed uniquely from aggregate moments.
Partial withdrawals, synthetic fragment sampling, accretion and automatic
coalescence are therefore unsupported. In particular, merging two clouds to free
a slot can violate the homologous-expansion closure even when an aggregate mass
and energy inventory could be preserved.

## Hard-cap policy

Capacity exhaustion raises `ReservoirCapacityError`. It does not evict an old
record, alter a collision regime, collapse material into a larger body, change
accuracy limits or retain an unbounded overflow queue. Storage is O(capacity),
with no history retained by the store. Released records belong to their receivers;
the application must also bound those owners rather than collecting handoffs in
another unbounded queue.

Live integration must check admission before committing a collision or transfer.
If no supported representation fits, the operation must remain unapplied and the
controller must report that limit. This policy bounds resource use by refusing
work it cannot represent; it does not promise uninterrupted evolution of arbitrary
scenes under an arbitrarily small cap. Reserving explicit particles and applying
promotion/handoff atomically to `World` belong to the integration checkpoint.

Tests cover repeated admission/refusal and release, absence of hidden queues or
history, duplicate and stale requests, atomic rejected physics steps, full-state
transfer and error-history retention. Single-fragment promotion is compared with
a resolved N-body trajectory and with all inventory components. Those checks do
not establish multi-fragment resampling, coalescence or multi-cloud evolution.
