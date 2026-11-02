"""Smart OPD web server: JSON API, SQLite storage, notification worker and the single-page UI.

Run:  python3 app/server.py --demo     (local demo with sample doctors and accounts)
      python3 app/server.py            (production: creates only an admin account)
Settings come from environment variables; see README.md.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import ssl
import sys
import threading
import time as wallclock
import traceback
from datetime import date, datetime, time, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import engine
import notify

HERE = Path(__file__).parent
DB_PATH = os.environ.get("OPD_DB", str(HERE / "opd.db"))
SIM_DIR = Path(os.environ.get("OPD_SIM_DIR", str(HERE / "sim_results")))
TLS_CERT, TLS_KEY = os.environ.get("OPD_TLS_CERT"), os.environ.get("OPD_TLS_KEY")
TICK_SECONDS = float(os.environ.get("OPD_TICK_SECONDS", "30"))       # arrival-alert check interval
DISPATCH_SECONDS = float(os.environ.get("OPD_DISPATCH_SECONDS", "5"))  # notification send interval
SESSION_HOURS = 12
MAX_BODY = 1_000_000
LOCKOUT_FAILS, LOCKOUT_MINUTES = 5, 5
ROLES = ("patient", "doctor", "staff", "admin", "tester")

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS doctors(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  department_id INTEGER NOT NULL REFERENCES departments(id),
  avg_minutes REAL NOT NULL DEFAULT 10,
  status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','break','delayed','unavailable')),
  break_until TEXT,
  work_days TEXT NOT NULL DEFAULT '0123456',
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS doctor_leave(
  doctor_id INTEGER NOT NULL REFERENCES doctors(id), day TEXT NOT NULL, PRIMARY KEY(doctor_id, day));
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('patient','doctor','staff','admin','tester')),
  name TEXT NOT NULL, phone TEXT, email TEXT,
  channel TEXT NOT NULL DEFAULT 'none' CHECK(channel IN ('sms','email','none')),
  doctor_id INTEGER REFERENCES doctors(id), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY,
  patient_id INTEGER NOT NULL REFERENCES users(id),
  doctor_id INTEGER NOT NULL REFERENCES doctors(id),
  day TEXT NOT NULL, token INTEGER NOT NULL, position REAL NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'booked'
    CHECK(status IN ('booked','checked_in','called','in_consultation','completed','skipped')),
  booked_at TEXT NOT NULL, checked_in_at TEXT, due_at TEXT, started_at TEXT, ended_at TEXT,
  skip_reason TEXT, promised_at TEXT, arrival_alerted INTEGER NOT NULL DEFAULT 0,
  UNIQUE(patient_id, doctor_id, day), UNIQUE(doctor_id, day, token));
CREATE INDEX IF NOT EXISTS appt_queue ON appointments(doctor_id, day);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL, doctor_id INTEGER, day TEXT, appointment_id INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS events_queue ON events(doctor_id, day);
CREATE TABLE IF NOT EXISTS eta_snapshots(
  id INTEGER PRIMARY KEY, appointment_id INTEGER NOT NULL REFERENCES appointments(id),
  eta TEXT, calculated_at TEXT NOT NULL, queue_version INTEGER NOT NULL, cause TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS eta_by_appt ON eta_snapshots(appointment_id);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, appointment_id INTEGER REFERENCES appointments(id),
  patient_id INTEGER NOT NULL REFERENCES users(id), purpose TEXT NOT NULL, channel TEXT NOT NULL,
  recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','delivered','unconfirmed','failed')),
  attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  next_try TEXT NOT NULL, detail TEXT, event_key TEXT UNIQUE NOT NULL);
CREATE INDEX IF NOT EXISTS notif_status ON notifications(status, next_try);
CREATE INDEX IF NOT EXISTS notif_appt ON notifications(appointment_id);
"""

DEFAULT_POLICY = {"opd_start": "09:00", "opd_end": "17:00", "grace_minutes": "10", "alert_minutes": "30",
                  "eta_change_minutes": "15", "notify_retries": "2"}

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA foreign_keys = ON")
db.execute("PRAGMA journal_mode = WAL")
# ponytail: one global lock serialises every request, which also makes queue actions atomic (PR-003); per-queue locks if load grows
lock = threading.Lock()
failed_logins = {}  # username: (count, locked_until)
sim_jobs = {}       # job id: status dict
DEMO = False


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# ---------- helpers ----------

def now():
    return datetime.now().replace(microsecond=0)


def today():
    return date.today().isoformat()


def parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def iso(dt):
    return dt.isoformat() if dt else None


def rows(sql, *args):
    return [dict(r) for r in db.execute(sql, args)]


def row(sql, *args):
    r = db.execute(sql, args).fetchone()
    return dict(r) if r else None


def need(body, key, cast=str):
    value = body.get(key)
    if value in (None, ""):
        raise HTTPError(400, f"Missing field: {key}.")
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise HTTPError(400, f"Invalid value for {key}.")


def parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPError(400, "Dates must look like 2026-11-02.")


def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def check_pw(password, stored):
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_pw(password, salt), stored)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def policy():
    return {**DEFAULT_POLICY, **{r["key"]: r["value"] for r in rows("SELECT * FROM policy")}}


def log(actor, action, doctor_id=None, day=None, appointment_id=None, detail=None):
    """Queue history and audit log in one table (FR-016, FR-027, FR-039)."""
    db.execute("INSERT INTO events(at, actor_id, action, doctor_id, day, appointment_id, detail) VALUES(?,?,?,?,?,?,?)",
               (iso(now()), actor and actor["id"], action, doctor_id, day, appointment_id, detail))


def doctor_or_404(doctor_id):
    doc = row("""SELECT d.*, dep.name AS department FROM doctors d JOIN departments dep ON dep.id = d.department_id
                 WHERE d.id = ?""", doctor_id)
    if not doc:
        raise HTTPError(404, "Doctor not found.")
    return doc


def effective_status(doc, t):
    """A break or delay that has run out counts as available again."""
    if doc["status"] in ("break", "delayed") and (not doc["break_until"] or parse(doc["break_until"]) <= t):
        return "available"
    return doc["status"]


def holds_opd(doc, d):
    """Whether the doctor runs OPD on that date: active, a working weekday, not on leave."""
    return (doc["active"] and str(d.weekday()) in doc["work_days"]
            and not row("SELECT 1 FROM doctor_leave WHERE doctor_id = ? AND day = ?", doc["id"], d.isoformat()))


