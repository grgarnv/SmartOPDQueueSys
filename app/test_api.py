"""End-to-end checks against a real server on a throwaway database. Run: python3 app/test_api.py

Starts its own server processes on free ports; never touches app/opd.db.
"""
import http.cookiejar
import json
import os
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
TMP = tempfile.mkdtemp(prefix="opd-test-")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(db, demo=True, env=None):
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(HERE / "server.py"), str(port)] + (["--demo"] if demo else []),
                            env={**os.environ, "OPD_DB": db, "OPD_SIM_DIR": f"{TMP}/sim", "OPD_TICK_SECONDS": "1",
                                 "OPD_DISPATCH_SECONDS": "0.3", **(env or {})},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return proc, f"http://127.0.0.1:{port}"
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start: " + proc.stdout.read())


class Client:
    def __init__(self, base):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def raw(self, path, body=None):
        req = urllib.request.Request(self.base + path, None if body is None else json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            r = self.op.open(req, timeout=10)
        except urllib.error.HTTPError as e:
            r = e
        return r.status, r.headers, r.read()

    def __call__(self, path, body=None):
        status, _, data = self.raw(path, body)
        return status, json.loads(data)

    def login(self, user, pw):
        s, r = self("/api/login", {"username": user, "password": pw})
        assert s == 200, (user, r)
        return self


def wait_for(fn, what, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        result = fn()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def main():
    db = f"{TMP}/test.db"
    proc, base = start_server(db)
    try:
        run_checks(base, db)
    finally:
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    assert "Traceback" not in log, log
    check_production_bootstrap()
    print("api: all checks passed")


def run_checks(base, db):
    c = lambda: Client(base)
    admin, staff, tester = c().login("admin", "admin123"), c().login("staff", "staff123"), c().login("tester", "tester123")
    rao, khan = c().login("dr.rao", "doctor123"), c().login("dr.khan", "doctor123")
    p1 = c().login("patient", "patient123")

    # headers and health
    s, h, _ = c().raw("/")
    assert s == 200 and h["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert c()("/api/health")[1]["demo"] is True

    # policy: open all day so the checks work at any hour
    s, pol = admin("/api/admin/policy", {"opd_start": "00:00", "opd_end": "23:59", "grace_minutes": 10, "alert_minutes": 30})
    assert s == 200 and pol["opd_end"] == "23:59"
    assert admin("/api/admin/policy", {"opd_start": "18:00", "opd_end": "09:00"})[0] == 400
    assert staff("/api/admin/policy", {"grace_minutes": 5})[0] == 403

    # registration rules (FR-001, FR-003)
    assert c()("/api/register", {"username": "x1", "password": "short", "name": "X"})[0] == 400
    assert c()("/api/register", {"username": "asha", "password": "longenough", "name": "Asha", "channel": "sms"})[0] == 400
    p2, p3 = c(), c()
    assert p2("/api/register", {"username": "asha", "password": "longenough", "name": "Asha", "phone": "+91 90000 00001"})[0] == 200
    assert p3("/api/register", {"username": "ravi", "password": "longenough", "name": "Ravi", "email": "ravi@example.com", "channel": "email"})[0] == 200
    assert c()("/api/register", {"username": "asha", "password": "longenough", "name": "A2"})[0] == 409

    # permissions (NFR-002, AC-006)
    assert c()("/api/my-appointments")[0] == 401
    assert p1("/api/queue?doctor_id=1")[0] == 403
    assert p1("/api/admin/overview")[0] == 403
    assert staff("/api/sim/run", {"seeds": 1})[0] == 403
    assert admin("/api/sim/run", {"seeds": 1})[0] == 403, "simulation runs are for test roles only (SRS 4.1)"

    # booking (FR-005 to FR-009, AC-001)
    s, a1 = p1("/api/book", {"doctor_id": 1}); assert s == 200 and a1["token"] == 1 and a1["eta"], a1
    s, dup = p1("/api/book", {"doctor_id": 1}); assert dup["existing"] and dup["token"] == 1
    _, a2 = p2("/api/book", {"doctor_id": 1}); _, a3 = p3("/api/book", {"doctor_id": 1})
    assert (a2["token"], a3["token"]) == (2, 3)
    assert p1("/api/book", {"doctor_id": 1, "day": "2020-01-01"})[0] == 400
    assert p1("/api/book", {"doctor_id": 99})[0] == 404
    assert p2("/api/checkin", {"appointment_id": a1["id"]})[0] == 404, "patients cannot touch others' bookings (NFR-004)"
    assert all(set(x) >= {"token", "eta", "status", "doctor", "day"} for x in p1("/api/my-appointments")[1]["appointments"])

    # leave and inactive doctors (FR-006, FR-036)
    today_s = date.today().isoformat()
    assert admin("/api/admin/leave", {"doctor_id": 3, "day": today_s})[0] == 200
    assert p1("/api/book", {"doctor_id": 3})[0] == 409
    deps = p1(f"/api/departments?day={today_s}")[1]["departments"]
    assert not next(d for dep in deps for d in dep["doctors"] if d["id"] == 3)["bookable"]
    admin("/api/admin/leave", {"doctor_id": 3, "day": today_s, "remove": True})
    tomorrow = (date.today() + timedelta(days=1))
    admin("/api/admin/doctor/update", {"doctor_id": 4, "work_days": str((tomorrow.weekday() + 1) % 7)})
    assert p1("/api/book", {"doctor_id": 4, "day": tomorrow.isoformat()})[0] == 409, "not a working day"
    admin("/api/admin/doctor/update", {"doctor_id": 4, "work_days": "0123456", "active": False})
    assert p1("/api/book", {"doctor_id": 4})[0] == 409, "inactive doctor"
    admin("/api/admin/doctor/update", {"doctor_id": 4, "active": True})

    # queue flow (FR-010 to FR-013, FR-022 to FR-028, PR-003)
    _, q = rao("/api/queue"); etas = [e["eta"] for e in q["entries"]]
    assert etas == sorted(etas) and all(etas)
    p2("/api/checkin", {"appointment_id": a2["id"]}); staff("/api/checkin", {"appointment_id": a3["id"]})
    _, q = rao("/api/queue")
    assert rao("/api/queue/action", {"action": "call_next", "version": q["version"] - 1})[0] == 409, "stale version rejected"
    s, r = rao("/api/queue/action", {"action": "call_next", "version": q["version"]}); assert r["called"] == 2, r
    e1 = next(e for e in r["entries"] if e["token"] == 1); assert e1["turn_missed"] and not e1["can_skip"]
    assert rao("/api/queue/action", {"action": "skip", "appointment_id": a1["id"]})[0] == 409, "grace not over"
    assert rao("/api/queue/action", {"action": "call_next"})[0] == 409, "finish current first"
    assert khan("/api/queue/action", {"action": "start", "appointment_id": a2["id"]})[0] == 403, "other doctor's queue"
    assert staff("/api/queue/action", {"action": "start", "appointment_id": a2["id"]})[0] == 403
    rao("/api/queue/action", {"action": "start", "appointment_id": a2["id"]})
    assert rao("/api/queue/action", {"action": "complete", "appointment_id": a2["id"]})[0] == 200
    # views converge (FR-013, AC-003)
    seen = {who: [(e["token"], e["status"], e["eta"]) for e in cl("/api/queue?doctor_id=1")[1]["entries"]] for who, cl in (("doctor", rao), ("staff", staff), ("admin", admin))}
    assert seen["doctor"] == seen["staff"] == seen["admin"]

    # emergency (FR-029 to FR-032)
    assert rao("/api/queue/action", {"action": "emergency", "appointment_id": a3["id"], "reason": "x"})[0] == 403
    assert staff("/api/queue/action", {"action": "emergency", "appointment_id": a3["id"]})[0] == 400, "reason required"
    s, q = staff("/api/queue/action", {"action": "emergency", "appointment_id": a3["id"], "reason": "chest pain"})
    assert s == 200 and q["entries"][0]["token"] == 3 and q["entries"][0]["emergency"]

    # no-show, skip and reinsertion (FR-024 to FR-027, AC-005)
    con = sqlite3.connect(db)
    con.execute("UPDATE appointments SET due_at = ? WHERE id = ?", ((datetime.now() - timedelta(minutes=11)).isoformat(timespec="seconds"), a1["id"]))
    con.commit()
    assert next(e for e in rao("/api/queue")[1]["entries"] if e["token"] == 1)["can_skip"]
    s, q = rao("/api/queue/action", {"action": "skip", "appointment_id": a1["id"], "reason": "no-show"}); assert s == 200
    assert next(e for e in q["entries"] if e["token"] == 1)["status"] == "skipped", "kept, not deleted"
    _, v = p1("/api/checkin", {"appointment_id": a1["id"]}); assert v["status"] == "checked_in"
    order = [e["token"] for e in rao("/api/queue")[1]["entries"] if e["ahead"] is not None]
    assert order == [3, 1], order

    # notifications (FR-017 to FR-021, AC-004)
    def notes(appt):
        return con.execute("SELECT purpose, status, channel FROM notifications WHERE appointment_id = ?", (appt,)).fetchall()
    wait_for(lambda: all(st != "pending" for _, st, _ in notes(a1["id"])) and notes(a1["id"]), "alerts to be dispatched")
    purposes = [p for p, _, _ in notes(a1["id"])]
    assert "arrival" in purposes and "skipped" in purposes, purposes
    assert purposes.count("arrival") == 1, "no duplicate arrival alerts (FR-021)"
    assert all(st == "unconfirmed" for _, st, _ in notes(a1["id"])), "log provider cannot confirm delivery"
    assert ("called", "unconfirmed", "sms") in notes(a2["id"])
    assert any(ch == "email" for _, _, ch in notes(a3["id"])), "patient's chosen channel is used"
    mine = p1("/api/my-appointments")[1]["appointments"][0]
    assert mine["notifications"] and mine["notifications"][0]["status"] == "unconfirmed"
    assert con.execute("SELECT COUNT(*) FROM eta_snapshots").fetchone()[0] > 0, "ETA history stored (FR-016)"

    # doctor availability (FR-015, AC-002)
    rao("/api/doctor/status", {"status": "unavailable"})
    assert p1("/api/my-appointments")[1]["appointments"][0]["eta"] is None
    assert p2("/api/book", {"doctor_id": 1})[0] == 409
    wait_for(lambda: con.execute("SELECT 1 FROM notifications WHERE purpose = 'doctor_unavailable'").fetchone(), "unavailable alert")
    rao("/api/doctor/status", {"status": "delayed", "minutes": 20})
    first = datetime.fromisoformat(rao("/api/queue")[1]["entries"][0]["eta"])
    assert first >= datetime.now() + timedelta(minutes=19)
    rao("/api/doctor/status", {"status": "available"})

    # workload, lookup, audit (FR-033, FR-038, FR-039, AC-007)
    _, o = staff("/api/admin/overview")
    d1 = next(d for d in o["doctors"] if d["name"] == "Dr. Rao")
    assert {"waiting", "current_token", "avg_minutes", "clears_at", "congestion"} <= set(d1) and d1["waiting"] == 2
    assert any(x["action"] == "emergency" for x in o["exceptions"])
    assert staff("/api/lookup?q=Asha")[1]["results"][0]["token"] == 2
    assert staff("/api/admin/events")[0] == 403
    acts = {e["action"] for e in admin("/api/admin/events")[1]["events"]}
    assert {"booked", "called", "skip", "emergency", "reinserted", "turn_missed", "policy_changed", "leave_added"} <= acts, acts
    row = next(e for e in admin("/api/admin/events")[1]["events"] if e["action"] == "emergency")
    assert row["actor"] == "Front Desk" and row["detail"] == "chest pain" and row["at"]

    # exports (FR-040)
    s, h, data = admin.raw(f"/api/admin/export?kind=queue&day={today_s}")
    assert s == 200 and h["Content-Type"].startswith("text/csv") and data.decode().startswith("doctor,token,status")
    assert admin.raw("/api/admin/export?kind=nope")[0] == 400

    # admin: doctors, departments, users
    assert admin("/api/admin/department", {"name": "Dermatology"})[0] == 200
    assert admin("/api/admin/doctor", {"name": "Dr. Shah", "department_id": 4, "username": "dr.shah", "password": "doctor1234"})[0] == 200
    assert c().login("dr.shah", "doctor1234")("/api/queue")[0] == 200
    assert admin("/api/admin/staff", {"name": "Temp", "username": "temp", "password": "temp12345", "role": "staff"})[0] == 200
    temp = c().login("temp", "temp12345")
    uid = next(u["id"] for u in admin("/api/admin/users")[1]["users"] if u["username"] == "temp")
    admin("/api/admin/user/update", {"user_id": uid, "active": False})
    assert temp("/api/admin/overview")[0] == 401, "disabled account loses access at once"

    # login lockout
    for _ in range(5):
        c()("/api/login", {"username": "staff", "password": "wrong"})
    assert c()("/api/login", {"username": "staff", "password": "staff123"})[0] == 429

    # simulation through the API (SIM, AC-009 to AC-012)
    s, job = tester("/api/sim/run", {"scenarios": ["normal"], "seeds": 3}); assert s == 200, job
    run = wait_for(lambda: next((r for r in tester("/api/sim/runs")[1]["runs"]), None), "simulation report")
    assert run["label"] == "SIMULATED RESULTS" and run["runs_per_scenario"] == 3
    s, _, md = admin.raw(f"/api/sim/report?run_id={run['run_id']}&format=md")
    assert s == 200 and b"SIMULATED RESULTS" in md and b"below target" in md
    assert admin.raw("/api/sim/report?run_id=../server&format=md")[0] == 400, "no path traversal"
    assert tester("/api/sim/run", {"scenarios": ["bogus"], "seeds": 1})[0] == 400

    # rough load check (PR-001), scaled to a test machine
    times, errors = [], []
    clients = [c().login("patient", "patient123") for _ in range(4)] + [staff, admin]
    def worker(cl):
        for path in ["/api/my-appointments", "/api/admin/overview", "/api/departments"] * 6:
            t0 = time.perf_counter()
            st, _, _ = cl.raw(path)
            times.append(time.perf_counter() - t0)
            if st not in (200, 403):
                errors.append(st)
    threads = [threading.Thread(target=worker, args=(clients[i % len(clients)],)) for i in range(40)]
    [t.start() for t in threads]; [t.join() for t in threads]
    p95 = statistics.quantiles(times, n=20)[18]
    print(f"  load: {len(times)} requests from 40 threads, p95 {p95 * 1000:.0f} ms, errors {len(errors)}")
    assert not errors and p95 < 2.0


def check_production_bootstrap():
    """Without --demo there are no demo accounts; the admin password comes from the environment."""
    proc, base = start_server(f"{TMP}/prod.db", demo=False, env={"OPD_ADMIN_PASSWORD": "a-strong-passphrase"})
    try:
        assert Client(base)("/api/login", {"username": "patient", "password": "patient123"})[0] == 401
        assert Client(base)("/api/login", {"username": "admin", "password": "admin123"})[0] == 401
        Client(base).login("admin", "a-strong-passphrase")
        assert Client(base)("/api/health")[1]["demo"] is False
    finally:
        proc.terminate()
        proc.communicate(timeout=5)


if __name__ == "__main__":
    main()
