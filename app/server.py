"""Smart OPD web server: JSON API, SQLite storage, notification worker and the single-page UI.

Run:  python3 app/server.py --demo     (local demo with sample doctors and accounts)
      python3 app/server.py            (production: creates only an admin account)
Settings come from environment variables; see README.md.
"""
import csv
import functools
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
BACKUP_DIR = Path(os.environ.get("OPD_BACKUP_DIR", str(Path(DB_PATH).parent / "backups")))
BACKUP_KEEP = int(os.environ.get("OPD_BACKUP_KEEP", "14"))  # daily backups kept; pre-upgrade backups are never pruned
TLS_CERT, TLS_KEY = os.environ.get("OPD_TLS_CERT"), os.environ.get("OPD_TLS_KEY")
TICK_SECONDS = float(os.environ.get("OPD_TICK_SECONDS", "30"))       # arrival-alert check interval
DISPATCH_SECONDS = float(os.environ.get("OPD_DISPATCH_SECONDS", "5"))  # notification send interval
SESSION_HOURS = 12
MAX_BODY = 1_000_000
MAX_FIELD = 200  # names, usernames, passwords and other single-line fields
LOCKOUT_FAILS, LOCKOUT_MINUTES = 5, 5
ROLES = ("patient", "doctor", "staff", "admin", "tester")

# priority: 0 normal, 1 a staff-assigned category (priority_label names it), 2 emergency
APPOINTMENTS = """CREATE TABLE IF NOT EXISTS {name}(
  id INTEGER PRIMARY KEY,
  patient_id INTEGER NOT NULL REFERENCES users(id),
  doctor_id INTEGER NOT NULL REFERENCES doctors(id),
  day TEXT NOT NULL, token INTEGER NOT NULL, position REAL NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0, priority_label TEXT,
  status TEXT NOT NULL DEFAULT 'booked'
    CHECK(status IN ('booked','checked_in','called','in_consultation','completed','skipped','cancelled')),
  booked_at TEXT NOT NULL, checked_in_at TEXT, due_at TEXT, started_at TEXT, ended_at TEXT,
  skip_reason TEXT, promised_at TEXT, arrival_alerted INTEGER NOT NULL DEFAULT 0, cancelled_at TEXT,
  UNIQUE(patient_id, doctor_id, day), UNIQUE(doctor_id, day, token))"""

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
  active INTEGER NOT NULL DEFAULT 1,
  status_day TEXT, max_patients INTEGER, opd_start TEXT, opd_end TEXT);
CREATE TABLE IF NOT EXISTS doctor_leave(
  doctor_id INTEGER NOT NULL REFERENCES doctors(id), day TEXT NOT NULL, PRIMARY KEY(doctor_id, day));
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('patient','doctor','staff','admin','tester')),
  name TEXT NOT NULL, phone TEXT, email TEXT,
  channel TEXT NOT NULL DEFAULT 'none' CHECK(channel IN ('sms','email','none')),
  doctor_id INTEGER REFERENCES doctors(id), active INTEGER NOT NULL DEFAULT 1,
  guardian_id INTEGER REFERENCES users(id), lang TEXT NOT NULL DEFAULT 'en', alert_lead INTEGER,
  reset_hash TEXT, reset_expires TEXT, reset_tries INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy(key TEXT PRIMARY KEY, value TEXT NOT NULL);
""" + APPOINTMENTS.format(name="appointments") + """;
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
                  "eta_change_minutes": "15", "notify_retries": "2",
                  "checkin_minutes": "60",          # patients may self check-in this long before their ETA
                  "require_checkin_code": "0",      # 1: self check-in needs the code shown on the reception display
                  "booking_days_ahead": "14", "max_active_bookings": "3",
                  "block_after_close": "1",         # 1: patients cannot book a queue projected to run past closing
                  "priority_categories": "Senior citizen, Pregnant, Disability",
                  "retention_days": "0"}            # 0 keeps everything; otherwise older days are purged nightly
NUMERIC_POLICY = {"grace_minutes": (0, 180), "alert_minutes": (0, 180), "eta_change_minutes": (0, 180),
                  "notify_retries": (0, 180), "checkin_minutes": (5, 720), "require_checkin_code": (0, 1),
                  "booking_days_ahead": (0, 365), "max_active_bookings": (1, 50), "block_after_close": (0, 1),
                  "retention_days": (0, 3650)}
LANGS = ("en", "hi")

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
    if value is None or not str(value).strip():
        raise HTTPError(400, f"Missing field: {key}.")
    if len(str(value)) > MAX_FIELD:
        raise HTTPError(400, f"{key} is too long (at most {MAX_FIELD} characters).")
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise HTTPError(400, f"Invalid value for {key}.")


def opt(body, key, cast, default):
    """Like need(), but an absent or empty field gives the default."""
    return default if body.get(key) in (None, "") else need(body, key, cast)


def text(body, key):
    """Optional free-text field as a stripped string (non-string JSON values are coerced, not a crash)."""
    return str(opt(body, key, str, "")).strip()


def valid_username(username):
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise HTTPError(400, "Usernames are 3 to 40 letters, digits, dots, dashes or underscores.")
    return username


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
    """Admin-set rules. Keys starting with _ are server secrets and never leave this module."""
    return {**DEFAULT_POLICY, **{r["key"]: r["value"] for r in rows("SELECT * FROM policy WHERE key NOT LIKE '\\_%' ESCAPE '\\'")}}


def secret_code(purpose, length):
    """A code derived from the server secret: the daily check-in code and the display-screen key."""
    secret = row("SELECT value FROM policy WHERE key = '_secret'")["value"]
    digest = hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).hexdigest()
    return f"{int(digest, 16) % 10 ** length:0{length}d}" if purpose.startswith("checkin:") else digest[:length]


def checkin_code(day=None):
    return secret_code(f"checkin:{day or today()}", 6)


def display_key():
    return secret_code("display", 20)


def priority_categories():
    return [c.strip() for c in policy()["priority_categories"].split(",") if c.strip()]


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
    """A break or delay that has run out counts as available again, and "unavailable"
    lasts only for the day it was set: each OPD day starts with the doctor available."""
    if doc["status"] in ("break", "delayed") and (not doc["break_until"] or parse(doc["break_until"]) <= t):
        return "available"
    if doc["status"] == "unavailable" and doc["status_day"] != t.date().isoformat():
        return "available"
    return doc["status"]


def holds_opd(doc, d):
    """Whether the doctor runs OPD on that date: active, a working weekday, not on leave."""
    return (doc["active"] and str(d.weekday()) in doc["work_days"]
            and not row("SELECT 1 FROM doctor_leave WHERE doctor_id = ? AND day = ?", doc["id"], d.isoformat()))


def hours(doc, d, p=None):
    """The doctor's OPD session on date d as (start, end) datetimes: their own hours, else the hospital's."""
    p = p or policy()
    return (datetime.combine(d, time.fromisoformat(doc["opd_start"] or p["opd_start"])),
            datetime.combine(d, time.fromisoformat(doc["opd_end"] or p["opd_end"])))


def contact(patient_id):
    """Who receives a patient's alerts and in which language: a family member's guardian, else the patient."""
    u = row("SELECT * FROM users WHERE id = ?", patient_id)
    return row("SELECT * FROM users WHERE id = ?", u["guardian_id"]) if u["guardian_id"] else u


def own_patients(user):
    """Patient ids a patient account may act for: itself and its active family members."""
    return [r["id"] for r in rows("SELECT id FROM users WHERE id = ? OR (guardian_id = ? AND active = 1)", user["id"], user["id"])]


def own_appointment(user, appt_id):
    """An appointment the user may act on; patients only see their own and their family's (NFR-004)."""
    a = row("SELECT * FROM appointments WHERE id = ?", appt_id)
    if not a or (user["role"] == "patient" and a["patient_id"] not in own_patients(user)):
        raise HTTPError(404, "Appointment not found.")
    return a


@functools.lru_cache(maxsize=256)
def learned_minutes(doctor_id, day, default):
    """(minutes, consultations) learned from the doctor's last 28 days before `day`. Cached per day,
    because earlier days do not change; the cache key includes the default so an admin edit applies at once."""
    since = (date.fromisoformat(day) - timedelta(days=28)).isoformat()
    done = rows("""SELECT started_at, ended_at FROM appointments WHERE doctor_id = ? AND day >= ? AND day < ?
                   AND status = 'completed' AND started_at IS NOT NULL AND ended_at IS NOT NULL""", doctor_id, since, day)
    durations = [(parse(r["ended_at"]) - parse(r["started_at"])).total_seconds() / 60 for r in done]
    return engine.prior_minutes(durations, default), len([x for x in durations if x >= 1])