def valid_contact(phone, email, channel):
    if phone and not re.fullmatch(r"\+?[0-9 ]{7,16}", phone):
        raise HTTPError(400, "Phone numbers may contain digits, spaces and a leading +.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPError(400, "That email address does not look right.")
    if channel not in ("sms", "email", "none"):
        raise HTTPError(400, "Alert channel must be sms, email or none.")
    if channel == "sms" and not phone:
        raise HTTPError(400, "Add a phone number to get SMS alerts.")
    if channel == "email" and not email:
        raise HTTPError(400, "Add an email address to get email alerts.")


# ---------- queue state, ETA snapshots and alerts ----------

def queue_entries(doctor_id, day):
    entries = rows("""SELECT a.*, u.name AS patient_name FROM appointments a
                      JOIN users u ON u.id = a.patient_id WHERE a.doctor_id = ? AND a.day = ?""", doctor_id, day)
    for e in entries:
        e["due_at"], e["started_at"], e["promised"] = parse(e["due_at"]), parse(e["started_at"]), parse(e["promised_at"])
    return entries


def queue_version(doctor_id, day):
    return row("SELECT COUNT(*) AS n FROM events WHERE doctor_id = ? AND day = ?", doctor_id, day)["n"]


def queue_state(doctor_id, day):
    """Current queue for one doctor and day with fresh ETAs. ETAs are recomputed on
    every read, so every view sees the latest committed state (FR-012, FR-013)."""
    doc = doctor_or_404(doctor_id)
    p, t = policy(), now()
    entries = queue_entries(doctor_id, day)
    done = sorted((e for e in entries if e["status"] == "completed" and e["ended_at"]), key=lambda e: e["ended_at"])
    avg = engine.expected_minutes([(parse(e["ended_at"]) - e["started_at"]).total_seconds() / 60 for e in done],
                                  doc["avg_minutes"])
    status = effective_status(doc, t)
    d = date.fromisoformat(day)
    available = status != "unavailable" and holds_opd(doc, d)
    opd_start = datetime.combine(d, time.fromisoformat(p["opd_start"]))
    etas = engine.compute_etas(entries, t, avg, opd_start, available=available,
                               break_until=parse(doc["break_until"]) if status in ("break", "delayed") else None)
    rank = {e["id"]: i for i, e in enumerate(engine.order(entries))}
    grace = int(p["grace_minutes"])
    out = []
    for e in sorted(entries, key=lambda e: (e["id"] not in rank, rank.get(e["id"], 0), e["token"])):
        out.append({
            "id": e["id"], "token": e["token"], "patient_name": e["patient_name"], "status": e["status"],
            "emergency": bool(e["priority"]), "checked_in_at": e["checked_in_at"], "skip_reason": e["skip_reason"],
            "turn_missed": e["due_at"] is not None and e["status"] == "booked",
            "can_skip": engine.can_skip(e, t, grace),
            "ahead": rank.get(e["id"]), "eta": iso(etas.get(e["id"])),
        })
    return {"doctor": {"id": doc["id"], "name": doc["name"], "department": doc["department"], "status": status,
                       "break_until": doc["break_until"] if status in ("break", "delayed") else None,
                       "holds_opd": bool(holds_opd(doc, d))},
            "day": day, "avg_minutes": round(avg, 1), "version": queue_version(doctor_id, day),
            "updated_at": iso(t), "entries": out}


MESSAGES = {
    "arrival": ("Your turn is near",
                "Token {token} with {doctor}: expected around {eta}. Please come to the OPD and check in if you have not. "
                "This time is an estimate and may change."),
    "eta_change": ("Your expected time has changed",
                   "Token {token} with {doctor}: now expected around {eta}. This time is an estimate and may change."),
    "called": ("Please go in now", "Token {token}: {doctor} is calling you now."),
    "skipped": ("You missed your turn",
                "Token {token} with {doctor} was skipped because you had not checked in. "
                "Check in when you arrive and you will rejoin the queue."),
    "doctor_unavailable": ("Doctor unavailable",
                           "{doctor} is currently unavailable. Your expected time will update when they are back."),
}


def enqueue(appt_id, purpose, key, eta=None):
    """Queue an alert for the worker. The unique event key stops duplicates (FR-021).
    Patients without a usable channel still see everything in the app (FR-017)."""
    a = row("""SELECT a.*, u.phone, u.email, u.channel, d.name AS doctor FROM appointments a
               JOIN users u ON u.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id WHERE a.id = ?""", appt_id)
    recipient = {"sms": a["phone"], "email": a["email"]}.get(a["channel"])
    if not recipient:
        return
    subject, body = MESSAGES[purpose]
    body = body.format(token=a["token"], doctor=a["doctor"], eta=eta.strftime("%H:%M") if eta else "")
    t = iso(now())
    db.execute("""INSERT OR IGNORE INTO notifications(appointment_id, patient_id, purpose, channel, recipient, subject, body,
                  created_at, updated_at, next_try, event_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (appt_id, a["patient_id"], purpose, a["channel"], recipient, subject, body, t, t, t, key))


def after_change(doctor_id, day, cause):
    """Run after every committed material event (and by the ticker): store ETAs that
    moved (D7, FR-016) and queue alerts per decision table 4 (FR-017, FR-018, FR-032)."""
    q = queue_state(doctor_id, day)
    p, t, is_today = policy(), now(), day == today()
    for e in q["entries"]:
        if e["ahead"] is None:
            continue
        last = row("SELECT eta FROM eta_snapshots WHERE appointment_id = ? ORDER BY id DESC LIMIT 1", e["id"])
        eta = parse(e["eta"])
        moved = abs((eta - parse(last["eta"])).total_seconds()) / 60 if last and last["eta"] and eta else None
        # ponytail: background ticks store only shifts of 5+ minutes to keep the table small
        if last is None or (last["eta"] != e["eta"] and (cause != "tick" or moved is None or moved >= 5)):
            db.execute("INSERT INTO eta_snapshots(appointment_id, eta, calculated_at, queue_version, cause) VALUES(?,?,?,?,?)",
                       (e["id"], e["eta"], iso(t), q["version"], cause))
        if not is_today or e["status"] not in engine.WAITING:
            continue
        a = row("SELECT promised_at, arrival_alerted FROM appointments WHERE id = ?", e["id"])
        told = parse(a["promised_at"])
        to_eta = (eta - t).total_seconds() / 60 if eta else None
        shift = abs((eta - told).total_seconds()) / 60 if eta and told else None
        for purpose in notify.alert_purposes(to_eta, shift, a["arrival_alerted"], int(p["alert_minutes"]),
                                             int(p["eta_change_minutes"])):
            enqueue(e["id"], purpose, f"{purpose}:{e['id']}" if purpose == "arrival" else f"{purpose}:{e['id']}:{e['eta']}", eta)
            # the patient was told this time: it becomes their no-show cutoff (engine.turn_cutoff)
            db.execute("UPDATE appointments SET promised_at = ?, arrival_alerted = arrival_alerted OR ? WHERE id = ?",
                       (e["eta"], purpose == "arrival", e["id"]))
        if cause == "doctor_unavailable":
            enqueue(e["id"], "doctor_unavailable", f"doctor_unavailable:{e['id']}:{q['version']}")


def material(user, action, doctor_id, day, appointment_id=None, detail=None):
    """Log a queue event, then refresh ETAs and alerts: the single path for queue changes."""
    log(user, action, doctor_id, day, appointment_id, detail)
    after_change(doctor_id, day, action)


def can_operate(user, doctor_id, roles):
    """Doctors may only act on their own queue; staff and admins on any queue."""
    if user["role"] == "doctor":
        return "doctor" in roles and user["doctor_id"] == doctor_id
    return user["role"] in roles


# ---------- routes ----------

ROUTES = {}


def route(method, path, roles=None):
    """roles=None means public; otherwise the signed-in user's role must be listed."""
    def deco(fn):
        ROUTES[(method, path)] = (fn, roles)
        return fn
    return deco


@route("GET", "/api/health")
def health(user, body):
    return {"ok": True, "version": engine.VERSION, "demo": DEMO, "time": iso(now())}


@route("POST", "/api/register")
def register(user, body):
    username, password = need(body, "username").strip().lower(), need(body, "password")
    name = need(body, "name").strip()
    phone, email = (body.get("phone") or "").strip(), (body.get("email") or "").strip()
    channel = body.get("channel") or ("sms" if phone else "email" if email else "none")
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise HTTPError(400, "Usernames are 3 to 40 letters, digits, dots, dashes or underscores.")
    if len(password) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    valid_contact(phone, email, channel)
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken. Choose another.")
    db.execute("INSERT INTO users(username, pw, role, name, phone, email, channel) VALUES(?,?,?,?,?,?,?)",
               (username, hash_pw(password), "patient", name, phone or None, email or None, channel))
    return login(None, body)


@route("POST", "/api/login")
def login(user, body):
    username, t = need(body, "username").strip().lower(), now()
    fails, until = failed_logins.get(username, (0, None))
    if until and until > t:
        raise HTTPError(429, f"Too many failed attempts. Try again after {until.strftime('%H:%M')}.")
    u = row("SELECT * FROM users WHERE username = ?", username)
    if not u or not u["active"] or not check_pw(need(body, "password"), u["pw"]):
        fails += 1
        failed_logins[username] = (fails, t + timedelta(minutes=LOCKOUT_MINUTES) if fails >= LOCKOUT_FAILS else None)
        raise HTTPError(401, "Wrong username or password.")
    failed_logins.pop(username, None)
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE created < ?", (iso(t - timedelta(hours=SESSION_HOURS)),))
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), u["id"], iso(t)))
    return {"_cookie": token, **public_user(u)}


