"""Explicit source/sink budgets remain distinct from conservation residuals."""

import math
import pytest

from body_state import BodyInventory
from diagnostics import PhysicalLossLedger, conservation_report, validate_losses
import experiments as E
import server as S
import units as U
import world as W


def test_boundary_loss_includes_spin_internal_and_binding_energy_and_survives_restart():
    w = W.World()
    w.add_body(W.ROCKY, 0.003, (0, 0, 0), (0, 0, 0))
    w.add_body(W.ROCKY, 0.003, (W.ESCAPE_DISTANCE + 1, 0, 0), (0, 1, 0), inventory=BodyInventory((0, 0, 1e30), 1e28))
    baseline = conservation_report(w)
    w._cull_escapers()
    report = conservation_report(w)
    assert report["explicit_losses"]["mass_kg"] == pytest.approx(0.003 * U.MASS_KG)
    assert report["explicit_losses"]["angular_momentum_kg_m2_s"][2] > 1e30
    assert abs(report["relative_conservation_residual"]) < 1e-14
    assert report["conservation_residual"]["mass_kg"] == pytest.approx(0, abs=1e10)
    assert report["current"]["energy_j"] != baseline["current"]["energy_j"]
    restored, _ = E.restore(E.capture(w, E.DEFAULT_CAMERA))
    assert restored.physical_loss_ledger.state() == w.physical_loss_ledger.state()
    assert conservation_report(restored) == report


def test_user_addition_and_removal_are_signed_explicit_changes():
    w = W.World()
    conservation_report(w)
    service = S.Server("127.0.0.1", 0, w)
    service.send_json = lambda *args: None
    addr = ("127.0.0.1", 1234)
    try:
        service.handle(dict(cmd="add", type="rocky", pos=[10, 0, 0], mode="launch", drag=[0, 0, 0]), addr)
        report = conservation_report(w)
        assert report["changes"]["mass_kg"] > 0 and report["explicit_losses"]["mass_kg"] < 0
        assert report["conservation_residual"]["mass_kg"] == 0
        assert report["relative_conservation_residual"] == 0
        with pytest.warns(RuntimeWarning, match="Last particle removed"):
            service.handle(dict(cmd="remove", id=1), addr)
        assert conservation_report(w)["conservation_residual"]["mass_kg"] == 0
        assert w.physical_loss_ledger.event_count == 2
    finally:
        service.sock.close()


def test_history_aggregates_all_events_and_retains_bounded_details_without_aliasing():
    ledger = PhysicalLossLedger()
    before = dict(time_s=0, mass_kg=2.0, momentum_kg_m_s=[1, 2, 3], angular_momentum_kg_m2_s=[3, 2, 1], energy_j=5.0)
    after = dict(time_s=1, mass_kg=1.0, momentum_kg_m_s=[0, 0, 0], angular_momentum_kg_m2_s=[0, 0, 0], energy_j=0.0)
    for i in range(100):
        ledger.record("removal", before, dict(after, time_s=i + 1))
    assert ledger.event_count == 100 and len(ledger.events) == 64
    assert ledger.totals["mass_kg"] == 100 and ledger.totals["energy_j"] == 500
    saved = ledger.state()
    copy = PhysicalLossLedger(saved)
    assert copy.state() == saved
    copy.totals["momentum_kg_m_s"][0] = 999
    assert ledger.state() == saved
    assert saved["events"][0]["time_s"] == 37


def test_unknown_inventory_is_never_replaced_with_zero_loss():
    ledger = PhysicalLossLedger()
    ledger.record("unavailable", None, None)
    assert ledger.unknown_events == 1 and all(v is None for v in ledger.totals.values())
    assert PhysicalLossLedger(ledger.state()).state() == ledger.state()
    w = W.World()
    w.units = U.LEGACY
    assert ledger.capture(w) is None
    known = dict(time_s=0, mass_kg=1, momentum_kg_m_s=[0, 0, 0], angular_momentum_kg_m2_s=[0, 0, 0], energy_j=1)
    ledger = PhysicalLossLedger()
    ledger.record("heuristic", known, dict(known, energy_j=None))
    assert ledger.totals["energy_j"] is None and ledger.totals["mass_kg"] == 0
    assert ledger.unknown_events == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(totals={}),
        lambda d: d.update(events={}),
        lambda d: d.update(events=[{}]),
        lambda d: d.update(event_count=-1),
        lambda d: d.update(unknown_events=True),
        lambda d: d.update(unknown_events=1),
        lambda d: d.update(extra=1),
    ],
)
def test_invalid_saved_history_is_rejected_before_world_replacement(change):
    w = W.World()
    data = E.capture(w, E.DEFAULT_CAMERA)
    change(data["physical_loss_ledger"])
    with pytest.raises(ValueError):
        E.restore(data)
    assert w.physical_loss_ledger.event_count == 0


@pytest.mark.parametrize(
    "value",
    [None, {}, dict(mass_kg=math.inf, momentum_kg_m_s=[0, 0, 0], angular_momentum_kg_m2_s=[0, 0, 0], energy_j=0),
     dict(mass_kg=0, momentum_kg_m_s=[0, 0], angular_momentum_kg_m2_s=[0, 0, 0], energy_j=0)],
)
def test_invalid_physical_loss_shapes_are_rejected(value):
    with pytest.raises(ValueError):
        validate_losses(value)
