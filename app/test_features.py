"""Checks for the 1.1 features (docs/AUDIT.md, items F-01 to F-25). Run: python3 app/test_features.py

Starts its own servers on throwaway databases, like test_api.py; never touches app/opd.db.
"""
import http.client
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from test_api import TMP, Client, start_server, wait_for

HERE = Path(__file__).parent
TODAY, TOMORROW = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def main():
    db = f"{TMP}/features.db"
    proc, base = start_server(db)
    try:
        run(base, sqlite3.connect(db))
    finally:
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    assert "Traceback" not in log, log
    check_upgrade_from_1_0()
    print("features: all checks passed")


def run(base, con):
    c = lambda: Client(base)
    admin, staff = c().login("admin", "admin123"), c().login("staff", "staff123")
    rao, iyer = c().login("dr.rao", "doctor123"), c().login("dr.iyer", "doctor123")
    admin("/api/admin/policy", {"opd_start": "00:00", "opd_end": "23:59", "block_after_close": 0, "max_active_bookings": 10})
    n = iter(range(1000))

    def patient(**extra):
        p = c()
        i = next(n)
        s, r = p("/api/register", {"username": f"pt{i}", "password": "longenough", "name": f"Patient {i}",
                                   "phone": f"+91 90000 {i:05d}", **extra})
        assert s == 200, r
        return p

    def q(doctor_id=1):
        return staff(f"/api/queue?doctor_id={doctor_id}")[1]

    def act(who, action, appt=None, **extra):
        return who("/api/queue/action", {"action": action, **({"appointment_id": appt} if appt else {}), **extra})

    def note(appt, purpose):
        return con.execute("SELECT recipient, body FROM notifications WHERE appointment_id = ? AND purpose = ?",
                           (appt, purpose)).fetchone()

    # F-01: a called patient who is not at the door no longer blocks the queue
    a, b = patient(), patient()
    ida, idb = a("/api/book", {"doctor_id": 1})[1]["id"], b("/api/book", {"doctor_id": 1})[1]["id"]
    a("/api/checkin", {"appointment_id": ida}); b("/api/checkin", {"appointment_id": idb})
    assert act(rao, "call_next")[1]["called"]
    assert act(rao, "call_next")[0] == 409
    s, r = act(rao, "not_present", ida, reason="not at the door"); assert s == 200, r
    e = next(x for x in r["entries"] if x["id"] == ida)
    assert e["status"] == "booked" and e["turn_missed"], "they lose check-in and their grace period starts"
    assert act(rao, "call_next")[1]["called"], "the doctor can call the next patient"
    s, r = act(staff, "not_present", ida); assert s == 409, "booked patients are not 'not here'"
    act(rao, "start", idb); act(rao, "complete", idb)
    a("/api/checkin", {"appointment_id": ida})
    s, r = act(rao, "not_present", ida); assert s == 200
    assert next(x for x in r["entries"] if x["id"] == ida)["turn_missed"] is False, "checked-in and not yet called: just waiting"

    # F-02: earlier days are closed automatically
    pid = con.execute("SELECT id FROM users WHERE username = 'patient'").fetchone()[0]
    con.execute("INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at, status) VALUES(?,?,?,?,?,?,?)",
                (pid, 2, YESTERDAY, 1, 1, YESTERDAY + "T09:00:00", "checked_in"))
    con.commit()
    wait_for(lambda: con.execute("SELECT status, skip_reason FROM appointments WHERE day = ?", (YESTERDAY,)).fetchone()
             == ("skipped", "not seen: OPD day closed"), "the day to be closed")
    assert con.execute("SELECT 1 FROM events WHERE action = 'day_closed' AND day = ?", (YESTERDAY,)).fetchone()

    # F-03: leave tells booked patients at once
    p3 = patient()
    a3 = p3("/api/book", {"doctor_id": 3, "day": TOMORROW})[1]["id"]
    assert admin("/api/admin/leave", {"doctor_id": 3, "day": TOMORROW})[1]["affected_appointments"] == 1
    assert note(a3, "doctor_leave"), "leave alert queued"
    admin("/api/admin/leave", {"doctor_id": 3, "day": TOMORROW, "remove": True})

    # F-04: daily cap, and queues projected past closing
    s, r = admin("/api/admin/doctor", {"name": "Dr. Cap", "department_id": 3, "username": "dr.cap", "password": "doctor1234",
                                       "max_patients": 1})
    cap = r["doctor_id"]
    assert patient()("/api/book", {"doctor_id": cap})[0] == 200
    s, r = patient()("/api/book", {"doctor_id": cap}); assert s == 409 and "fully booked" in r["error"], r
    dep = next(d for x in staff(f"/api/departments?day={TODAY}")[1]["departments"] for d in x["doctors"] if d["id"] == cap)
    assert dep["full"] and not dep["bookable"]
    s, r = staff("/api/staff/walkin", {"name": "Desk Patient", "doctor_id": cap})
    assert s == 200 and r["warning"] and "fully booked" in r["warning"], "the desk can still add someone standing there"
    admin("/api/admin/doctor/update", {"doctor_id": cap, "max_patients": "", "opd_start": "09:00", "opd_end": "09:20"})
    admin("/api/admin/policy", {"block_after_close": 1})
    assert patient()("/api/book", {"doctor_id": cap, "day": TOMORROW})[0] == 200   # 09:00
    assert patient()("/api/book", {"doctor_id": cap, "day": TOMORROW})[0] == 200   # 09:10, clears 09:20
    s, r = patient()("/api/book", {"doctor_id": cap, "day": TOMORROW}); assert s == 409 and "closing time" in r["error"], r
    admin("/api/admin/policy", {"block_after_close": 0})

    # F-14: doctors can have their own hours; ETAs start at the doctor's opening time
    first = staff(f"/api/queue?doctor_id={cap}&day={TOMORROW}")[1]
    assert first["doctor"]["opd_start"] == "09:00" and first["entries"][0]["eta"] == f"{TOMORROW}T09:00:00"
    assert admin("/api/admin/doctor/update", {"doctor_id": cap, "opd_start": "10:00", "opd_end": ""})[0] == 400, "both or neither"
    assert admin("/api/admin/doctor/update", {"doctor_id": cap, "opd_start": "11:00", "opd_end": "10:00"})[0] == 400

    # F-05: "unavailable" lasts only for the day it was set
    rao("/api/doctor/status", {"status": "unavailable"})
    assert q(1)["doctor"]["status"] == "unavailable"
    con.execute("UPDATE doctors SET status_day = ? WHERE id = 1", (YESTERDAY,)); con.commit()
    assert q(1)["doctor"]["status"] == "available", "next day starts available"

    # F-06: self check-in only near the turn, optionally with the reception code
    admin("/api/admin/policy", {"checkin_minutes": 5})
    ahead = [patient() for _ in range(3)]
    for p in ahead:
        p("/api/book", {"doctor_id": 2})
    late = patient()
    s, v = late("/api/book", {"doctor_id": 2})
    assert v["checkin_opens_at"], "ETA is more than 5 minutes away"
    s, r = late("/api/checkin", {"appointment_id": v["id"]}); assert s == 409 and "opens at" in r["error"], r
    assert staff("/api/checkin", {"appointment_id": v["id"]})[0] == 200, "the desk can always check someone in"
    admin("/api/admin/policy", {"checkin_minutes": 720, "require_checkin_code": 1})
    s, r = ahead[0]("/api/my-appointments"); aid = r["appointments"][0]["id"]
    assert ahead[0]("/api/checkin", {"appointment_id": aid})[0] == 403, "code required"
    code = staff("/api/admin/policy")[1]["checkin_code"]
    assert len(code) == 6 and ahead[0]("/api/checkin", {"appointment_id": aid, "code": code})[0] == 200
    admin("/api/admin/policy", {"require_checkin_code": 0, "checkin_minutes": 60})

    # F-07: booking window and per-patient limit
    lim = patient()
    s, r = lim("/api/book", {"doctor_id": 4, "day": (date.today() + timedelta(days=20)).isoformat()})
    assert s == 400 and "14 days" in r["error"], r
    admin("/api/admin/policy", {"max_active_bookings": 1})
    assert lim("/api/book", {"doctor_id": 4})[0] == 200
    s, r = lim("/api/book", {"doctor_id": 4, "day": TOMORROW}); assert s == 409 and "upcoming" in r["error"], r
    admin("/api/admin/policy", {"max_active_bookings": 10})

    # F-08, F-15: priority categories rank after emergencies; both can be removed with a reason
    pa, pb, pc = patient(), patient(), patient()
    ia, ib, ic = (p("/api/book", {"doctor_id": 4})[1]["id"] for p in (pa, pb, pc))
    assert act(staff, "priority", ic, category="Astronaut")[0] == 400
    act(staff, "priority", ic, category="Senior citizen")
    act(staff, "emergency", ib, reason="bleeding")
    order = [x["id"] for x in q(4)["entries"] if x["id"] in (ia, ib, ic)]
    assert order == [ib, ic, ia], order
    assert next(x for x in q(4)["entries"] if x["id"] == ic)["priority"] == "Senior citizen"
    assert act(staff, "remove_priority", ib)[0] == 400, "reason required"
    s, r = act(staff, "remove_priority", ib, reason="entered on the wrong patient"); assert s == 200
    assert not next(x for x in r["entries"] if x["id"] == ib)["emergency"]
    assert act(rao, "remove_priority", ic, reason="x")[0] == 403, "doctors do not change priority"
    assert admin("/api/admin/policy", {"priority_categories": "Emergency, Child"})[0] == 400

    # F-09: walk-ins at the desk
    s, w = staff("/api/staff/walkin", {"name": "Walk In", "phone": "+91 91111 11111", "doctor_id": 2})
    assert s == 200 and w["status"] == "checked_in" and w["username"].startswith("walkin-"), w
    s, again = staff("/api/staff/walkin", {"name": "walk in", "phone": "+91 91111 11111", "doctor_id": 2})
    assert again["existing"] and again["id"] == w["id"], "same name and phone: same patient, same booking"
    found = staff("/api/lookup?q=Walk%20In")[1]
    assert found["patients"][0]["username"] == w["username"] and found["results"]
    assert staff("/api/staff/walkin", {"name": "", "doctor_id": 2})[0] == 400

    # F-16: desk-assisted password reset, and reset by code
    wid = found["patients"][0]["id"]
    assert staff("/api/staff/patient-password", {"patient_id": wid, "password": "walkin-pass1"})[0] == 200
    c().login(w["username"], "walkin-pass1")
    forgot = patient()
    me = forgot("/api/me")[1]
    msg = c()("/api/password/forgot", {"username": me["username"]})[1]["message"]
    assert c()("/api/password/forgot", {"username": "nobody-here"})[1]["message"] == msg, "no account discovery"
    code_row = wait_for(lambda: con.execute("SELECT body FROM notifications WHERE patient_id = ? AND purpose = 'reset_code'",
                                            (me["id"],)).fetchone(), "reset code")
    real = code_row[0].split("code is ")[1][:6]
    assert c()("/api/password/reset", {"username": me["username"], "code": "000000" if real != "000000" else "111111",
                                       "new": "brand-new-1"})[0] == 400
    s, r = c()("/api/password/reset", {"username": me["username"], "code": real, "new": "brand-new-1"}); assert s == 200, r
    assert forgot("/api/me")[0] == 401, "old sessions end"
    c().login(me["username"], "brand-new-1")
    assert c()("/api/password/reset", {"username": me["username"], "code": real, "new": "again-new-1"})[0] == 400, "single use"

    # F-10: cancel, rebook and reschedule
    pr = patient()
    s, v = pr("/api/book", {"doctor_id": 1}); first_token = v["token"]
    assert pr("/api/cancel", {"appointment_id": v["id"]})[1]["status"] == "cancelled"
    assert not pr("/api/my-appointments")[1]["appointments"]
    s, again = pr("/api/book", {"doctor_id": 1}); assert s == 200 and again["id"] == v["id"] and again["token"] > first_token
    assert pr("/api/reschedule", {"appointment_id": v["id"], "doctor_id": 1, "day": TODAY})[0] == 400, "same slot"
    s, r = pr("/api/reschedule", {"appointment_id": v["id"], "doctor_id": 4, "day": "2001-01-01"}); assert s == 400
    assert pr("/api/my-appointments")[1]["appointments"][0]["id"] == v["id"], "refused reschedule keeps the old booking"
    s, moved = pr("/api/reschedule", {"appointment_id": v["id"], "doctor_id": 2, "day": TOMORROW}); assert s == 200, moved
    mine = pr("/api/my-appointments")[1]["appointments"]
    assert [(x["doctor"]["id"], x["day"]) for x in mine] == [(2, TOMORROW)]
    assert staff("/api/cancel", {"appointment_id": moved["id"], "reason": "duplicate"})[0] == 200
    assert note(moved["id"], "cancelled"), "desk cancellations are sent to the patient"
    assert patient()("/api/cancel", {"appointment_id": moved["id"]})[0] == 404, "not your booking"

    # F-11: family members book under one account; alerts reach the guardian
    parent = patient()
    kids = parent("/api/dependants", {"name": "Child One"})[1]["dependants"]
    kids = parent("/api/dependants", {"name": "Child Two"})[1]["dependants"]
    k1, k2 = (k["id"] for k in kids)
    s1, b1 = parent("/api/book", {"doctor_id": 3, "patient_id": k1})
    s2, b2 = parent("/api/book", {"doctor_id": 3, "patient_id": k2})
    assert s1 == s2 == 200 and b1["id"] != b2["id"], "two children, same doctor, same day"
    assert {x["patient_id"] for x in parent("/api/my-appointments")[1]["appointments"]} == {k1, k2}
    assert patient()("/api/book", {"doctor_id": 3, "patient_id": k1})[0] == 404, "not your family"
    parent("/api/checkin", {"appointment_id": b1["id"]})
    act(c().login("dr.khan", "doctor123"), "call_next")
    guardian_phone = parent("/api/me")[1]["phone"]
    assert note(b1["id"], "called")[0] == guardian_phone
    assert parent("/api/dependants/remove", {"patient_id": k2})[0] == 409, "has a booking"
    parent("/api/cancel", {"appointment_id": b2["id"]})
    assert len(parent("/api/dependants/remove", {"patient_id": k2})[1]["dependants"]) == 1

    # F-12: reception display shows tokens only and needs the display key
    assert c()("/api/display")[0] == 403 and c()("/api/display?key=wrong")[0] == 403
    key = staff("/api/admin/policy")[1]["display_key"]
    s, raw_display, body = c().raw(f"/api/display?key={key}")
    board = json.loads(body)
    assert s == 200 and board["doctors"] and "Patient" not in body.decode() and "Child" not in body.decode()

    # F-13: move one patient, or everyone waiting, to a colleague in the same department
    m1, m2, m3 = patient(), patient(), patient()
    t1, t2, t3 = (p("/api/book", {"doctor_id": 2})[1]["id"] for p in (m1, m2, m3))
    assert act(staff, "transfer", t1, to_doctor_id=4)[0] == 400, "other department"
    s, r = act(staff, "transfer", t1, to_doctor_id=1); assert s == 200
    assert con.execute("SELECT doctor_id FROM appointments WHERE id = ?", (t1,)).fetchone()[0] == 1
    assert note(t1, "transferred")
    s, r = act(staff, "transfer_all", None, doctor_id=2, to_doctor_id=1); assert s == 200 and "Moved" in r["message"], r
    assert not [x for x in r["entries"] if x["status"] in ("booked", "checked_in")]
    assert {t2, t3} <= {x["id"] for x in q(1)["entries"]}

    # F-17, F-19: analytics from real visits, with measured ETA accuracy
    s, an = admin("/api/admin/analytics"); assert s == 200
    assert an["total"]["seen"] >= 1 and an["total"]["eta_n"] >= 1 and len(an["by_hour"]) == 24
    assert any(d["cancelled"] for d in an["doctors"])
    s, _, csv_data = admin.raw("/api/admin/export?kind=analytics")
    assert s == 200 and csv_data.decode().startswith("doctor,department,booked") and "All doctors" in csv_data.decode()
    assert admin("/api/admin/analytics?from=2026-12-01&to=2026-01-01")[0] == 400

    # F-18: the usual consultation time is learned from earlier days
    s, r = admin("/api/admin/doctor", {"name": "Dr. Learn", "department_id": 1, "username": "dr.learn", "password": "doctor1234",
                                       "avg_minutes": 10})
    learn = r["doctor_id"]
    for i in range(10):
        day = (date.today() - timedelta(days=2 + i)).isoformat()
        con.execute("""INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at, status, started_at, ended_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""", (pid, learn, day, 1, 1, day + "T09:00", "completed", day + "T09:00:00", day + "T09:20:00"))
    con.commit()
    d = next(x for x in admin("/api/admin/doctors")[1]["doctors"] if x["id"] == learn)
    assert (d["learned_minutes"], d["learned_from"]) == (20, 10), d
    assert staff(f"/api/queue?doctor_id={learn}")[1]["avg_minutes"] == 20

    # F-20, F-21: alert language and the patient's own alert lead time
    assert c()("/api/register", {"username": "badlang", "password": "longenough", "name": "B", "lang": "xx"})[0] == 400
    assert c()("/api/register", {"username": "badlead", "password": "longenough", "name": "B", "alert_lead": 2})[0] == 400
    s, r = admin("/api/admin/doctor", {"name": "Dr. Lead", "department_id": 1, "username": "dr.lead", "password": "doctor1234",
                                       "avg_minutes": 8})
    lead_doc = r["doctor_id"]
    for p in (patient(), patient()):
        p("/api/book", {"doctor_id": lead_doc})
    hindi_short = patient(lang="hi", alert_lead=5)
    default = patient()
    vs = hindi_short("/api/book", {"doctor_id": lead_doc})[1]   # ETA about 16 minutes away
    vd = default("/api/book", {"doctor_id": lead_doc})[1]       # about 24 minutes away, inside the 30-minute default
    assert not vs["arrival_alert"] and vd["arrival_alert"]
    assert not note(vs["id"], "arrival") and note(vd["id"], "arrival")
    act(staff, "emergency", vs["id"], reason="test")
    act(staff, "transfer", vs["id"], to_doctor_id=1)
    assert any("ऀ" <= ch <= "ॿ" for ch in note(vs["id"], "transferred")[1]), "Hindi text"
    assert hindi_short("/api/profile", {"channel": "sms", "phone": "+91 90000 99999", "lang": "en", "alert_lead": 45})[1]["alert_lead"] == 45

    # F-22: audit log filters and pages
    con.executemany("INSERT INTO events(at, action, detail) VALUES(?, 'filler', 'paging check')",
                    [(datetime.now().isoformat(timespec="seconds"),)] * 250)
    con.commit()
    ev = admin("/api/admin/events?action=cancelled")[1]
    assert ev["events"] and all(e["action"] == "cancelled" for e in ev["events"]) and "cancelled" in ev["actions"]
    assert all("bleeding" in (e["detail"] or "") for e in admin("/api/admin/events?q=bleeding")[1]["events"])
    page = admin("/api/admin/events")[1]
    assert page["more"] and len(page["events"]) == 200
    older = admin(f"/api/admin/events?before={page['events'][-1]['id']}")[1]["events"]
    assert older and older[0]["id"] < page["events"][-1]["id"]

    # F-23: live updates over server-sent events
    host, port = base[7:].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    cookie = next(ck for h in staff.op.handlers if hasattr(h, "cookiejar") for ck in h.cookiejar if ck.name == "sid")
    conn.request("GET", "/api/stream", headers={"Cookie": f"sid={cookie.value}"})
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type") == "text/event-stream"
    admin("/api/admin/department", {"name": "Live Update Check"})
    line = resp.fp.readline()
    while line.startswith(b":") or line == b"\n":
        line = resp.fp.readline()
    assert line.startswith(b"data: "), line
    conn.close()
    assert c().raw("/api/stream")[0] == 401

    # F-24: data retention and "delete my data"
    con.execute("INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at, status) VALUES(?,?,?,?,?,?,?)",
                (pid, 1, "2020-01-01", 1, 1, "2020-01-01T09:00", "completed"))
    con.execute("INSERT INTO events(at, action) VALUES('2020-01-01T09:00:00', 'old_event')")
    con.commit()
    assert admin("/api/admin/policy", {"retention_days": 365})[0] == 200
    assert not con.execute("SELECT 1 FROM appointments WHERE day = '2020-01-01'").fetchone()
    assert not con.execute("SELECT 1 FROM events WHERE action = 'old_event'").fetchone()
    assert con.execute("SELECT 1 FROM events WHERE action = 'retention_purge'").fetchone()
    admin("/api/admin/policy", {"retention_days": 0})
    gone = patient()
    gid = gone("/api/me")[1]["id"]
    kid = gone("/api/dependants", {"name": "Kid Gone"})[1]["dependants"][0]["id"]
    gb = gone("/api/book", {"doctor_id": 1, "patient_id": kid})[1]["id"]
    assert gone("/api/delete-account", {"password": "wrong-pass"})[0] == 403
    assert gone("/api/delete-account", {"password": "longenough"})[0] == 200
    assert gone("/api/me")[0] == 401
    assert con.execute("SELECT name, phone, active FROM users WHERE id IN (?, ?)", (gid, kid)).fetchall() == [("Deleted patient", None, 0)] * 2
    assert con.execute("SELECT status FROM appointments WHERE id = ?", (gb,)).fetchone()[0] == "cancelled"

    # F-25: daily and manual backups
    assert any(b["name"].endswith("-daily.db") for b in admin("/api/admin/backups")[1]["backups"])
    s, r = admin("/api/admin/backup", {}); assert s == 200
    path = Path(admin("/api/admin/backups")[1]["folder"]) / r["name"]
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM users").fetchone()[0] > 5, "a usable copy"