@route("POST", "/api/logout", ROLES)
def logout(user, body):
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    return {"_cookie": "", "ok": True}


def public_user(u):
    return {k: u[k] for k in ("id", "username", "role", "name", "doctor_id", "phone", "email", "channel")}


@route("GET", "/api/me", ROLES)
def me(user, body):
    return public_user(user)


@route("POST", "/api/profile", ("patient",))
def profile(user, body):
    """Patients keep their contact details and alert channel up to date (FR-003)."""
    phone, email = (body.get("phone") or "").strip(), (body.get("email") or "").strip()
    channel = body.get("channel") or "none"
    valid_contact(phone, email, channel)
    db.execute("UPDATE users SET phone = ?, email = ?, channel = ? WHERE id = ?", (phone or None, email or None, channel, user["id"]))
    return public_user(row("SELECT * FROM users WHERE id = ?", user["id"]))


@route("GET", "/api/departments", ROLES)
def departments(user, body):
    """Departments with active doctors and their load on the chosen day, so patients can
    see less busy options in the same department (FR-034, FR-035: advisory only)."""
    day = body.get("day") or today()
    d = parse_day(day)
    deps = rows("SELECT * FROM departments ORDER BY name")
    for dep in deps:
        dep["doctors"] = []
        for doc in rows("SELECT id FROM doctors WHERE department_id = ? AND active = 1 ORDER BY name", dep["id"]):
            q = queue_state(doc["id"], day)
            waiting = [e for e in q["entries"] if e["ahead"] is not None]
            last = max((e["eta"] for e in waiting if e["eta"]), default=None)
            clears = iso(parse(last) + timedelta(minutes=q["avg_minutes"])) if last else None
            open_ = q["doctor"]["holds_opd"] and not (d == date.today() and q["doctor"]["status"] == "unavailable")
            dep["doctors"].append({**q["doctor"], "waiting": len(waiting), "clears_at": clears, "bookable": bool(open_)})
    return {"departments": deps, "day": day}


@route("POST", "/api/book", ("patient",))
def book(user, body):
    """Booking validation follows decision tree DT-1 and decision table 1."""
    doctor_id = need(body, "doctor_id", int)
    day = body.get("day") or today()
    d = parse_day(day)
    t, p = now(), policy()
    doc = doctor_or_404(doctor_id)
    if d < t.date():
        raise HTTPError(400, "Choose today or a later date.")
    if not holds_opd(doc, d):
        raise HTTPError(409, f"{doc['name']} does not hold OPD on {day}. Choose another date or doctor.")
    if d == t.date() and effective_status(doc, t) == "unavailable":
        raise HTTPError(409, f"{doc['name']} is not available today. Choose another doctor or date.")
    if d == t.date() and t.time() >= time.fromisoformat(p["opd_end"]):
        raise HTTPError(409, f"OPD has closed for today (closes {p['opd_end']}). Choose another date.")
    existing = row("SELECT id FROM appointments WHERE patient_id = ? AND doctor_id = ? AND day = ?", user["id"], doctor_id, day)
    if existing:  # FR-009: a repeat submission returns the same booking instead of a duplicate
        return {"existing": True, **appointment_view(existing["id"])}
    entries = queue_entries(doctor_id, day)
    token = max((e["token"] for e in entries), default=0) + 1
    appt_id = db.execute("INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at) VALUES(?,?,?,?,?,?)",
                         (user["id"], doctor_id, day, token, engine.end_position(entries), iso(t))).lastrowid
    material(user, "booked", doctor_id, day, appt_id, f"token {token}")
    first = appointment_view(appt_id)
    db.execute("UPDATE appointments SET promised_at = ? WHERE id = ?", (first["eta"], appt_id))  # the time the patient was given
    return {"existing": False, **first}