changes = threading.Condition()  # live updates (/api/stream): bumped after every committed change
change_seq = 0


def bump():
    global change_seq
    with changes:
        change_seq += 1
        changes.notify_all()


def backup(label="daily"):
    """Copy the live database with SQLite's online backup. Daily copies beyond BACKUP_KEEP are pruned."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"opd-{now():%Y%m%d-%H%M%S}-{label}.db"
    dest = sqlite3.connect(path)
    with dest:
        db.backup(dest)
    dest.close()
    for old in sorted(BACKUP_DIR.glob("opd-*-daily.db"))[:-BACKUP_KEEP]:
        old.unlink()
    return path


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
    prior, _ = learned_minutes(doc["id"], day, doc["avg_minutes"])
    avg = engine.expected_minutes([(parse(e["ended_at"]) - e["started_at"]).total_seconds() / 60 for e in done], prior)
    status = effective_status(doc, t)
    d = date.fromisoformat(day)
    # the doctor's status describes now, so it only affects today's queue; a past day has no honest ETA
    available = (status != "unavailable" or d != t.date()) and d >= t.date() and holds_opd(doc, d)
    opd_start, opd_end = hours(doc, d, p)
    etas = engine.compute_etas(entries, t, avg, opd_start, available=available,
                               break_until=parse(doc["break_until"]) if status in ("break", "delayed") else None)
    rank = {e["id"]: i for i, e in enumerate(engine.order(entries))}
    grace = int(p["grace_minutes"])
    out = []
    for e in sorted(entries, key=lambda e: (e["id"] not in rank, rank.get(e["id"], 0), e["token"])):
        out.append({
            "id": e["id"], "token": e["token"], "patient_name": e["patient_name"], "status": e["status"],
            "emergency": e["priority"] >= 2, "priority": e["priority_label"],
            "checked_in_at": e["checked_in_at"], "skip_reason": e["skip_reason"],
            "turn_missed": e["due_at"] is not None and e["status"] == "booked",
            "can_skip": engine.can_skip(e, t, grace),
            "ahead": rank.get(e["id"]), "eta": iso(etas.get(e["id"])),
        })
    return {"doctor": {"id": doc["id"], "name": doc["name"], "department": doc["department"], "status": status,
                       "break_until": doc["break_until"] if status in ("break", "delayed") else None,
                       "holds_opd": bool(holds_opd(doc, d)), "department_id": doc["department_id"],
                       "opd_start": opd_start.strftime("%H:%M"), "opd_end": opd_end.strftime("%H:%M")},
            "day": day, "avg_minutes": round(avg, 1), "version": queue_version(doctor_id, day),
            "updated_at": iso(t), "entries": out}


MESSAGES = {
    "en": {
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
        "doctor_leave": ("Doctor on leave",
                         "{doctor} will not hold OPD on {day}. Token {token} is still listed: please cancel it and book "
                         "another date or doctor in the app."),
        "transferred": ("Your appointment has moved",
                        "Your appointment is now with {doctor}, token {token}. See the app for your expected time."),
        "cancelled": ("Appointment cancelled", "Token {token} with {doctor} on {day} has been cancelled by the OPD desk."),
        "reset_code": ("Password reset code", "Your Smart OPD password reset code is {code}. It expires in 15 minutes."),
    },
    # ponytail: Hindi only for now; add a language by adding a dict here and its name in index.html LANGS
    "hi": {
        "arrival": ("आपकी बारी नज़दीक है",
                    "{doctor} के साथ टोकन {token}: अनुमानित समय लगभग {eta}। कृपया OPD पहुँचें और चेक-इन करें, अगर अभी तक "
                    "नहीं किया है। यह समय अनुमान है और बदल सकता है।"),
        "eta_change": ("आपका अनुमानित समय बदल गया है",
                       "{doctor} के साथ टोकन {token}: अब लगभग {eta} अनुमानित है। यह समय अनुमान है और बदल सकता है।"),
        "called": ("कृपया अभी अंदर जाएँ", "टोकन {token}: {doctor} आपको अभी बुला रहे हैं।"),
        "skipped": ("आपकी बारी निकल गई",
                    "{doctor} के साथ टोकन {token} छोड़ दिया गया क्योंकि आपने चेक-इन नहीं किया था। पहुँचने पर चेक-इन करें, "
                    "आप फिर से कतार में जुड़ जाएँगे।"),
        "doctor_unavailable": ("डॉक्टर उपलब्ध नहीं",
                               "{doctor} अभी उपलब्ध नहीं हैं। उनके लौटने पर आपका अनुमानित समय अपडेट होगा।"),
        "doctor_leave": ("डॉक्टर छुट्टी पर",
                         "{doctor} {day} को OPD नहीं करेंगे। टोकन {token} अभी भी सूची में है: कृपया इसे रद्द करें और ऐप में "
                         "दूसरी तारीख या डॉक्टर चुनें।"),
        "transferred": ("आपकी अपॉइंटमेंट बदली गई",
                        "आपकी अपॉइंटमेंट अब {doctor} के साथ है, टोकन {token}। अनुमानित समय ऐप में देखें।"),
        "cancelled": ("अपॉइंटमेंट रद्द", "{day} को {doctor} के साथ टोकन {token} OPD डेस्क द्वारा रद्द कर दिया गया है।"),
        "reset_code": ("पासवर्ड रीसेट कोड", "आपका Smart OPD पासवर्ड रीसेट कोड {code} है। यह 15 मिनट में समाप्त हो जाएगा।"),
    },
}


def notify_patient(patient_id, appt_id, purpose, key, **fields):
    """Queue an alert for the worker, in the recipient's language. The unique event key stops
    duplicates (FR-021). Patients without a usable channel still see everything in the app (FR-017)."""
    c = contact(patient_id)
    recipient = {"sms": c["phone"], "email": c["email"]}.get(c["channel"])
    if not recipient:
        return
    subject, body = MESSAGES.get(c["lang"], MESSAGES["en"])[purpose]
    t = iso(now())
    db.execute("""INSERT OR IGNORE INTO notifications(appointment_id, patient_id, purpose, channel, recipient, subject, body,
                  created_at, updated_at, next_try, event_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (appt_id, patient_id, purpose, c["channel"], recipient, subject, body.format(**fields), t, t, t, key))


def enqueue(appt_id, purpose, key, eta=None):
    a = row("SELECT a.*, d.name AS doctor FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.id = ?", appt_id)
    notify_patient(a["patient_id"], appt_id, purpose, key, token=a["token"], doctor=a["doctor"], day=a["day"],
                   eta=eta.strftime("%H:%M") if eta else "")


def alert_minutes(patient_id, p):
    """How long before their ETA a patient wants the arrival alert: their own setting, else the policy."""
    return contact(patient_id)["alert_lead"] or int(p["alert_minutes"])


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
        a = row("SELECT patient_id, promised_at, arrival_alerted FROM appointments WHERE id = ?", e["id"])
        told = parse(a["promised_at"])
        to_eta = (eta - t).total_seconds() / 60 if eta else None
        shift = abs((eta - told).total_seconds()) / 60 if eta and told else None
        for purpose in notify.alert_purposes(to_eta, shift, a["arrival_alerted"], alert_minutes(a["patient_id"], p),
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
    username, password = valid_username(need(body, "username").strip().lower()), need(body, "password")
    name = need(body, "name").strip()
    phone, email = text(body, "phone"), text(body, "email")
    channel = body.get("channel") or ("sms" if phone else "email" if email else "none")
    lang, lead = prefs(body)
    if len(password) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    valid_contact(phone, email, channel)
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken. Choose another.")
    db.execute("INSERT INTO users(username, pw, role, name, phone, email, channel, lang, alert_lead) VALUES(?,?,?,?,?,?,?,?,?)",
               (username, hash_pw(password), "patient", name, phone or None, email or None, channel, lang, lead))
    return login(None, body)


def prefs(body):
    """Alert language and the patient's own arrival-alert lead time in minutes (None = hospital default)."""
    lang = body.get("lang") or "en"
    if lang not in LANGS:
        raise HTTPError(400, f"Language must be one of: {', '.join(LANGS)}.")
    lead = opt(body, "alert_lead", int, None)
    if lead is not None and not 5 <= lead <= 180:
        raise HTTPError(400, "Alert time must be 5 to 180 minutes before your turn.")
    return lang, lead


def unusable_password():
    """Accounts nobody signs in to (family members, walk-ins) get a random password until one is set for them."""
    return hash_pw(secrets.token_urlsafe(24))


def start_session(u):
    token, t = secrets.token_urlsafe(32), now()
    db.execute("DELETE FROM sessions WHERE created < ?", (iso(t - timedelta(hours=SESSION_HOURS)),))
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), u["id"], iso(t)))
    return {"_cookie": token, **public_user(u)}


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
    return start_session(u)


