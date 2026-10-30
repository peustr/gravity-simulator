"""Bounded ownership, atomic failure and exact promotion of transported material."""
from dataclasses import FrozenInstanceError, replace
import gc
import math
import weakref

import numpy as np
import pytest

from collision_outcomes import collision_budget
from debris_lifecycle import ReservoirCapacityError, ReservoirRecord, ReservoirStore
from debris_transport import start_transport
from test_collision_models import classify, encounter
from test_debris_transport import LIMITS, explicit_reference, initial_cloud


def record(*, singleton=False, formed_at=100):
    fragments, body = initial_cloud()
    return ReservoirRecord(start_transport(fragments[:1] if singleton else fragments, body), formed_at)


def test_full_store_refuses_without_eviction_reclassification_or_an_overflow_queue():
    store = ReservoirStore(2)
    a = replace(record(), classification=classify(encounter(), 'planetesimals'))
    b = record(singleton=True)
    store.deposit(10, a)
    store.deposit(20, b)
    for _ in range(20):
        incoming = record()
        reference = weakref.ref(incoming)
        with pytest.raises(ReservoirCapacityError, match='current owner'):
            store.deposit(30, incoming)
        assert store.ids == (10, 20)
        assert store.get(10) is a and store.get(20) is b
        assert store.get(10).classification is a.classification
        del incoming
        assert reference() is None
    assert len(store) == store.capacity == 2
    with pytest.raises(AttributeError):
        store.capacity = 3
    with pytest.raises(FrozenInstanceError):
        a.formed_at_s = 0


def test_whole_cloud_transfer_preserves_complete_state_and_frees_the_source_slot():
    source, destination = ReservoirStore(1), ReservoirStore(1)
    original = record()
    source.deposit(42, original)
    evolved = source.advance(42, 100, **LIMITS)
    assert evolved.time_s == 200
    assert evolved.transport.force_defect_impulse_m_s > 0
    assert evolved.transport.energy_error_j != 0
    source.transfer_to(42, destination)
    assert len(source) == 0
    assert destination.get(42) is evolved
    assert destination.get(42).transport.budget() == evolved.transport.budget()
    assert destination.get(42).transport.energy_offset_j == evolved.transport.energy_offset_j
    assert destination.get(42).transport.force_defect_impulse_m_s == evolved.transport.force_defect_impulse_m_s
    source.deposit(43, record())
    with pytest.raises(KeyError):
        source.transfer_to(42, destination)
    returned = destination.release(42)
    assert returned is evolved and len(destination) == 0


def test_failed_transfers_leave_both_owners_unchanged():
    source, destination = ReservoirStore(1), ReservoirStore(1)
    a, b = record(), record(singleton=True)
    source.deposit(1, a)
    destination.deposit(2, b)
    with pytest.raises(ReservoirCapacityError):
        source.transfer_to(1, destination)
    with pytest.raises(ValueError, match='another store'):
        source.transfer_to(1, source)
    assert source.get(1) is a and destination.get(2) is b
    assert destination.release(2) is b
    destination.deposit(1, b)
    with pytest.raises(ValueError, match='already present'):
        source.transfer_to(1, destination)
    assert source.get(1) is a and destination.get(1) is b
    destination.release(1)
    destination = ReservoirStore(2)
    destination.deposit(2, a)
    with pytest.raises(ValueError, match='another ID'):
        source.transfer_to(1, destination)
    assert source.get(1) is a and destination.get(2) is a


def test_rejected_physics_step_is_atomic_and_does_not_reset_error_history():
    store = ReservoirStore(1)
    store.deposit(1, record())
    current = store.advance(1, 100, **LIMITS)
    with pytest.raises(ValueError, match='Accumulated energy error'):
        store.advance(1, 500, **{**LIMITS, 'max_relative_energy_error': 1e-12})
    assert store.get(1) is current
    assert store.get(1).time_s == 200
    assert store.get(1).transport.energy_error_j == current.transport.energy_error_j