def appointment_view(appt_id):
    a = row("SELECT * FROM appointments WHERE id = ?", appt_id)
    q = queue_state(a["doctor_id"], a["day"])
    e = next(x for x in q["entries"] if x["id"] == appt_id)
    eta = parse(e["eta"])
    alert = (eta is not None and a["status"] in engine.WAITING and a["day"] == today()
             and eta - now() <= timedelta(minutes=int(policy()["alert_minutes"])))
    notes = rows("""SELECT purpose, channel, status, created_at, updated_at FROM notifications
                    WHERE appointment_id = ? ORDER BY id DESC LIMIT 3""", appt_id)
    return {**e, "doctor": q["doctor"], "day": a["day"], "updated_at": q["updated_at"], "arrival_alert": alert,
            "notifications": notes}


@route("GET", "/api/my-appointments", ("patient",))
def my_appointments(user, body):
    ids = rows("SELECT id FROM appointments WHERE patient_id = ? AND day >= ? ORDER BY day, token",
               user["id"], (date.today() - timedelta(days=1)).isoformat())
    return {"appointments": [appointment_view(r["id"]) for r in ids], "alert_minutes": int(policy()["alert_minutes"])}


@route("POST", "/api/checkin", ("patient", "staff", "admin"))
def checkin(user, body):
    a = row("SELECT * FROM appointments WHERE id = ?", need(body, "appointment_id", int))
    if not a or (user["role"] == "patient" and a["patient_id"] != user["id"]):
        raise HTTPError(404, "Appointment not found.")
    if a["day"] != today():
        raise HTTPError(409, "Check-in opens on the day of the appointment.")
    t = iso(now())
    if a["status"] == "booked":
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ? WHERE id = ?", (t, a["id"]))
        material(user, "checked_in", a["doctor_id"], a["day"], a["id"])
    elif a["status"] == "skipped":  # late arrival: back in at the end of the eligible queue by default (FR-026)
        pos = engine.end_position(queue_entries(a["doctor_id"], a["day"]))
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ?, due_at = NULL, position = ? WHERE id = ?",
                   (t, pos, a["id"]))
        material(user, "reinserted", a["doctor_id"], a["day"], a["id"], "late check-in, end of queue")
    else:
        raise HTTPError(409, "This appointment is already checked in.")
    return appointment_view(a["id"])


@route("GET", "/api/queue", ("doctor", "staff", "admin"))
def queue(user, body):
    doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    return queue_state(doctor_id, body.get("day") or today())


@route("GET", "/api/lookup", ("staff", "admin"))
def lookup(user, body):
    """Front-desk patient lookup by name, username, phone or token for today."""
    term = need(body, "q").strip()
    like = f"%{term}%"
    return {"results": rows("""SELECT a.id, a.token, a.status, a.day, u.name AS patient_name, u.phone, d.name AS doctor, d.id AS doctor_id
                               FROM appointments a JOIN users u ON u.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id
                               WHERE a.day = ? AND (u.name LIKE ? OR u.username LIKE ? OR u.phone LIKE ? OR CAST(a.token AS TEXT) = ?)
                               ORDER BY d.name, a.token LIMIT 50""", today(), like, like, like, term)}


QUEUE_ACTIONS = {  # action: roles allowed
    "call_next": ("doctor", "staff"), "start": ("doctor",), "complete": ("doctor",),
    "skip": ("doctor", "staff"), "emergency": ("staff", "admin"), "reinsert_front": ("staff", "admin"),
}


@route("POST", "/api/queue/action", ("doctor", "staff", "admin"))
def queue_action(user, body):
    action = need(body, "action")
    if action not in QUEUE_ACTIONS:
        raise HTTPError(400, f"Unknown action: {action}.")
    day = today()
    if action == "call_next":
        a = None
        doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    else:
        a = row("SELECT * FROM appointments WHERE id = ? AND day = ?", need(body, "appointment_id", int), day)
        if not a:
            raise HTTPError(404, "No such appointment in today's queue.")
        doctor_id = a["doctor_id"]
    if not can_operate(user, doctor_id, QUEUE_ACTIONS[action]):
        raise HTTPError(403, "You do not have permission for this action on this queue.")
    if "version" in body and int(body["version"]) != queue_version(doctor_id, day):  # PR-003: no silent overwrite
        raise HTTPError(409, "The queue changed since you loaded it. It has been refreshed; try again.")
    t, reason = now(), (body.get("reason") or "").strip()
    entries = queue_entries(doctor_id, day)

    if action == "call_next":
        if any(e["status"] in ("called", "in_consultation") for e in entries):
            raise HTTPError(409, "Finish the current patient before calling the next one.")
        chosen, missed = engine.next_to_call(entries)
        for e in missed:
            if e["due_at"] is None:  # their turn came but they are not here: grace starts (never before their given time)
                db.execute("UPDATE appointments SET due_at = ? WHERE id = ?", (iso(engine.turn_cutoff(e, t)), e["id"]))
                log(user, "turn_missed", doctor_id, day, e["id"], f"token {e['token']} not checked in")
        if not chosen:
            after_change(doctor_id, day, "turn_missed")
            if missed:
                return {"called": None, "message": "Nobody waiting has checked in yet.", **queue_state(doctor_id, day)}
            raise HTTPError(409, "No patients are waiting.")
        db.execute("UPDATE appointments SET status = 'called' WHERE id = ?", (chosen["id"],))
        material(user, "called", doctor_id, day, chosen["id"], f"token {chosen['token']}")
        enqueue(chosen["id"], "called", f"called:{chosen['id']}")
        return {"called": chosen["token"], **queue_state(doctor_id, day)}

    entry = next(e for e in entries if e["id"] == a["id"])
    if action == "start":
        if a["status"] != "called":
            raise HTTPError(409, "Call this patient before starting the consultation.")
        db.execute("UPDATE appointments SET status = 'in_consultation', started_at = ? WHERE id = ?", (iso(t), a["id"]))
    elif action == "complete":
        if a["status"] != "in_consultation":
            raise HTTPError(409, "This consultation has not started.")
        db.execute("UPDATE appointments SET status = 'completed', ended_at = ? WHERE id = ?", (iso(t), a["id"]))
    elif action == "skip":
        if not engine.can_skip(entry, t, int(policy()["grace_minutes"])):
            raise HTTPError(409, "This patient cannot be skipped yet: their grace period has not run out.")
        # FR-025: the record stays, marked skipped with the reason
        db.execute("UPDATE appointments SET status = 'skipped', skip_reason = ? WHERE id = ?", (reason or "no-show", a["id"]))
        enqueue(a["id"], "skipped", f"skipped:{a['id']}:{queue_version(doctor_id, day)}")
    elif action == "emergency":  # staff-controlled; the system never judges urgency (FR-029, FR-030)
        if a["status"] not in engine.WAITING:
            raise HTTPError(409, "Only a waiting patient can be given emergency priority.")
        if not reason:
            raise HTTPError(400, "Give a reason for emergency priority.")
        db.execute("UPDATE appointments SET priority = 1 WHERE id = ?", (a["id"],))
    elif action == "reinsert_front":
        if a["status"] != "skipped":
            raise HTTPError(409, "Only a skipped patient can be reinserted.")
        if not reason:
            raise HTTPError(400, "Give a reason for this exception.")
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ?, due_at = NULL, position = ? WHERE id = ?",
                   (iso(t), engine.front_position(entries), a["id"]))
    material(user, action, doctor_id, day, a["id"], reason or None)
    return queue_state(doctor_id, day)