@route("POST", "/api/logout", ROLES)
def logout(user, body):
    """Ends this session only, so one front-desk PC signing out does not sign out a shared account elsewhere."""
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (user["token_hash"],))
    return {"_cookie": "", "ok": True}


@route("POST", "/api/password", ROLES)
def change_password(user, body):
    """Every account can change its own password; other sessions of the account are signed out."""
    current, new = need(body, "current"), need(body, "new")
    if not check_pw(current, user["pw"]):
        raise HTTPError(403, "Your current password is wrong.")
    if len(new) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    db.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_pw(new), user["id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user["id"], user["token_hash"]))
    log(user, "password_changed")
    return {"ok": True}


@route("POST", "/api/password/forgot")
def forgot_password(user, body):
    """Send a one-time reset code through the account's alert channel. The reply is the same
    whether or not the account exists, so it cannot be used to discover usernames."""
    u = row("SELECT * FROM users WHERE username = ? AND active = 1", need(body, "username").strip().lower())
    t = now()
    recent = u and u["reset_expires"] and parse(u["reset_expires"]) - timedelta(minutes=14) > t  # at most one code a minute
    if u and not recent and {"sms": u["phone"], "email": u["email"]}.get(u["channel"]):
        code = f"{secrets.randbelow(10 ** 6):06d}"
        db.execute("UPDATE users SET reset_hash = ?, reset_expires = ?, reset_tries = 0 WHERE id = ?",
                   (token_hash(f"{u['id']}:{code}"), iso(t + timedelta(minutes=15)), u["id"]))
        notify_patient(u["id"], None, "reset_code", f"reset:{u['id']}:{iso(t)}", code=code)
    return {"ok": True, "message": "If that account has SMS or email alerts set up, a code is on its way. It works for 15 minutes."}


@route("POST", "/api/password/reset")
def reset_password(user, body):
    u = row("SELECT * FROM users WHERE username = ? AND active = 1", need(body, "username").strip().lower())
    code, new = need(body, "code").strip(), need(body, "new")
    if not u or not u["reset_hash"] or parse(u["reset_expires"]) < now() or u["reset_tries"] >= 5:
        raise HTTPError(400, "That code is not valid any more. Ask for a new one.")
    if not hmac.compare_digest(token_hash(f"{u['id']}:{code}"), u["reset_hash"]):
        db.execute("UPDATE users SET reset_tries = reset_tries + 1 WHERE id = ?", (u["id"],))
        db.commit()  # count the failed try even though this request fails
        raise HTTPError(400, "That code is wrong. Check the latest message and try again.")
    if len(new) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    db.execute("UPDATE users SET pw = ?, reset_hash = NULL, reset_expires = NULL, reset_tries = 0 WHERE id = ?",
               (hash_pw(new), u["id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
    log(u, "password_reset_by_code")
    return start_session(u)


def public_user(u):
    out = {k: u[k] for k in ("id", "username", "role", "name", "doctor_id", "phone", "email", "channel", "lang", "alert_lead")}
    if u["role"] == "patient":
        out["dependants"] = rows("SELECT id, name FROM users WHERE guardian_id = ? AND active = 1 ORDER BY name", u["id"])
    return out


@route("GET", "/api/me", ROLES)
def me(user, body):
    return public_user(user)


@route("POST", "/api/profile", ("patient",))
def profile(user, body):
    """Patients keep their contact details, alert channel, language and alert timing up to date (FR-003)."""
    phone, email = text(body, "phone"), text(body, "email")
    channel = body.get("channel") or "none"
    lang, lead = prefs(body)
    valid_contact(phone, email, channel)
    db.execute("UPDATE users SET phone = ?, email = ?, channel = ?, lang = ?, alert_lead = ? WHERE id = ?",
               (phone or None, email or None, channel, lang, lead, user["id"]))
    return public_user(row("SELECT * FROM users WHERE id = ?", user["id"]))


@route("POST", "/api/dependants", ("patient",))
def add_dependant(user, body):
    """Family members (a child, an elderly parent) book under this account; alerts go to this account."""
    name = need(body, "name").strip()
    if len(own_patients(user)) > 10:
        raise HTTPError(409, "An account can have at most 10 family members.")
    db.execute("INSERT INTO users(username, pw, role, name, guardian_id, channel) VALUES(?,?,?,?,?,?)",
               (f"family-{user['id']}-{secrets.token_hex(4)}", unusable_password(), "patient", name, user["id"], "none"))
    log(user, "family_member_added", detail=name)
    return public_user(row("SELECT * FROM users WHERE id = ?", user["id"]))


@route("POST", "/api/dependants/remove", ("patient",))
def remove_dependant(user, body):
    pid = need(body, "patient_id", int)
    if pid == user["id"] or pid not in own_patients(user):
        raise HTTPError(404, "Family member not found.")
    if row("SELECT 1 FROM appointments WHERE patient_id = ? AND day >= ? AND status IN ('booked','checked_in','called','in_consultation')",
           pid, today()):
        raise HTTPError(409, "Cancel their upcoming appointments first.")
    db.execute("UPDATE users SET active = 0 WHERE id = ?", (pid,))  # kept, not deleted: their past visits stay linked
    log(user, "family_member_removed", detail=str(pid))
    return public_user(row("SELECT * FROM users WHERE id = ?", user["id"]))


@route("POST", "/api/delete-account", ("patient",))
def delete_account(user, body):
    """Patient-requested erasure: upcoming visits are cancelled and personal details are removed from this
    account and its family members. Visit records stay, anonymised, so queue history and audit stay consistent."""
    if not check_pw(need(body, "password"), user["pw"]):
        raise HTTPError(403, "Your password is wrong.")
    for pid in own_patients(user):
        for a in rows("SELECT id FROM appointments WHERE patient_id = ? AND day >= ? AND status IN ('booked','checked_in')",
                      pid, today()):
            cancel_appointment(user, own_appointment(user, a["id"]), "account deleted", notify_patient_too=False)
    ids = own_patients(user) + [r["id"] for r in rows("SELECT id FROM users WHERE guardian_id = ?", user["id"])]
    for pid in set(ids):
        db.execute("""UPDATE users SET name = 'Deleted patient', username = ?, pw = ?, phone = NULL, email = NULL, channel = 'none',
                      active = 0, alert_lead = NULL, reset_hash = NULL WHERE id = ?""", (f"deleted-{pid}", unusable_password(), pid))
        db.execute("UPDATE notifications SET recipient = '', body = '' WHERE patient_id = ?", (pid,))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (pid,))
    log(None, "account_deleted", detail=f"patient {user['id']}")
    return {"_cookie": "", "ok": True}


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
            full = open_ and capacity_problem(doctor_or_404(doc["id"]), day, q)
            dep["doctors"].append({**q["doctor"], "waiting": len(waiting), "clears_at": clears,
                                   "bookable": bool(open_ and not full), "full": bool(full)})
    return {"departments": deps, "day": day}


def capacity_problem(doc, day, q=None):
    """Why one more patient would not fit the doctor's day, or None: the admin's daily cap, or (when
    the block_after_close policy is on) a queue already projected to run past the end of OPD."""
    q = q or queue_state(doc["id"], day)
    booked = sum(e["status"] != "cancelled" for e in q["entries"])
    if doc["max_patients"] and booked >= doc["max_patients"]:
        return f"{doc['name']} is fully booked on {day} ({doc['max_patients']} patients)."
    etas = [parse(e["eta"]) for e in q["entries"] if e["ahead"] is not None and e["eta"]]
    if policy()["block_after_close"] == "1" and etas:
        _, close = hours(doc, date.fromisoformat(day))
        if max(etas) + timedelta(minutes=q["avg_minutes"]) >= close:
            return f"{doc['name']}'s queue on {day} already runs to closing time ({close:%H:%M}). Choose another date or doctor."
    return None


def create_booking(actor, patient_id, doctor_id, day, by_staff=False, checked_in=False):
    """The one booking path for patients, walk-ins and reschedules (decision tree DT-1, decision table 1).
    Patient bookings also obey the booking window, the per-patient limit and doctor capacity; staff
    bookings at the desk go through with a warning instead, because the patient is standing there."""
    d = parse_day(day)
    t, p = now(), policy()
    doc = doctor_or_404(doctor_id)
    if d < t.date():
        raise HTTPError(400, "Choose today or a later date.")
    if not holds_opd(doc, d):
        raise HTTPError(409, f"{doc['name']} does not hold OPD on {day}. Choose another date or doctor.")
    if d == t.date() and effective_status(doc, t) == "unavailable":
        raise HTTPError(409, f"{doc['name']} is not available today. Choose another doctor or date.")
    _, close = hours(doc, d, p)
    if d == t.date() and t >= close:
        raise HTTPError(409, f"OPD has closed for today (closes {close:%H:%M}). Choose another date.")
    existing = row("SELECT id, status FROM appointments WHERE patient_id = ? AND doctor_id = ? AND day = ?", patient_id, doctor_id, day)
    if existing and existing["status"] != "cancelled":  # FR-009: a repeat submission returns the same booking
        return {"existing": True, **appointment_view(existing["id"])}
    warning = None
    if by_staff:
        warning = capacity_problem(doc, day)
    else:
        if d > t.date() + timedelta(days=int(p["booking_days_ahead"])):
            raise HTTPError(400, f"You can book up to {p['booking_days_ahead']} days ahead.")
        active = row("""SELECT COUNT(*) AS n FROM appointments WHERE patient_id = ? AND day >= ?
                        AND status IN ('booked','checked_in','called','in_consultation')""", patient_id, today())["n"]
        if active >= int(p["max_active_bookings"]):
            raise HTTPError(409, f"There are already {active} upcoming appointments for this patient. Cancel one to book another.")
        problem = capacity_problem(doc, day)
        if problem:
            raise HTTPError(409, problem)
    entries = queue_entries(doctor_id, day)
    token = max((e["token"] for e in entries), default=0) + 1
    status, checked = ("checked_in", iso(t)) if checked_in else ("booked", None)
    if existing:  # a cancelled booking with this doctor and day is reused: the unique key allows one row
        appt_id = existing["id"]
        db.execute("""UPDATE appointments SET token = ?, position = ?, status = ?, booked_at = ?, checked_in_at = ?, priority = 0,
                      priority_label = NULL, due_at = NULL, started_at = NULL, ended_at = NULL, skip_reason = NULL,
                      promised_at = NULL, arrival_alerted = 0, cancelled_at = NULL WHERE id = ?""",
                   (token, engine.end_position(entries), status, iso(t), checked, appt_id))
    else:
        appt_id = db.execute("""INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at, status, checked_in_at)
                                VALUES(?,?,?,?,?,?,?,?)""",
                             (patient_id, doctor_id, day, token, engine.end_position(entries), iso(t), status, checked)).lastrowid
    material(actor, "booked", doctor_id, day, appt_id, f"token {token}" + (", walk-in at the desk" if checked_in else ""))
    first = appointment_view(appt_id)
    db.execute("UPDATE appointments SET promised_at = ? WHERE id = ?", (first["eta"], appt_id))  # the time the patient was given
    return {"existing": False, "warning": warning, **first}


@route("POST", "/api/book", ("patient",))
def book(user, body):
    patient_id = opt(body, "patient_id", int, user["id"])
    if patient_id not in own_patients(user):
        raise HTTPError(404, "Family member not found.")
    return create_booking(user, patient_id, need(body, "doctor_id", int), body.get("day") or today())


def cancel_appointment(user, a, reason, notify_patient_too=True):
    if a["status"] not in engine.WAITING or a["day"] < today():
        raise HTTPError(409, "Only an upcoming appointment that has not been called can be cancelled.")
    db.execute("UPDATE appointments SET status = 'cancelled', cancelled_at = ? WHERE id = ?", (iso(now()), a["id"]))
    material(user, "cancelled", a["doctor_id"], a["day"], a["id"], reason or None)
    if notify_patient_too:
        enqueue(a["id"], "cancelled", f"cancelled:{a['id']}:{iso(now())}")


@route("POST", "/api/cancel", ("patient", "staff", "admin"))
def cancel(user, body):
    """Patients cancel their own or their family's bookings; the desk can cancel any (and the patient is told)."""
    a = own_appointment(user, need(body, "appointment_id", int))
    cancel_appointment(user, a, text(body, "reason"), notify_patient_too=user["role"] != "patient")
    return appointment_view(a["id"])


@route("POST", "/api/reschedule", ("patient",))
def reschedule(user, body):
    """Cancel and rebook in one transaction: if the new booking is refused, the old one stays."""
    a = own_appointment(user, need(body, "appointment_id", int))
    doctor_id, day = need(body, "doctor_id", int), body.get("day") or today()
    if doctor_id == a["doctor_id"] and day == a["day"]:
        raise HTTPError(400, "That is the same doctor and date. Choose a different one.")
    cancel_appointment(user, a, "rescheduled", notify_patient_too=False)
    return create_booking(user, a["patient_id"], doctor_id, day)


def appointment_view(appt_id):
    a = row("SELECT * FROM appointments WHERE id = ?", appt_id)
    q = queue_state(a["doctor_id"], a["day"])
    e = next(x for x in q["entries"] if x["id"] == appt_id)
    eta, p, t = parse(e["eta"]), policy(), now()
    alert = (eta is not None and a["status"] in engine.WAITING and a["day"] == today()
             and eta - t <= timedelta(minutes=alert_minutes(a["patient_id"], p)))
    opens = eta - timedelta(minutes=int(p["checkin_minutes"])) if eta and a["status"] == "booked" else None
    notes = rows("""SELECT purpose, channel, status, created_at, updated_at FROM notifications
                    WHERE appointment_id = ? ORDER BY id DESC LIMIT 3""", appt_id)
    return {**e, "doctor": q["doctor"], "day": a["day"], "updated_at": q["updated_at"], "arrival_alert": alert,
            "notifications": notes, "patient_id": a["patient_id"],
            "checkin_opens_at": iso(opens) if opens and opens > t else None,
            "checkin_code_required": p["require_checkin_code"] == "1"}


@route("GET", "/api/my-appointments", ("patient",))
def my_appointments(user, body):
    mine = own_patients(user)
    ids = rows(f"""SELECT id FROM appointments WHERE patient_id IN ({','.join('?' * len(mine))}) AND day >= ?
                   AND status != 'cancelled' ORDER BY day, token""", *mine, (date.today() - timedelta(days=1)).isoformat())
    return {"appointments": [appointment_view(r["id"]) for r in ids], "alert_minutes": int(policy()["alert_minutes"])}


@route("POST", "/api/checkin", ("patient", "staff", "admin"))
def checkin(user, body):
    a = own_appointment(user, need(body, "appointment_id", int))
    if a["day"] != today():
        raise HTTPError(409, "Check-in opens on the day of the appointment.")
    if a["status"] == "cancelled":
        raise HTTPError(409, "This appointment was cancelled. Book again if you still need it.")
    if user["role"] == "patient":  # self check-in must be near the turn and, if required, prove presence at reception
        view = appointment_view(a["id"])
        if view["checkin_opens_at"]:
            raise HTTPError(409, f"Self check-in opens at {view['checkin_opens_at'][11:16]}, {policy()['checkin_minutes']} "
                                 "minutes before your expected time. The front desk can check you in earlier.")
        if view["checkin_code_required"] and not hmac.compare_digest(text(body, "code"), checkin_code()):
            raise HTTPError(403, "Enter the check-in code shown on the screen at reception.")
    t = iso(now())
    if a["status"] == "booked":
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ? WHERE id = ?", (t, a["id"]))
        material(user, "checked_in", a["doctor_id"], a["day"], a["id"])
    elif a["status"] == "skipped":  # late arrival: back in at the end of the eligible queue by default (FR-026)
        pos = engine.end_position(queue_entries(a["doctor_id"], a["day"]))
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ?, due_at = NULL, position = ? WHERE id = ?",
                   (t, pos, a["id"]))
        material(user, "reinserted", a["doctor_id"], a["day"], a["id"], "late check-in, end of queue")
    elif a["status"] == "completed":
        raise HTTPError(409, "This consultation is already complete.")
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
                               ORDER BY d.name, a.token LIMIT 50""", today(), like, like, like, term),
            # patient accounts too, so the desk can book a returning walk-in or reset a forgotten password
            "patients": rows("""SELECT u.id, u.username, u.name, COALESCE(g.phone, u.phone) AS phone, g.name AS guardian
                                FROM users u LEFT JOIN users g ON g.id = u.guardian_id
                                WHERE u.role = 'patient' AND u.active = 1 AND (u.name LIKE ? OR u.username LIKE ? OR u.phone LIKE ?)
                                ORDER BY u.name LIMIT 20""", like, like, like)}


@route("POST", "/api/staff/walkin", ("staff", "admin"))
def walkin(user, body):
    """A patient at the desk without the app: find or create their record and give them a token, already checked in."""
    doctor_id = need(body, "doctor_id", int)
    patient_id = opt(body, "patient_id", int, None)
    if patient_id is None:
        name, phone = need(body, "name").strip(), text(body, "phone")
        valid_contact(phone, "", "sms" if phone else "none")
        same = phone and row("""SELECT id FROM users WHERE role = 'patient' AND active = 1 AND guardian_id IS NULL
                                AND lower(name) = lower(?) AND phone = ?""", name, phone)
        patient_id = same["id"] if same else db.execute(
            "INSERT INTO users(username, pw, role, name, phone, channel, lang) VALUES(?,?,?,?,?,?,?)",
            (f"walkin-{secrets.token_hex(4)}", unusable_password(), "patient", name, phone or None,
             "sms" if phone else "none", body.get("lang") if body.get("lang") in LANGS else "en")).lastrowid
    elif not row("SELECT 1 FROM users WHERE id = ? AND role = 'patient' AND active = 1", patient_id):
        raise HTTPError(404, "Patient not found.")
    result = create_booking(user, patient_id, doctor_id, today(), by_staff=True, checked_in=True)
    if result["existing"] and result["status"] in ("booked", "skipped"):  # they had booked in the app: check them in now
        checkin(user, {"appointment_id": result["id"]})
        result = {**result, **appointment_view(result["id"])}
    return {**result, "username": row("SELECT username FROM users WHERE id = ?", patient_id)["username"]}


@route("POST", "/api/staff/patient-password", ("staff", "admin"))
def staff_patient_password(user, body):
    """Desk-assisted reset for a patient who forgot their password (or a walk-in who now wants to use the app)."""
    target = row("SELECT * FROM users WHERE id = ? AND role = 'patient' AND active = 1", need(body, "patient_id", int))
    if not target:
        raise HTTPError(404, "Patient not found.")
    if target["guardian_id"]:
        raise HTTPError(409, "Family members sign in through their guardian's account.")
    password = need(body, "password")
    if len(password) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    db.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_pw(password), target["id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (target["id"],))
    log(user, "patient_password_reset", detail=target["username"])
    return {"ok": True, "username": target["username"]}


QUEUE_ACTIONS = {  # action: roles allowed
    "call_next": ("doctor", "staff"), "start": ("doctor",), "complete": ("doctor",),
    "skip": ("doctor", "staff"), "emergency": ("staff", "admin"), "reinsert_front": ("staff", "admin"),
    "not_present": ("doctor", "staff"), "priority": ("staff", "admin"), "remove_priority": ("staff", "admin"),
    "transfer": ("staff", "admin"), "transfer_all": ("staff", "admin"),
}
QUEUE_WIDE = ("call_next", "transfer_all")  # act on a doctor's queue rather than one appointment


def transfer_target(a_doctor_id, body):
    """The doctor a patient moves to: active, same department, holding OPD today and not marked unavailable."""
    src, dst = doctor_or_404(a_doctor_id), doctor_or_404(need(body, "to_doctor_id", int))
    t = now()
    if dst["id"] == src["id"] or dst["department_id"] != src["department_id"]:
        raise HTTPError(400, "Move patients to another doctor in the same department.")
    if not holds_opd(dst, t.date()) or effective_status(dst, t) == "unavailable":
        raise HTTPError(409, f"{dst['name']} is not holding OPD now.")
    return dst


def move_appointment(user, a, dst):
    """Put a waiting patient at the end of another doctor's queue, keeping their status and priority."""
    if row("SELECT 1 FROM appointments WHERE patient_id = ? AND doctor_id = ? AND day = ?", a["patient_id"], dst["id"], a["day"]):
        raise HTTPError(409, f"This patient already has an appointment record with {dst['name']} today.")
    entries = queue_entries(dst["id"], a["day"])
    token = max((e["token"] for e in entries), default=0) + 1
    db.execute("""UPDATE appointments SET doctor_id = ?, token = ?, position = ?, due_at = NULL, promised_at = NULL,
                  arrival_alerted = 0 WHERE id = ?""", (dst["id"], token, engine.end_position(entries), a["id"]))
    log(user, "transferred_out", a["doctor_id"], a["day"], a["id"], f"token {a['token']} to {dst['name']}, token {token}")
    material(user, "transferred_in", dst["id"], a["day"], a["id"], f"token {token}, was token {a['token']}")
    enqueue(a["id"], "transferred", f"transferred:{a['id']}:{dst['id']}")


@route("POST", "/api/queue/action", ("doctor", "staff", "admin"))
def queue_action(user, body):
    action = need(body, "action")
    if action not in QUEUE_ACTIONS:
        raise HTTPError(400, f"Unknown action: {action}.")
    day = today()
    if action in QUEUE_WIDE:
        a = None
        doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    else:
        a = row("SELECT * FROM appointments WHERE id = ? AND day = ?", need(body, "appointment_id", int), day)
        if not a:
            raise HTTPError(404, "No such appointment in today's queue.")
        doctor_id = a["doctor_id"]
    if not can_operate(user, doctor_id, QUEUE_ACTIONS[action]):
        raise HTTPError(403, "You do not have permission for this action on this queue.")
    if opt(body, "version", int, None) not in (None, queue_version(doctor_id, day)):  # PR-003: no silent overwrite
        raise HTTPError(409, "The queue changed since you loaded it. It has been refreshed; try again.")
    t, reason = now(), text(body, "reason")
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

    if action == "transfer_all":  # e.g. the doctor has to leave: move everyone still waiting, in queue order
        dst = transfer_target(doctor_id, body)
        waiting = [e for e in engine.order(entries) if e["status"] in engine.WAITING]
        moved, kept = 0, []
        for e in waiting:
            try:
                move_appointment(user, row("SELECT * FROM appointments WHERE id = ?", e["id"]), dst)
                moved += 1
            except HTTPError:
                kept.append(e["token"])
        note = f"Moved {moved} waiting patients to {dst['name']}." + (f" Kept tokens {', '.join(map(str, kept))}: they already have a record with {dst['name']} today." if kept else "")
        return {"message": note, **queue_state(doctor_id, day)}

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
        db.execute("UPDATE appointments SET priority = 2, priority_label = 'emergency' WHERE id = ?", (a["id"],))
    elif action == "priority":  # hospital priority groups, ranked after emergencies and before everyone else
        category = text(body, "category")
        if category not in priority_categories():
            raise HTTPError(400, f"Category must be one of: {', '.join(priority_categories())}.")
        if a["status"] not in engine.WAITING or a["priority"] >= 2:
            raise HTTPError(409, "Only a waiting patient without emergency priority can be given a priority category.")
        db.execute("UPDATE appointments SET priority = 1, priority_label = ? WHERE id = ?", (category, a["id"]))
        reason = category
    elif action == "remove_priority":  # undo a mistaken emergency or category, with the reason on record
        if not a["priority"]:
            raise HTTPError(409, "This patient has no priority to remove.")
        if not reason:
            raise HTTPError(400, "Give a reason for removing the priority.")
        db.execute("UPDATE appointments SET priority = 0, priority_label = NULL WHERE id = ?", (a["id"],))
        reason = f"was {a['priority_label'] or 'priority'}: {reason}"
    elif action == "not_present":  # called or checked in, but not at the door: they lose check-in, keep their place
        if a["status"] not in ("called", "checked_in"):
            raise HTTPError(409, "Only a called or checked-in patient can be marked as not here.")
        # a called patient's turn has come, so their grace period starts; anyone else is simply waiting again
        due = iso(engine.turn_cutoff(entry, t)) if a["status"] == "called" else None
        db.execute("UPDATE appointments SET status = 'booked', checked_in_at = NULL, due_at = ? WHERE id = ?", (due, a["id"]))
    elif action == "transfer":
        if a["status"] not in engine.WAITING:
            raise HTTPError(409, "Only a waiting patient can be moved to another doctor.")
        move_appointment(user, a, transfer_target(doctor_id, body))
        return queue_state(doctor_id, day)
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
    db.execute("UPDATE doctors SET status = ?, break_until = ?, status_day = ? WHERE id = ?", (status, until, today(), doctor_id))
    material(user, "doctor_" + status, doctor_id, today(), None, until and f"until {until[11:16]}")
    return queue_state(doctor_id, today())


# ---------- administration ----------

@route("GET", "/api/admin/overview", ("staff", "admin"))
def overview(user, body):
    """Workload per doctor today (FR-033, FR-038)."""
    p, t, day = policy(), now(), today()
    out = []
    for d in rows("SELECT id FROM doctors WHERE active = 1 ORDER BY name"):
        q = queue_state(d["id"], day)
        _, close = hours(doctor_or_404(d["id"]), t.date(), p)
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
                         'doctor_unavailable','doctor_break','priority','remove_priority','not_present','transferred_out',
                         'cancelled') ORDER BY e.id DESC LIMIT 20""", day)
    failed = row("SELECT COUNT(*) AS n FROM notifications WHERE status = 'failed' AND created_at >= ?", day)["n"]
    return {"doctors": out, "exceptions": exceptions, "failed_alerts": failed, "updated_at": iso(t), "opd_end": p["opd_end"]}


@route("GET", "/api/admin/events", ("admin",))
def events(user, body):
    """Audit log, newest first, 200 a page. Filters: q (text in action, detail, actor or doctor),
    action, day; before = the last id of the previous page."""
    where, args = ["1"], []
    if text(body, "q"):
        where.append("(e.action LIKE ? OR e.detail LIKE ? OR u.name LIKE ? OR d.name LIKE ?)")
        args += [f"%{text(body, 'q')}%"] * 4
    if text(body, "action"):
        where.append("e.action = ?")
        args.append(text(body, "action"))
    if text(body, "day"):
        where.append("substr(e.at, 1, 10) = ?")
        args.append(parse_day(text(body, "day")).isoformat())
    before = opt(body, "before", int, None)
    if before is not None:
        where.append("e.id < ?")
        args.append(before)
    found = rows(f"""SELECT e.*, u.name AS actor, d.name AS doctor, a.token FROM events e
                     LEFT JOIN users u ON u.id = e.actor_id LEFT JOIN doctors d ON d.id = e.doctor_id
                     LEFT JOIN appointments a ON a.id = e.appointment_id WHERE {' AND '.join(where)}
                     ORDER BY e.id DESC LIMIT 201""", *args)
    return {"events": found[:200], "more": len(found) > 200,
            "actions": [r["action"] for r in rows("SELECT DISTINCT action FROM events ORDER BY action")]}


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
        d["learned_minutes"], d["learned_from"] = learned_minutes(d["id"], today(), d["avg_minutes"])
    return {"doctors": docs, "departments": rows("SELECT * FROM departments ORDER BY name")}


def doctor_settings(body, doc=None):
    """Optional daily cap and the doctor's own OPD hours (empty = hospital hours), validated together."""
    cur = doc or {"max_patients": None, "opd_start": None, "opd_end": None}
    cap = opt(body, "max_patients", int, None) if "max_patients" in body else cur["max_patients"]
    start = text(body, "opd_start") or None if "opd_start" in body else cur["opd_start"]
    end = text(body, "opd_end") or None if "opd_end" in body else cur["opd_end"]
    if cap is not None and not 1 <= cap <= 500:
        raise HTTPError(400, "Daily limit must be 1 to 500 patients, or empty for no limit.")
    if bool(start) != bool(end):
        raise HTTPError(400, "Give both the doctor's opening and closing time, or neither to use hospital hours.")
    try:
        if start and time.fromisoformat(start) >= time.fromisoformat(end):
            raise HTTPError(400, "The doctor's OPD must open before it closes.")
    except ValueError:
        raise HTTPError(400, "Times must look like 09:00.")
    return cap or None, start, end


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
    username, password = valid_username(need(body, "username").strip().lower()), need(body, "password")
    avg = opt(body, "avg_minutes", float, 10)
    work_days = clean_days(body.get("work_days", "012345"))  # an explicit empty value is an error, not the default
    if not row("SELECT 1 FROM departments WHERE id = ?", dep):
        raise HTTPError(404, "Department not found.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken.")
    if len(password) < 8 or not 1 <= avg <= 120:
        raise HTTPError(400, "Password needs 8+ characters and usual consultation time must be 1 to 120 minutes.")
    cap, start, end = doctor_settings(body)
    doc_id = db.execute("""INSERT INTO doctors(name, department_id, avg_minutes, work_days, max_patients, opd_start, opd_end)
                           VALUES(?,?,?,?,?,?,?)""", (name, dep, avg, work_days, cap, start, end)).lastrowid
    db.execute("INSERT INTO users(username, pw, role, name, doctor_id) VALUES(?,?,?,?,?)",
               (username, hash_pw(password), "doctor", name, doc_id))
    log(user, "doctor_added", doc_id, detail=name)
    return {"ok": True, "doctor_id": doc_id}


@route("POST", "/api/admin/doctor/update", ("admin",))
def update_doctor(user, body):
    doc = doctor_or_404(need(body, "doctor_id", int))
    name = text(body, "name") or doc["name"]
    dep = opt(body, "department_id", int, doc["department_id"])
    avg = opt(body, "avg_minutes", float, doc["avg_minutes"])
    work_days = clean_days(body.get("work_days", doc["work_days"]))
    active = int(bool(body["active"])) if "active" in body else doc["active"]
    password = opt(body, "password", str, None)
    if not row("SELECT 1 FROM departments WHERE id = ?", dep):
        raise HTTPError(404, "Department not found.")
    if not 1 <= avg <= 120:
        raise HTTPError(400, "Usual consultation time must be 1 to 120 minutes.")
    if password is not None and len(password) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    cap, start, end = doctor_settings(body, doc)
    db.execute("""UPDATE doctors SET name = ?, department_id = ?, avg_minutes = ?, work_days = ?, active = ?,
                  max_patients = ?, opd_start = ?, opd_end = ? WHERE id = ?""",
               (name, dep, avg, work_days, active, cap, start, end, doc["id"]))
    db.execute("UPDATE users SET name = ?, active = ? WHERE doctor_id = ?", (name, active, doc["id"]))
    if password is not None:  # admin reset for a doctor who forgot their password; their sessions end
        db.execute("UPDATE users SET pw = ? WHERE doctor_id = ?", (hash_pw(password), doc["id"]))
        db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE doctor_id = ?)", (doc["id"],))
    material(user, "doctor_updated", doc["id"], today(), None,
             json.dumps({"name": name, "department_id": dep, "avg_minutes": avg, "work_days": work_days, "active": active,
                         "max_patients": cap, "opd_start": start, "opd_end": end}))
    return {"ok": True}


