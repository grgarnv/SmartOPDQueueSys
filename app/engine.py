"""Queue ordering and ETA logic for one doctor's queue on one day.

Pure functions with no I/O, so the same code serves the web app, the tests and
the later simulation harness (SRS 6.2, SIM-004).

An entry is a dict with: id, status, priority (1 = emergency), position,
started_at (datetime or None) and due_at (datetime or None: when the patient's
turn came while they were not checked in).
"""
from datetime import timedelta

WAITING = ("booked", "checked_in")
ACTIVE = ("in_consultation", "called") + WAITING


def order(entries):
    """Active entries in service order: current patient, called patient, then
    emergencies, then queue position. Completed and skipped entries are left out."""
    return sorted(
        (e for e in entries if e["status"] in ACTIVE),
        key=lambda e: (ACTIVE.index(e["status"]) if e["status"] not in WAITING else 2,
                       -e["priority"], e["position"]),
    )


def expected_minutes(durations, default):
    """Expected consultation length from today's observed durations."""
    # ponytail: rolling mean of the last 5 consultations; swap for a better estimator once the simulator measures MAE
    recent = [d for d in durations if d >= 1][-5:]  # under a minute is an accidental start/complete, not a consultation
    return sum(recent) / len(recent) if recent else default


def compute_etas(entries, now, avg_minutes, opd_start=None, available=True, break_until=None):
    """Estimated start time per active entry, {id: datetime}. Every value is None
    when the doctor is unavailable, because no honest estimate exists (FR-015)."""
    queue = order(entries)
    if not available:
        return {e["id"]: None for e in queue}
    free = max(t for t in (now, opd_start, break_until) if t is not None)
    avg = timedelta(minutes=avg_minutes)
    etas = {}
    for e in queue:
        if e["status"] == "in_consultation":
            etas[e["id"]] = e["started_at"]
            free = max(free, e["started_at"] + avg)
        else:
            etas[e["id"]] = free
            free += avg
    return etas


def next_to_call(entries):
    """Who the doctor should call next (decision tree DT-3).

    Returns (entry or None, missed) where missed lists waiting entries that were
    passed over because they have not checked in. They keep their place."""
    missed = []
    for e in order(entries):
        if e["status"] == "checked_in":
            return e, missed
        if e["status"] == "booked":
            missed.append(e)
    return None, missed


def can_skip(entry, now, grace_minutes):
    """A patient becomes skippable only after the grace period has run since
    their turn came and they were still not checked in (FR-024)."""
    return (entry["status"] == "booked" and entry["due_at"] is not None
            and now - entry["due_at"] >= timedelta(minutes=grace_minutes))


def end_position(entries):
    """Position at the end of the queue: default for new bookings and late reinsertion (FR-026)."""
    return max((e["position"] for e in entries), default=0) + 1


def front_position(entries):
    """Position ahead of everyone waiting: used only for an authorised reinsertion exception."""
    waiting = [e["position"] for e in entries if e["status"] in WAITING]
    return min(waiting) - 1 if waiting else end_position(entries)
