"""Checks for the queue and ETA engine. Run: python3 app/test_engine.py"""
from datetime import datetime, timedelta

import engine

T = datetime(2026, 11, 2, 10, 0)


def e(id, status="booked", priority=0, position=None, started_at=None, due_at=None):
    return {"id": id, "status": status, "priority": priority, "position": position or id,
            "started_at": started_at, "due_at": due_at}


def test_order():
    q = [e(1, "completed"), e(2, "skipped"), e(3), e(4, "checked_in", priority=1), e(5, "in_consultation"), e(6, "called")]
    assert [x["id"] for x in engine.order(q)] == [5, 6, 4, 3], "current, called, emergency, then position"


def test_etas_accumulate():
    q = [e(1, "in_consultation", started_at=T - timedelta(minutes=4)), e(2, "checked_in"), e(3)]
    etas = engine.compute_etas(q, T, 10)
    assert etas[1] == T - timedelta(minutes=4)
    assert etas[2] == T + timedelta(minutes=6), "waits for the rest of the current consultation"
    assert etas[3] == T + timedelta(minutes=16)


def test_etas_break_and_opd_start_and_unavailable():
    q = [e(1), e(2)]
    assert engine.compute_etas(q, T, 10, break_until=T + timedelta(minutes=15))[1] == T + timedelta(minutes=15)
    assert engine.compute_etas(q, T, 10, opd_start=T + timedelta(hours=1))[2] == T + timedelta(minutes=70)
    assert engine.compute_etas(q, T, 10, available=False) == {1: None, 2: None}


def test_overrunning_consultation_starts_next_now():
    q = [e(1, "in_consultation", started_at=T - timedelta(minutes=30)), e(2, "checked_in")]
    assert engine.compute_etas(q, T, 10)[2] == T


def test_expected_minutes():
    assert engine.expected_minutes([], 12) == 12
    assert engine.expected_minutes([1, 100, 10, 10, 10, 10, 10], 12) == 10, "only the last 5 count"
    assert engine.expected_minutes([0, 0.2], 12) == 12, "sub-minute clicks are ignored"


def test_next_to_call_passes_over_absent_patients():
    chosen, missed = engine.next_to_call([e(1), e(2), e(3, "checked_in"), e(4, "checked_in")])
    assert chosen["id"] == 3 and [m["id"] for m in missed] == [1, 2]
    assert engine.next_to_call([e(1)]) == (None, [e(1)])
    assert engine.next_to_call([e(1, "checked_in"), e(2, "checked_in", priority=1)])[0]["id"] == 2


def test_can_skip_only_after_grace():
    assert not engine.can_skip(e(1), T, 10), "turn has not come yet"
    assert not engine.can_skip(e(1, due_at=T - timedelta(minutes=9)), T, 10)
    assert engine.can_skip(e(1, due_at=T - timedelta(minutes=10)), T, 10)
    assert not engine.can_skip(e(1, "checked_in", due_at=T - timedelta(hours=1)), T, 10)


def test_reinsert_positions():
    q = [e(1, "completed"), e(2, "skipped"), e(3), e(4, "checked_in")]
    assert engine.end_position(q) == 5
    assert engine.front_position(q) == 2
    assert engine.front_position([e(1, "completed")]) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("engine: all checks passed")