@route("POST", "/api/doctor/status", ("doctor", "staff", "admin"))
def doctor_status(user, body):
    """Breaks, delays and availability changes are material events (FR-012)."""
    doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    doctor_or_404(doctor_id)
    status = need(body, "status")
    if status not in ("available", "break", "delayed", "unavailable"):
        raise HTTPError(400, "Status must be available, break, delayed or unavailable.")
    until = None
    if status in ("break", "delayed"):
        minutes = need(body, "minutes", int)
        if not 1 <= minutes <= 240:
            raise HTTPError(400, "Length must be 1 to 240 minutes.")
        until = iso(now() + timedelta(minutes=minutes))
    db.execute("UPDATE doctors SET status = ?, break_until = ? WHERE id = ?", (status, until, doctor_id))
    material(user, "doctor_" + status, doctor_id, today(), None, until and f"until {until[11:16]}")
    return queue_state(doctor_id, today())


# ---------- administration ----------

@route("GET", "/api/admin/overview", ("staff", "admin"))
def overview(user, body):
    """Workload per doctor today (FR-033, FR-038)."""
    p, t, day = policy(), now(), today()
    close = datetime.combine(t.date(), time.fromisoformat(p["opd_end"]))
    out = []
    for d in rows("SELECT id FROM doctors WHERE active = 1 ORDER BY name"):
        q = queue_state(d["id"], day)
        waiting = [e for e in q["entries"] if e["status"] in engine.WAITING]
        current = next((e for e in q["entries"] if e["status"] in ("called", "in_consultation")), None)
        etas = [parse(e["eta"]) for e in q["entries"] if e["eta"] and e["ahead"] is not None]
        clears = max(etas) + timedelta(minutes=q["avg_minutes"]) if etas else None
        # ponytail: fixed congestion thresholds; make them policy values when admins ask
        level = "over capacity" if clears and clears > close else "busy" if len(waiting) >= 8 else "normal"
        out.append({**q["doctor"], "waiting": len(waiting), "current_token": current and current["token"],
                    "current_status": current and current["status"], "avg_minutes": q["avg_minutes"],
                    "clears_at": iso(clears), "congestion": level,
                    "completed": sum(e["status"] == "completed" for e in q["entries"]),
                    "skipped": sum(e["status"] == "skipped" for e in q["entries"]),
                    "emergencies": sum(e["emergency"] for e in q["entries"])})
    exceptions = rows("""SELECT e.at, e.action, e.detail, d.name AS doctor, a.token FROM events e
                         LEFT JOIN doctors d ON d.id = e.doctor_id LEFT JOIN appointments a ON a.id = e.appointment_id
                         WHERE e.day = ? AND e.action IN ('skip','emergency','reinsert_front','reinserted','doctor_delayed',
                         'doctor_unavailable','doctor_break') ORDER BY e.id DESC LIMIT 20""", day)
    failed = row("SELECT COUNT(*) AS n FROM notifications WHERE status = 'failed' AND created_at >= ?", day)["n"]
    return {"doctors": out, "exceptions": exceptions, "failed_alerts": failed, "updated_at": iso(t), "opd_end": p["opd_end"]}


@route("GET", "/api/admin/events", ("admin",))
def events(user, body):
    return {"events": rows("""SELECT e.*, u.name AS actor, d.name AS doctor, a.token FROM events e
                              LEFT JOIN users u ON u.id = e.actor_id LEFT JOIN doctors d ON d.id = e.doctor_id
                              LEFT JOIN appointments a ON a.id = e.appointment_id ORDER BY e.id DESC LIMIT 200""")}


@route("GET", "/api/admin/notifications", ("staff", "admin"))
def notifications(user, body):
    return {"notifications": rows("""SELECT n.id, n.purpose, n.channel, n.status, n.attempts, n.created_at, n.updated_at,
                                     n.detail, u.name AS patient, a.token, d.name AS doctor FROM notifications n
                                     JOIN users u ON u.id = n.patient_id LEFT JOIN appointments a ON a.id = n.appointment_id
                                     LEFT JOIN doctors d ON d.id = a.doctor_id ORDER BY n.id DESC LIMIT 200""")}


