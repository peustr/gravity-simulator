"""Bounded ownership of immutable cloud models, with lossless whole-cloud transfer.

Full stores refuse admission; there is no eviction, hidden overflow queue or
coalescence. This is a single-threaded lifecycle API, not a many-cloud integrator.
"""
from dataclasses import dataclass, replace
import math

from collision_outcomes import SphereState
from debris_transport import CloudTransport, advance_transport
from disruption import ContactOutcome


class ReservoirCapacityError(RuntimeError):
    """No free reservoir slot; the proposed operation has changed nothing."""


@dataclass(frozen=True)
class ReservoirRecord:
    transport: CloudTransport
    formed_at_s: float = 0.0
    classification: ContactOutcome | None = None

    def __post_init__(self):
        if not isinstance(self.transport, CloudTransport):
            raise TypeError('Reservoir records require a CloudTransport state')
        if self.classification is not None and not isinstance(self.classification, ContactOutcome):
            raise TypeError('Classification must be an immutable ContactOutcome')
        if not math.isfinite(self.formed_at_s) or self.formed_at_s < 0:
            raise ValueError('Formation time must be finite and nonnegative')
        if not math.isfinite(self.time_s):
            raise ValueError('Reservoir time is outside numerical range')

    @property
    def time_s(self):
        return self.formed_at_s + self.transport.elapsed_s


@dataclass(frozen=True)
class PromotedFragment:
    fragment: SphereState
    record: ReservoirRecord  # retains provenance, epoch, coupling context and error history


def _identifier(value):
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError('Reservoir ID must be an unsigned 64-bit integer')


class ReservoirStore:
    """Fixed slot count; transfers validate both ends before changing ownership.

    Stored records are immutable. Releasing/promoting returns the complete record
    to the caller, who must accept ownership; neither operation discards material.
    The resolved body in a transport state is coupling context, not an additional
    owned body. Do not independently advance entries sharing a physical body.
    """
    def __init__(self, capacity: int):
        if type(capacity) is not int or capacity < 0:
            raise ValueError('Reservoir capacity must be a nonnegative integer')
        self._capacity = capacity
        self._records: dict[int, ReservoirRecord] = {}

    @property
    def capacity(self):
        return self._capacity

    @property
    def ids(self):
        return tuple(self._records)

    def __len__(self):
        return len(self._records)

    def get(self, identifier: int) -> ReservoirRecord:
        _identifier(identifier)
        return self._records[identifier]

    def _check_admission(self, identifier):
        _identifier(identifier)
        if identifier in self._records:
            raise ValueError('Reservoir ID is already present')
        if len(self) >= self.capacity:
            raise ReservoirCapacityError('Reservoir capacity exhausted; material remains with its current owner')

    def deposit(self, identifier: int, record: ReservoirRecord):
        """Admit an existing record; caller relinquishes ownership only on success."""
        self._check_admission(identifier)
        if not isinstance(record, ReservoirRecord):
            raise TypeError('A store accepts ReservoirRecord objects')
        if any(existing.transport is record.transport for existing in self._records.values()):
            raise ValueError('Transport state is already stored under another ID')
        self._records[identifier] = record

    def advance(self, identifier: int, duration_s: float, *, max_relative_force_error: float,
                max_omitted_velocity_change_m_s: float, max_relative_energy_error: float) -> ReservoirRecord:
        """Advance one isolated model; commit only after all transport checks pass."""
        record = self.get(identifier)
        transport = advance_transport(record.transport, duration_s,
                                      max_relative_force_error=max_relative_force_error,
                                      max_omitted_velocity_change_m_s=max_omitted_velocity_change_m_s,
                                      max_relative_energy_error=max_relative_energy_error)
        updated = replace(record, transport=transport)
        self._records[identifier] = updated
        return updated

    def transfer_to(self, identifier: int, destination: 'ReservoirStore'):
        """Move a whole record, preserving its ID, epoch, classification and errors."""
        if destination is self:
            raise ValueError('Transfer destination must be another store')
        record = self.get(identifier)
        destination.deposit(identifier, record)
        del self._records[identifier]

    def release(self, identifier: int) -> ReservoirRecord:
        """Hand off the complete record; caller is responsible for its next owner."""
        self.get(identifier)
        return self._records.pop(identifier)

    def promote_singleton(self, identifier: int) -> PromotedFragment:
        """Exactly recover one explicit fragment; aggregated clouds cannot be sampled."""
        record = self.get(identifier)
        state = record.transport
        cloud = state.reservoir
        if cloud.fragment_count != 1:
            raise ValueError('Only a one-fragment reservoir can be promoted without a resampling model')
        fragment = SphereState(cloud.mass_kg, state.max_fragment_radius_m, cloud.centre_m, cloud.velocity_m_s,
                               cloud.spin_kg_m2_s, cloud.internal_energy_j)
        result = PromotedFragment(fragment, record)
        del self._records[identifier]
        return result