def check_upgrade_from_1_0():
    """A database made by version 1.0 (commit 35b04bb) upgrades in place, with a backup, and keeps its data."""
    old = Path(TMP) / "v1_0"
    old.mkdir(exist_ok=True)
    for f in ("server.py", "engine.py", "notify.py", "index.html"):
        shown = subprocess.run(["git", "show", f"35b04bb:app/{f}"], capture_output=True, cwd=HERE)
        if shown.returncode:
            print("  upgrade check skipped: version 1.0 is not in this git history")
            return
        (old / f).write_bytes(shown.stdout)
    db = f"{TMP}/upgrade.db"
    proc = subprocess.Popen([sys.executable, str(old / "server.py"), "0", "--demo"], env={"OPD_DB": db, "PATH": ""},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(lambda: Path(db).exists() and sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'notifications'").fetchone()[0], "1.0 schema", 15)
    finally:
        proc.terminate()
        proc.wait(5)
    con = sqlite3.connect(db)
    wait_for(lambda: con.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 8, "1.0 demo data", 10)
    pid = con.execute("SELECT id FROM users WHERE username = 'patient'").fetchone()[0]
    con.execute("INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at, priority) VALUES(?,?,?,?,?,?,?)",
                (pid, 1, TODAY, 1, 1, TODAY + "T08:00:00", 1))
    con.commit()
    con.close()
    proc, base = start_server(db, demo=False)
    try:
        staff = Client(base).login("staff", "staff123")
        e = staff("/api/queue?doctor_id=1")[1]["entries"][0]
        assert e["emergency"] and e["priority"] == "emergency", "1.0 emergencies keep their priority"
        assert staff("/api/cancel", {"appointment_id": e["id"]})[1]["status"] == "cancelled", "new status works"
        patient = Client(base).login("patient", "patient123")
        assert patient("/api/dependants", {"name": "New Child"})[0] == 200, "new columns work"
    finally:
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    assert "Upgrading the database" in log and "Traceback" not in log, log
    assert list((Path(TMP) / "backups").glob("opd-*-pre-upgrade.db")), "backup taken before the upgrade"
    assert sqlite3.connect(db).execute("PRAGMA foreign_key_check").fetchall() == []


if __name__ == "__main__":
    main()