@route("GET", "/api/admin/doctors", ("admin",))
def admin_doctors(user, body):
    docs = rows("""SELECT d.*, dep.name AS department FROM doctors d JOIN departments dep ON dep.id = d.department_id
                   ORDER BY d.active DESC, d.name""")
    for d in docs:
        d["leave"] = [r["day"] for r in rows("SELECT day FROM doctor_leave WHERE doctor_id = ? AND day >= ? ORDER BY day",
                                             d["id"], today())]
        d["username"] = (row("SELECT username FROM users WHERE doctor_id = ?", d["id"]) or {}).get("username")
    return {"doctors": docs, "departments": rows("SELECT * FROM departments ORDER BY name")}


def clean_days(value):
    days = "".join(sorted(set(str(value))))
    if not re.fullmatch(r"[0-6]{1,7}", days):
        raise HTTPError(400, "Working days must be weekday numbers 0 (Monday) to 6 (Sunday).")
    return days


@route("POST", "/api/admin/department", ("admin",))
def add_department(user, body):
    name = need(body, "name").strip()
    if row("SELECT 1 FROM departments WHERE name = ?", name):
        raise HTTPError(409, "That department already exists.")
    db.execute("INSERT INTO departments(name) VALUES(?)", (name,))
    log(user, "department_added", detail=name)
    return {"ok": True}


@route("POST", "/api/admin/department/update", ("admin",))
def update_department(user, body):
    dep_id, name = need(body, "department_id", int), need(body, "name").strip()
    if not row("SELECT 1 FROM departments WHERE id = ?", dep_id):
        raise HTTPError(404, "Department not found.")
    if row("SELECT 1 FROM departments WHERE name = ? AND id != ?", name, dep_id):
        raise HTTPError(409, "Another department already has that name.")
    db.execute("UPDATE departments SET name = ? WHERE id = ?", (name, dep_id))
    log(user, "department_renamed", detail=name)
    return {"ok": True}


@route("POST", "/api/admin/doctor", ("admin",))
def add_doctor(user, body):
    """Creates the doctor and their sign-in together (FR-037)."""
    name, dep = need(body, "name").strip(), need(body, "department_id", int)
    username, password = need(body, "username").strip().lower(), need(body, "password")
    avg = float(body.get("avg_minutes") or 10)
    work_days = clean_days(body.get("work_days") or "012345")
    if not row("SELECT 1 FROM departments WHERE id = ?", dep):
        raise HTTPError(404, "Department not found.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken.")
    if len(password) < 8 or not 1 <= avg <= 120:
        raise HTTPError(400, "Password needs 8+ characters and usual consultation time must be 1 to 120 minutes.")
    doc_id = db.execute("INSERT INTO doctors(name, department_id, avg_minutes, work_days) VALUES(?,?,?,?)",
                        (name, dep, avg, work_days)).lastrowid
    db.execute("INSERT INTO users(username, pw, role, name, doctor_id) VALUES(?,?,?,?,?)",
               (username, hash_pw(password), "doctor", name, doc_id))
    log(user, "doctor_added", doc_id, detail=name)
    return {"ok": True, "doctor_id": doc_id}


@route("POST", "/api/admin/doctor/update", ("admin",))
def update_doctor(user, body):
    doc = doctor_or_404(need(body, "doctor_id", int))
    name = (body.get("name") or doc["name"]).strip()
    dep = int(body.get("department_id") or doc["department_id"])
    avg = float(body.get("avg_minutes") or doc["avg_minutes"])
    work_days = clean_days(body.get("work_days") or doc["work_days"])
    active = int(bool(body["active"])) if "active" in body else doc["active"]
    if not row("SELECT 1 FROM departments WHERE id = ?", dep):
        raise HTTPError(404, "Department not found.")
    if not 1 <= avg <= 120:
        raise HTTPError(400, "Usual consultation time must be 1 to 120 minutes.")
    db.execute("UPDATE doctors SET name = ?, department_id = ?, avg_minutes = ?, work_days = ?, active = ? WHERE id = ?",
               (name, dep, avg, work_days, active, doc["id"]))
    db.execute("UPDATE users SET name = ?, active = ? WHERE doctor_id = ?", (name, active, doc["id"]))
    material(user, "doctor_updated", doc["id"], today(), None,
             json.dumps({"name": name, "department_id": dep, "avg_minutes": avg, "work_days": work_days, "active": active}))
    return {"ok": True}


@route("POST", "/api/admin/leave", ("admin",))
def leave(user, body):
    doc = doctor_or_404(need(body, "doctor_id", int))
    day = parse_day(need(body, "day")).isoformat()
    if body.get("remove"):
        db.execute("DELETE FROM doctor_leave WHERE doctor_id = ? AND day = ?", (doc["id"], day))
        material(user, "leave_removed", doc["id"], day, None, day)
        return {"ok": True}
    booked = row("SELECT COUNT(*) AS n FROM appointments WHERE doctor_id = ? AND day = ? AND status IN ('booked','checked_in')",
                 doc["id"], day)["n"]
    db.execute("INSERT OR IGNORE INTO doctor_leave VALUES(?,?)", (doc["id"], day))
    material(user, "leave_added", doc["id"], day, None, day)
    return {"ok": True, "affected_appointments": booked}


@route("GET", "/api/admin/users", ("admin",))
def users(user, body):
    return {"users": rows("""SELECT id, username, role, name, phone, email, active FROM users
                             WHERE role IN ('staff','admin','tester') ORDER BY role, name""")}


@route("POST", "/api/admin/staff", ("admin",))
def add_staff(user, body):
    name, username, password = need(body, "name").strip(), need(body, "username").strip().lower(), need(body, "password")
    role = body.get("role") or "staff"
    if role not in ("staff", "admin", "tester"):
        raise HTTPError(400, "Role must be staff, admin or tester.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken.")
    if len(password) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    db.execute("INSERT INTO users(username, pw, role, name) VALUES(?,?,?,?)", (username, hash_pw(password), role, name))
    log(user, "user_added", detail=f"{username} ({role})")
    return {"ok": True}


@route("POST", "/api/admin/user/update", ("admin",))
def update_user(user, body):
    target = row("SELECT * FROM users WHERE id = ?", need(body, "user_id", int))
    if not target or target["role"] not in ("staff", "admin", "tester"):
        raise HTTPError(404, "Staff account not found.")
    if target["id"] == user["id"]:
        raise HTTPError(409, "You cannot change your own role or access.")
    role = body.get("role") or target["role"]
    active = int(bool(body["active"])) if "active" in body else target["active"]
    if role not in ("staff", "admin", "tester"):
        raise HTTPError(400, "Role must be staff, admin or tester.")
    db.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, active, target["id"]))
    if body.get("password"):
        if len(body["password"]) < 8:
            raise HTTPError(400, "Password must be at least 8 characters.")
        db.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_pw(body["password"]), target["id"]))
    if not active or role != target["role"] or body.get("password"):
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target["id"],))
    log(user, "user_updated", detail=f"{target['username']}: role={role}, active={active}")
    return {"ok": True}