def test_single_fragment_promotion_matches_resolved_trajectory_and_every_budget_component():
    original = record(singleton=True)
    state = original.transport
    fragment = initial_cloud()[0][0]
    reference = explicit_reference((fragment,), state.body, 1000)
    store = ReservoirStore(1)
    store.deposit(7, original)
    for _ in range(10):
        evolved = store.advance(7, 100, **LIMITS)
    receipt = store.promote_singleton(7)
    assert len(store) == 0
    assert receipt.record is evolved
    np.testing.assert_allclose(receipt.fragment.position_m, reference.particles[0].xyz, rtol=0, atol=1e-3)
    np.testing.assert_allclose(receipt.fragment.velocity_m_s, reference.particles[0].vxyz, rtol=0, atol=1e-8)
    cloud_budget = evolved.transport.reservoir.budget()
    explicit_budget = collision_budget([receipt.fragment])
    for field in cloud_budget.__dataclass_fields__:
        np.testing.assert_allclose(getattr(explicit_budget, field), getattr(cloud_budget, field), rtol=1e-12, atol=0)
    coupled = collision_budget((receipt.fragment, evolved.transport.body))
    assert coupled.energy_j == pytest.approx(evolved.transport.budget().energy_j, rel=1e-12)
    assert (4 / 3) * math.pi * receipt.fragment.radius_m**3 == pytest.approx(
        evolved.transport.reservoir.volume_m3, rel=1e-12)
    assert receipt.record.transport.energy_offset_j == state.energy_offset_j
    assert receipt.record.transport.force_defect_impulse_m_s > 0
    with pytest.raises(KeyError):
        store.promote_singleton(7)


def test_multifragment_promotion_is_rejected_without_synthetic_material():
    store = ReservoirStore(1)
    original = record()
    store.deposit(1, original)
    with pytest.raises(ValueError, match='resampling model'):
        store.promote_singleton(1)
    assert store.get(1) is original
    assert store.release(1) is original


def test_repeated_admission_and_release_keep_storage_bounded_without_history():
    store = ReservoirStore(1)
    for identifier in range(30):
        current = record()
        ref = weakref.ref(current)
        store.deposit(identifier, current)
        del current
        exported = store.release(identifier)
        assert ref() is exported
        assert len(store) == 0
        del exported
        gc.collect()
        assert ref() is None


@pytest.mark.parametrize('capacity', [-1, 1.5, True])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError, match='nonnegative integer'):
        ReservoirStore(capacity)


@pytest.mark.parametrize('identifier', [-1, 2**64, 1.5, True])
def test_invalid_identifiers_cannot_alias_an_existing_record(identifier):
    store = ReservoirStore(1)
    original = record()
    store.deposit(1, original)
    with pytest.raises(ValueError, match='64-bit'):
        store.deposit(identifier, record())
    with pytest.raises(ValueError, match='64-bit'):
        store.get(identifier)
    assert store.get(1) is original


def test_duplicate_ids_states_types_and_zero_capacity():
    store = ReservoirStore(2)
    original = record()
    store.deposit(1, original)
    with pytest.raises(ValueError, match='already present'):
        store.deposit(1, record())
    with pytest.raises(ValueError, match='another ID'):
        store.deposit(2, replace(original, formed_at_s=200))
    with pytest.raises(TypeError, match='ReservoirRecord'):
        store.deposit(2, original.transport)
    with pytest.raises(ReservoirCapacityError):
        ReservoirStore(0).deposit(1, original)
    assert store.ids == (1,)
    with pytest.raises(KeyError):
        store.release(2)


@pytest.mark.parametrize('time', [-1, math.nan, math.inf])
def test_invalid_formation_time(time):
    with pytest.raises(ValueError, match='Formation time'):
        replace(record(), formed_at_s=time)


def test_record_type_and_time_overflow():
    with pytest.raises(TypeError, match='CloudTransport'):
        ReservoirRecord(None)
    with pytest.raises(TypeError, match='ContactOutcome'):
        replace(record(), classification={})
    original = record()
    with pytest.raises(ValueError, match='numerical range'):
        replace(original, formed_at_s=1e308, transport=replace(original.transport, elapsed_s=1e308))