@route("POST", "/api/admin/leave", ("admin",))
def leave(user, body):
    doc = doctor_or_404(need(body, "doctor_id", int))
    day = parse_day(need(body, "day")).isoformat()
    if body.get("remove"):
        db.execute("DELETE FROM doctor_leave WHERE doctor_id = ? AND day = ?", (doc["id"], day))
        material(user, "leave_removed", doc["id"], day, None, day)
        return {"ok": True}
    affected = rows("SELECT id FROM appointments WHERE doctor_id = ? AND day = ? AND status IN ('booked','checked_in')",
                    doc["id"], day)
    db.execute("INSERT OR IGNORE INTO doctor_leave VALUES(?,?)", (doc["id"], day))
    material(user, "leave_added", doc["id"], day, None, day)
    for a in affected:  # tell booked patients straight away, so they can rebook
        enqueue(a["id"], "doctor_leave", f"doctor_leave:{a['id']}:{day}")
    return {"ok": True, "affected_appointments": len(affected)}


@route("GET", "/api/admin/users", ("admin",))
def users(user, body):
    return {"users": rows("""SELECT id, username, role, name, phone, email, active FROM users
                             WHERE role IN ('staff','admin','tester') ORDER BY role, name""")}


@route("POST", "/api/admin/staff", ("admin",))
def add_staff(user, body):
    name, username, password = need(body, "name").strip(), valid_username(need(body, "username").strip().lower()), need(body, "password")
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
    password = opt(body, "password", str, None)
    db.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, active, target["id"]))
    if password is not None:
        if len(password) < 8:
            raise HTTPError(400, "Password must be at least 8 characters.")
        db.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_pw(password), target["id"]))
    if not active or role != target["role"] or password is not None:
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target["id"],))
    log(user, "user_updated", detail=f"{target['username']}: role={role}, active={active}")
    return {"ok": True}