@route("GET", "/api/admin/policy", ("staff", "admin"))
def get_policy(user, body):
    return policy()


@route("POST", "/api/admin/policy", ("admin",))
def set_policy(user, body):
    new = {k: str(body[k]).strip() for k in DEFAULT_POLICY if k in body}
    try:
        for k in ("opd_start", "opd_end"):
            if k in new:
                time.fromisoformat(new[k])
        for k in ("grace_minutes", "alert_minutes", "eta_change_minutes", "notify_retries"):
            if k in new and not 0 <= int(new[k]) <= 180:
                raise ValueError
    except ValueError:
        raise HTTPError(400, "Times must be HH:MM and numbers 0 to 180.")
    merged = {**policy(), **new}
    if time.fromisoformat(merged["opd_start"]) >= time.fromisoformat(merged["opd_end"]):
        raise HTTPError(400, "OPD must open before it closes.")
    for k, v in new.items():
        db.execute("INSERT INTO policy VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
    log(user, "policy_changed", detail=json.dumps(new))
    return policy()


def csv_response(name, header, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(data)
    return {"_raw": buf.getvalue().encode(), "_type": "text/csv; charset=utf-8", "_filename": name}


@route("GET", "/api/admin/export", ("admin",))
def export(user, body):
    """Operational summaries as CSV (FR-040)."""
    kind, day = body.get("kind") or "queue", body.get("day") or today()
    parse_day(day)
    if kind == "queue":
        data = rows("""SELECT d.name, a.token, a.status, a.priority, a.booked_at, a.checked_in_at, a.started_at, a.ended_at,
                       a.skip_reason FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.day = ? ORDER BY d.name, a.token""", day)
        return csv_response(f"queue-{day}.csv", ["doctor", "token", "status", "emergency", "booked_at", "checked_in_at",
                                                 "started_at", "ended_at", "skip_reason"], [list(r.values()) for r in data])
    if kind == "events":
        data = rows("""SELECT e.at, u.name, e.action, d.name, a.token, e.detail FROM events e LEFT JOIN users u ON u.id = e.actor_id
                       LEFT JOIN doctors d ON d.id = e.doctor_id LEFT JOIN appointments a ON a.id = e.appointment_id
                       WHERE substr(e.at, 1, 10) = ? ORDER BY e.id""", day)
        return csv_response(f"audit-{day}.csv", ["at", "actor", "action", "doctor", "token", "detail"], [list(r.values()) for r in data])
    if kind == "notifications":
        data = rows("""SELECT created_at, purpose, channel, status, attempts, detail FROM notifications
                       WHERE substr(created_at, 1, 10) = ? ORDER BY id""", day)
        return csv_response(f"notifications-{day}.csv", ["created_at", "purpose", "channel", "status", "attempts", "detail"],
                            [list(r.values()) for r in data])
    raise HTTPError(400, "Export kind must be queue, events or notifications.")


# ---------- simulation (test and development roles only, SRS 4.1) ----------

RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[a-z_-]+-[0-9]+seeds")


@route("POST", "/api/sim/run", ("tester",))
def sim_run(user, body):
    import simulate
    scenarios = body.get("scenarios") or list(simulate.SCENARIOS)
    seeds = need(body, "seeds", int)
    if not isinstance(scenarios, list) or any(s not in simulate.SCENARIOS for s in scenarios):
        raise HTTPError(400, f"Scenarios must be from: {', '.join(simulate.SCENARIOS)}.")
    if not 1 <= seeds <= 1000:
        raise HTTPError(400, "Seeds must be 1 to 1000.")
    if any(j["status"] == "running" for j in sim_jobs.values()):
        raise HTTPError(409, "A simulation is already running. Wait for it to finish.")
    job = secrets.token_hex(4)
    sim_jobs[job] = {"id": job, "status": "running", "scenarios": scenarios, "seeds": seeds, "done": 0,
                     "total": seeds * len(scenarios), "started_at": iso(now())}

    def work():
        try:
            def progress(*_):
                sim_jobs[job]["done"] += 1
            report = simulate.run_experiment(scenarios, seeds, out_dir=SIM_DIR, progress=progress)
            sim_jobs[job].update(status="finished", run_id=report["run_id"])
        except Exception as e:  # report the failure to the tester instead of dying silently
            traceback.print_exc()
            sim_jobs[job].update(status="failed", error=str(e))

    threading.Thread(target=work, daemon=True).start()
    log(user, "simulation_started", detail=f"{','.join(scenarios)} x {seeds} seeds")
    return sim_jobs[job]


@route("GET", "/api/sim/runs", ("tester", "admin"))
def sim_runs(user, body):
    runs = []
    for f in sorted(SIM_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        brief = {name: {m: res["summary"][m] for m in ("eta_mae", "eta_within_15", "wait_after_checkin")}
                 for name, res in r["results"].items()}
        runs.append({k: r[k] for k in ("run_id", "label", "created_at", "software_version", "scenarios",
                                       "runs_per_scenario", "runtime_seconds")} | {"summary": brief})
    import simulate
    return {"runs": runs, "jobs": list(sim_jobs.values()),
            "scenarios": {k: v["description"] for k, v in simulate.SCENARIOS.items()}}


@route("GET", "/api/sim/report", ("tester", "admin"))
def sim_report(user, body):
    """Download a saved report (FR-040). The id is checked so no other file can be read."""
    run_id, fmt = need(body, "run_id"), body.get("format") or "md"
    if not RUN_ID.fullmatch(run_id) or fmt not in ("md", "json"):
        raise HTTPError(400, "Unknown report.")
    path = SIM_DIR / f"{run_id}.{fmt}"
    if not path.exists():
        raise HTTPError(404, "Report not found.")
    return {"_raw": path.read_bytes(), "_type": "text/markdown; charset=utf-8" if fmt == "md" else "application/json",
            "_filename": path.name}


# ---------- background work: arrival-alert ticks and notification delivery ----------

def dispatch_once():
    """Send pending alerts outside the request lock, so a slow or failing provider
    never blocks booking or queue progress (FR-020, NFR-007)."""
    with lock:
        pending = rows("SELECT * FROM notifications WHERE status = 'pending' AND next_try <= ? ORDER BY id LIMIT 20", iso(now()))
        retries = int(policy()["notify_retries"])
    for n in pending:
        provider = notify.provider_for(n["channel"])
        try:
            status, detail = provider.send(n["recipient"], n["subject"], n["body"]), f"via {provider.name}"
        except Exception as e:
            status, detail = None, f"via {provider.name}: {type(e).__name__}: {e}"[:300]
        attempts, t = n["attempts"] + 1, now()
        if status is None:
            status = "pending" if attempts <= retries else "failed"
        with lock, db:
            db.execute("UPDATE notifications SET status = ?, attempts = ?, updated_at = ?, next_try = ?, detail = ? WHERE id = ?",
                       (status, attempts, iso(t), iso(t + timedelta(minutes=attempts)), detail, n["id"]))


def tick_once():
    """Time passes without events, so arrival alerts are checked on a timer too (FR-017)."""
    with lock, db:
        for q in rows("""SELECT DISTINCT doctor_id FROM appointments
                         WHERE day = ? AND status IN ('booked','checked_in','called','in_consultation')""", today()):
            after_change(q["doctor_id"], today(), "tick")


def background():
    last_tick = 0.0
    while True:
        try:
            if wallclock.monotonic() - last_tick >= TICK_SECONDS:
                tick_once()
                last_tick = wallclock.monotonic()
            dispatch_once()
        except Exception:
            traceback.print_exc()
        wallclock.sleep(DISPATCH_SECONDS)


# ---------- HTTP plumbing ----------

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                               "frame-ancestors 'none'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "SmartOPD"
    sys_version = ""

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        url = urlparse(self.path)
        if method == "GET" and url.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        found = ROUTES.get((method, url.path))
        if not found:
            return self.send_json(404, {"error": "Not found."})
        fn, roles = found
        try:
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise HTTPError(413, "Request is too large.")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise HTTPError(400, "Expected a JSON object.")
            else:
                body = {k: v[0] for k, v in parse_qs(url.query).items()}
            with lock:
                user = self.current_user()
                if roles is not None:
                    if not user:
                        raise HTTPError(401, "Please sign in.")
                    if user["role"] not in roles:
                        raise HTTPError(403, "You do not have permission for this action.")
                with db:  # commit before replying, roll back on any error (NFR-006)
                    result = fn(user, body)
            if "_raw" in result:
                return self.send(200, result["_raw"], result["_type"],
                                 {"Content-Disposition": f'attachment; filename="{result["_filename"]}"'})
            cookie = result.pop("_cookie", None)
            self.send_json(200, result, cookie)
        except HTTPError as e:
            self.send_json(e.status, {"error": e.message})
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Request body is not valid JSON."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "That conflicts with existing data. Refresh and try again."})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on the server. Nothing was saved."})

    def current_user(self):
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        token = jar["sid"].value if "sid" in jar else None
        if not token:
            return None
        s = row("""SELECT u.*, s.created FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND u.active = 1""", token_hash(token))
        if not s or now() - parse(s["created"]) > timedelta(hours=SESSION_HOURS):
            return None
        return s

    def send_json(self, status, data, cookie=None):
        extra = {}
        if cookie is not None:
            extra["Set-Cookie"] = (f"sid={cookie}; HttpOnly; SameSite=Strict; Path=/"
                                   + ("; Secure" if TLS_CERT else "") + ("" if cookie else "; Max-Age=0"))
        self.send(status, json.dumps(data).encode(), "application/json", extra)

    def send(self, status, payload, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


def init_db(demo):
    db.executescript(SCHEMA)
    if row("SELECT 1 FROM users LIMIT 1"):
        return
    with db:
        if not demo:
            password = os.environ.get("OPD_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            db.execute("INSERT INTO users(username, pw, role, name) VALUES(?,?,?,?)",
                       ("admin", hash_pw(password), "admin", "OPD Administrator"))
            shown = "from OPD_ADMIN_PASSWORD" if os.environ.get("OPD_ADMIN_PASSWORD") else password
            print(f"Created the first account: admin / {shown}. Sign in and change it, then add departments and doctors.")
            return
        for name in ("General Medicine", "Paediatrics", "Orthopaedics"):
            db.execute("INSERT INTO departments(name) VALUES(?)", (name,))
        for name, dep, avg, username in [("Dr. Rao", 1, 8, "dr.rao"), ("Dr. Iyer", 1, 12, "dr.iyer"),
                                         ("Dr. Khan", 2, 10, "dr.khan"), ("Dr. Sen", 3, 15, "dr.sen")]:
            doc_id = db.execute("INSERT INTO doctors(name, department_id, avg_minutes) VALUES(?,?,?)", (name, dep, avg)).lastrowid
            db.execute("INSERT INTO users(username, pw, role, name, doctor_id) VALUES(?,?,?,?,?)",
                       (username, hash_pw("doctor123"), "doctor", name, doc_id))
        for username, pw, role, name in [("admin", "admin123", "admin", "OPD Admin"), ("staff", "staff123", "staff", "Front Desk"),
                                         ("tester", "tester123", "tester", "QA Tester")]:
            db.execute("INSERT INTO users(username, pw, role, name) VALUES(?,?,?,?)", (username, hash_pw(pw), role, name))
        db.execute("INSERT INTO users(username, pw, role, name, phone, channel) VALUES(?,?,?,?,?,?)",
                   ("patient", hash_pw("patient123"), "patient", "Demo Patient", "+91 98765 43210", "sms"))
    print("Demo data loaded. Accounts: admin/admin123, staff/staff123, tester/tester123, patient/patient123, "
          "dr.rao, dr.iyer, dr.khan, dr.sen / doctor123")


def main():
    global DEMO
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    DEMO = "--demo" in sys.argv or os.environ.get("OPD_DEMO") == "1"
    host = os.environ.get("OPD_HOST", "127.0.0.1")
    port = int(args[0]) if args else int(os.environ.get("OPD_PORT", "8000"))
    init_db(DEMO)
    threading.Thread(target=background, daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    scheme = "http"
    if TLS_CERT:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print(f"Smart OPD {engine.VERSION} running at {scheme}://{host}:{port}{' (demo mode)' if DEMO else ''}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