@route("GET", "/api/admin/policy", ("staff", "admin"))
def get_policy(user, body):
    """Policy plus what the desk needs to set up reception: today's check-in code and the display-screen key."""
    return {**policy(), "checkin_code": checkin_code(), "display_key": display_key()}


@route("POST", "/api/admin/policy", ("admin",))
def set_policy(user, body):
    new = {k: str(body[k]).strip() for k in DEFAULT_POLICY if k in body}
    try:
        for k in ("opd_start", "opd_end"):
            if k in new:
                time.fromisoformat(new[k])
    except ValueError:
        raise HTTPError(400, "Times must look like 09:00.")
    for k, (lo, hi) in NUMERIC_POLICY.items():
        if k in new and not (new[k].isdigit() and lo <= int(new[k]) <= hi):
            raise HTTPError(400, f"{k.replace('_', ' ').capitalize()} must be a whole number from {lo} to {hi}.")
    if "priority_categories" in new:
        cats = [c.strip() for c in new["priority_categories"].split(",") if c.strip()]
        if not cats or len(new["priority_categories"]) > MAX_FIELD or "emergency" in (c.lower() for c in cats):
            raise HTTPError(400, "List priority categories separated by commas (emergency is built in).")
        new["priority_categories"] = ", ".join(cats)
    merged = {**policy(), **new}
    if time.fromisoformat(merged["opd_start"]) >= time.fromisoformat(merged["opd_end"]):
        raise HTTPError(400, "OPD must open before it closes.")
    for k, v in new.items():
        db.execute("INSERT INTO policy VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
    log(user, "policy_changed", detail=json.dumps(new))
    if "retention_days" in new:  # applies now as well as nightly
        purge_once()
    return policy()


def csv_cell(v):
    """Patient-supplied text such as names could start a spreadsheet formula; prefix it so it stays text."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def csv_response(name, header, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows([csv_cell(v) for v in r] for r in data)
    return {"_raw": buf.getvalue().encode(), "_type": "text/csv; charset=utf-8", "_filename": name}


@route("GET", "/api/admin/export", ("admin",))
def export(user, body):
    """Operational summaries as CSV (FR-040)."""
    kind, day = body.get("kind") or "queue", body.get("day") or today()
    parse_day(day)
    if kind == "queue":
        data = rows("""SELECT d.name, a.token, a.status, a.priority_label, a.booked_at, a.checked_in_at, a.started_at, a.ended_at,
                       a.skip_reason FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.day = ? ORDER BY d.name, a.token""", day)
        return csv_response(f"queue-{day}.csv", ["doctor", "token", "status", "priority", "booked_at", "checked_in_at",
                                                 "started_at", "ended_at", "skip_reason"], [list(r.values()) for r in data])
    if kind == "analytics":
        a = analytics(user, body)
        cols = ["doctor", "department", "booked", "seen", "not_seen", "cancelled", "no_show_rate", "avg_wait_minutes",
                "avg_consult_minutes", "seen_per_hour", "eta_n", "eta_mae", "eta_within_15"]
        return csv_response(f"analytics-{a['from']}-to-{a['to']}.csv", cols, [[d[c] for c in cols] for d in a["doctors"] + [a["total"]]])
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
    raise HTTPError(400, "Export kind must be queue, events, notifications or analytics.")


def mean(xs):
    return round(sum(xs) / len(xs), 1) if xs else None


def summarise(group, label, department=""):
    """One analytics row. Wait = check-in to start. ETA error compares the ETA a patient
    held when they checked in with when they were actually seen (measured, not simulated)."""
    seen = [a for a in group if a["started_at"]]
    waits = [(parse(a["started_at"]) - parse(a["checked_in_at"])).total_seconds() / 60 for a in seen if a["checked_in_at"]]
    consults = [(parse(a["ended_at"]) - parse(a["started_at"])).total_seconds() / 60 for a in seen if a["ended_at"]]
    errors = [abs((parse(a["started_at"]) - parse(a["eta_at_checkin"])).total_seconds()) / 60 for a in seen if a["eta_at_checkin"]]
    booked = [a for a in group if a["status"] != "cancelled"]
    not_seen = sum(a["status"] == "skipped" for a in group)
    session_hours = 0.0  # per day: first consultation start to last consultation end
    for d in {a["day"] for a in seen}:
        day_seen = [a for a in seen if a["day"] == d]
        ends = [parse(a["ended_at"]) for a in day_seen if a["ended_at"]]
        if ends:
            session_hours += (max(ends) - min(parse(a["started_at"]) for a in day_seen)).total_seconds() / 3600
    return {"doctor": label, "department": department, "booked": len(booked), "seen": len(seen), "not_seen": not_seen,
            "cancelled": len(group) - len(booked), "no_show_rate": round(not_seen / len(booked), 3) if booked else None,
            "avg_wait_minutes": mean(waits), "avg_consult_minutes": mean([c for c in consults if c >= 1]),
            "seen_per_hour": round(len(seen) / session_hours, 1) if session_hours > 0 else None,
            "eta_n": len(errors), "eta_mae": mean(errors),
            "eta_within_15": round(sum(e <= 15 for e in errors) / len(errors), 3) if errors else None}


@route("GET", "/api/admin/analytics", ("admin",))
def analytics(user, body):
    """Operational analytics for a date range (default: the last 30 days)."""
    to = parse_day(text(body, "to") or today())
    frm = parse_day(text(body, "from") or (to - timedelta(days=29)).isoformat())
    if frm > to or (to - frm).days > 366:
        raise HTTPError(400, "Choose a range of up to one year, start before end.")
    appts = rows("""SELECT a.*, d.name AS doctor, dep.name AS department,
                    (SELECT s.eta FROM eta_snapshots s WHERE s.appointment_id = a.id AND s.calculated_at <= a.checked_in_at
                     ORDER BY s.id DESC LIMIT 1) AS eta_at_checkin
                    FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN departments dep ON dep.id = d.department_id
                    WHERE a.day BETWEEN ? AND ?""", frm.isoformat(), to.isoformat())
    names = sorted({(a["doctor"], a["department"]) for a in appts})
    doctors = [summarise([a for a in appts if a["doctor"] == n], n, dep) for n, dep in names]
    by_hour = [{"hour": h, "checked_in": sum(1 for a in appts if a["checked_in_at"] and int(a["checked_in_at"][11:13]) == h),
                "seen": sum(1 for a in appts if a["started_at"] and int(a["started_at"][11:13]) == h)} for h in range(24)]
    return {"from": frm.isoformat(), "to": to.isoformat(), "doctors": doctors, "total": summarise(appts, "All doctors"),
            "by_hour": by_hour}


# ---------- reception display and backups ----------

@route("GET", "/api/display")
def display(user, body):
    """Waiting-room screen: tokens only, never patient names. Opened with the display key, not a staff sign-in,
    so no staff session is left running on a public screen."""
    if not hmac.compare_digest(text(body, "key"), display_key()):
        raise HTTPError(403, "This display link is not valid. Copy it again from Staff and policy.")
    day, p = today(), policy()
    boards = []
    for d in rows("SELECT id FROM doctors WHERE active = 1 ORDER BY name"):
        q = queue_state(d["id"], day)
        if not q["doctor"]["holds_opd"]:
            continue
        current = next((e for e in q["entries"] if e["status"] in ("called", "in_consultation")), None)
        waiting = [e for e in q["entries"] if e["status"] in engine.WAITING]
        boards.append({"doctor": q["doctor"]["name"], "department": q["doctor"]["department"], "status": q["doctor"]["status"],
                       "break_until": q["doctor"]["break_until"], "now": current and current["token"],
                       "now_status": current and current["status"], "next": [e["token"] for e in waiting[:5]], "waiting": len(waiting)})
    return {"doctors": boards, "updated_at": iso(now()),
            "checkin_code": checkin_code() if p["require_checkin_code"] == "1" else None}


@route("GET", "/api/admin/backups", ("admin",))
def list_backups(user, body):
    files = sorted(BACKUP_DIR.glob("opd-*.db"), reverse=True) if BACKUP_DIR.exists() else []
    return {"folder": str(BACKUP_DIR), "keep": BACKUP_KEEP,
            "backups": [{"name": f.name, "bytes": f.stat().st_size} for f in files[:30]]}


@route("POST", "/api/admin/backup", ("admin",))
def backup_now(user, body):
    path = backup("manual")
    log(user, "backup_made", detail=path.name)
    return {"ok": True, "name": path.name}


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


@functools.lru_cache(maxsize=64)
def run_brief(path, mtime):
    """Summary of one saved report. Cached by modification time: the list is polled while the request lock is held."""
    r = json.loads(Path(path).read_text())
    brief = {name: {m: res["summary"][m] for m in ("eta_mae", "eta_within_15", "wait_after_checkin")}
             for name, res in r["results"].items()}
    return {k: r[k] for k in ("run_id", "label", "created_at", "software_version", "scenarios",
                              "runs_per_scenario", "runtime_seconds")} | {"summary": brief}


@route("GET", "/api/sim/runs", ("tester", "admin"))
def sim_runs(user, body):
    runs = []
    for f in sorted(SIM_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            runs.append(run_brief(str(f), f.stat().st_mtime))
        except (OSError, ValueError, KeyError):
            continue
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
    if pending:
        bump()


def tick_once():
    """Time passes without events, so arrival alerts are checked on a timer too (FR-017).
    Also closes earlier days: anyone still waiting was not seen, and a consultation left open is ended."""
    with lock, db:
        close_past_days()
        for q in rows("""SELECT DISTINCT doctor_id FROM appointments
                         WHERE day = ? AND status IN ('booked','checked_in','called','in_consultation')""", today()):
            after_change(q["doctor_id"], today(), "tick")
    bump()  # ETAs move with the clock, so open screens refresh


def close_past_days():
    left = rows("""SELECT id, doctor_id, day, status FROM appointments
                   WHERE day < ? AND status IN ('booked','checked_in','called','in_consultation')""", today())
    for a in left:
        if a["status"] == "in_consultation":  # the doctor forgot to press Complete; no end time, so it never skews averages
            db.execute("UPDATE appointments SET status = 'completed' WHERE id = ?", (a["id"],))
        else:
            db.execute("UPDATE appointments SET status = 'skipped', skip_reason = 'not seen: OPD day closed' WHERE id = ?", (a["id"],))
    for doctor_id, day in sorted({(a["doctor_id"], a["day"]) for a in left}):
        n = sum(1 for a in left if (a["doctor_id"], a["day"]) == (doctor_id, day))
        log(None, "day_closed", doctor_id, day, None, f"{n} appointments still open were closed")


def purge_once():
    """Data retention (policy retention_days, 0 = keep everything): delete visits, their ETA history and
    alerts, and audit events older than the limit. Patient accounts are kept; patients delete those themselves."""
    days = int(policy()["retention_days"])
    if not days:
        return
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    old = "SELECT id FROM appointments WHERE day < ?"
    counts = [db.execute(f"DELETE FROM eta_snapshots WHERE appointment_id IN ({old})", (cutoff,)).rowcount,
              db.execute(f"DELETE FROM notifications WHERE appointment_id IN ({old}) OR (appointment_id IS NULL AND created_at < ?)",
                         (cutoff, cutoff)).rowcount,
              db.execute("DELETE FROM appointments WHERE day < ?", (cutoff,)).rowcount,
              db.execute("DELETE FROM events WHERE at < ?", (cutoff,)).rowcount]
    if any(counts):
        log(None, "retention_purge", detail=f"before {cutoff}: {counts[2]} visits, {counts[0]} ETA records, "
                                            f"{counts[1]} alerts, {counts[3]} audit events")


def daily_once():
    """Once a day: back up (if today's backup is missing) and apply data retention."""
    with lock:
        if not list(BACKUP_DIR.glob(f"opd-{now():%Y%m%d}-*-daily.db")):
            backup()
        with db:
            purge_once()


def background():
    last_tick, last_day = 0.0, None
    while True:
        try:
            if last_day != today():
                daily_once()
                last_day = today()
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
        if url.path == "/favicon.ico":  # no icon; answer quietly instead of logging a 404 in every browser console
            return self.send(204, b"", "image/x-icon")
        if method == "GET" and url.path == "/api/stream":
            return self.stream()
        found = ROUTES.get((method, url.path))
        if not found:
            return self.send_json(404, {"error": "Not found."})
        fn, roles = found
        try:
            if method == "POST":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    raise HTTPError(400, "Invalid Content-Length.")
                if length < 0:  # read(-1) would block until the client closes the connection
                    raise HTTPError(400, "Invalid Content-Length.")
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
            if method == "POST":
                bump()
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

    def stream(self):
        """Server-sent events: one message per committed change, so screens refresh at once instead of
        on a timer. Holds this connection's thread, never the request lock; ends when the session does."""
        with lock:
            user = self.current_user()
        if not user:
            return self.send_json(401, {"error": "Please sign in."})
        self.send_response(200)
        for k, v in {**SECURITY_HEADERS, "Content-Type": "text/event-stream"}.items():
            self.send_header(k, v)
        self.end_headers()
        seen = change_seq
        try:
            while True:
                with changes:
                    changes.wait_for(lambda: change_seq != seen, timeout=25)
                if change_seq != seen:
                    seen = change_seq
                    self.wfile.write(f"data: {seen}\n\n".encode())
                else:
                    self.wfile.write(b": still here\n\n")  # keeps proxies from closing an idle connection
                self.wfile.flush()
                with lock:
                    if not self.current_user():
                        return
        except OSError:  # the browser closed the page
            return

    def current_user(self):
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        token = jar["sid"].value if "sid" in jar else None
        if not token:
            return None
        s = row("""SELECT u.*, s.created, s.token_hash FROM sessions s JOIN users u ON u.id = s.user_id
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


COLUMNS_ADDED_IN_1_1 = [
    ("users", "guardian_id", "INTEGER REFERENCES users(id)"), ("users", "lang", "TEXT NOT NULL DEFAULT 'en'"),
    ("users", "alert_lead", "INTEGER"), ("users", "reset_hash", "TEXT"), ("users", "reset_expires", "TEXT"),
    ("users", "reset_tries", "INTEGER NOT NULL DEFAULT 0"), ("doctors", "status_day", "TEXT"),
    ("doctors", "max_patients", "INTEGER"), ("doctors", "opd_start", "TEXT"), ("doctors", "opd_end", "TEXT"),
]
APPOINTMENT_COLUMNS_1_0 = ("id, patient_id, doctor_id, day, token, position, status, booked_at, checked_in_at, due_at, "
                           "started_at, ended_at, skip_reason, promised_at, arrival_alerted")


def migrate():
    """Upgrade a 1.0 database in place, after saving a backup. New columns are added; the appointments
    table is rebuilt because its status check must allow 'cancelled' (SQLite cannot alter a CHECK)."""
    have = lambda table: {r["name"] for r in rows(f"PRAGMA table_info({table})")}
    missing = [(t, c, decl) for t, c, decl in COLUMNS_ADDED_IN_1_1 if c not in have(t)]
    old_appointments = "'cancelled'" not in row("SELECT sql FROM sqlite_master WHERE name = 'appointments'")["sql"]
    if not missing and not old_appointments:
        return
    print(f"Upgrading the database to {engine.VERSION}. Backup first: {backup('pre-upgrade')}", flush=True)
    for table, column, decl in missing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    if old_appointments:
        db.execute("PRAGMA foreign_keys = OFF")  # only takes effect outside a transaction
        with db:
            db.execute("BEGIN")  # the whole rebuild is one transaction: a failure leaves the 1.0 table as it was
            db.execute(APPOINTMENTS.format(name="appointments_new"))
            # 1.0 had one priority level (1 = emergency); emergencies are now level 2
            db.execute(f"""INSERT INTO appointments_new({APPOINTMENT_COLUMNS_1_0}, priority, priority_label)
                           SELECT {APPOINTMENT_COLUMNS_1_0}, CASE WHEN priority > 0 THEN 2 ELSE 0 END,
                                  CASE WHEN priority > 0 THEN 'emergency' END FROM appointments""")
            db.execute("DROP TABLE appointments")
            db.execute("ALTER TABLE appointments_new RENAME TO appointments")
            db.execute("CREATE INDEX IF NOT EXISTS appt_queue ON appointments(doctor_id, day)")
            broken = rows("PRAGMA foreign_key_check")
            if broken:
                raise RuntimeError(f"Upgrade stopped, nothing changed: foreign key problems {broken[:5]}")
        db.execute("PRAGMA foreign_keys = ON")


def init_db(demo):
    db.executescript(SCHEMA)
    migrate()
    with db:
        db.execute("INSERT OR IGNORE INTO policy VALUES('_secret', ?)", (secrets.token_hex(32),))
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
