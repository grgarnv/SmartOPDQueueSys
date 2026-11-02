"""Smart OPD web server: JSON API, SQLite storage and the single-page UI.

Run:  python3 app/server.py   then open http://localhost:8000
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
from datetime import date, datetime, time, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import engine

HERE = Path(__file__).parent
DB_PATH = os.environ.get("OPD_DB", str(HERE / "opd.db"))
SESSION_HOURS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS doctors(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  department_id INTEGER NOT NULL REFERENCES departments(id),
  avg_minutes REAL NOT NULL DEFAULT 10,
  status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','break','unavailable')),
  break_until TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('patient','doctor','staff','admin')),
  name TEXT NOT NULL, phone TEXT, doctor_id INTEGER REFERENCES doctors(id));
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created TEXT NOT NULL);
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
  skip_reason TEXT,
  UNIQUE(patient_id, doctor_id, day), UNIQUE(doctor_id, day, token));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL, doctor_id INTEGER, day TEXT, appointment_id INTEGER, detail TEXT);
"""

DEFAULT_POLICY = {"opd_start": "09:00", "opd_end": "17:00", "grace_minutes": "10", "alert_minutes": "30"}

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA foreign_keys = ON")
# ponytail: one global lock serialises every request, which also makes queue actions atomic (PR-003); per-queue locks if load grows
lock = threading.Lock()


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# ---------- helpers ----------

def now():
    return datetime.now().replace(microsecond=0)


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


def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def check_pw(password, stored):
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_pw(password, salt), stored)


def policy():
    return {**DEFAULT_POLICY, **{r["key"]: r["value"] for r in rows("SELECT * FROM policy")}}


def log(actor, action, doctor_id=None, day=None, appointment_id=None, detail=None):
    """Every queue change and admin action lands here: queue history and audit log (FR-016, FR-027, FR-039)."""
    db.execute("INSERT INTO events(at, actor_id, action, doctor_id, day, appointment_id, detail) VALUES(?,?,?,?,?,?,?)",
               (iso(now()), actor and actor["id"], action, doctor_id, day, appointment_id, detail))


def doctor_or_404(doctor_id):
    doc = row("SELECT d.*, dep.name AS department FROM doctors d JOIN departments dep ON dep.id = d.department_id WHERE d.id = ?", doctor_id)
    if not doc:
        raise HTTPError(404, "Doctor not found.")
    return doc


def effective_status(doc, t):
    """A break that has run out counts as available again."""
    if doc["status"] == "break" and (not doc["break_until"] or parse(doc["break_until"]) <= t):
        return "available"
    return doc["status"]


def queue_entries(doctor_id, day):
    entries = rows("""SELECT a.*, u.name AS patient_name FROM appointments a
                      JOIN users u ON u.id = a.patient_id WHERE a.doctor_id = ? AND a.day = ?""", doctor_id, day)
    for e in entries:
        e["due_at"], e["started_at"] = parse(e["due_at"]), parse(e["started_at"])
    return entries


def queue_state(doctor_id, day):
    """Current queue for one doctor and day with fresh ETAs. ETAs are recomputed on
    every read, so every view sees the latest committed state (FR-012, FR-013)."""
    doc = doctor_or_404(doctor_id)
    p, t = policy(), now()
    entries = queue_entries(doctor_id, day)
    durations = [(parse(e["ended_at"]) - e["started_at"]).total_seconds() / 60
                 for e in sorted(entries, key=lambda e: e["ended_at"] or "") if e["status"] == "completed" and e["ended_at"]]
    avg = engine.expected_minutes(durations, doc["avg_minutes"])
    status = effective_status(doc, t)
    opd_start = datetime.combine(date.fromisoformat(day), time.fromisoformat(p["opd_start"]))
    etas = engine.compute_etas(entries, t, avg, opd_start, available=status != "unavailable",
                               break_until=parse(doc["break_until"]) if status == "break" else None)
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
    version = row("SELECT COUNT(*) AS n FROM events WHERE doctor_id = ? AND day = ?", doctor_id, day)["n"]
    return {"doctor": {"id": doc["id"], "name": doc["name"], "department": doc["department"], "status": status,
                       "break_until": doc["break_until"] if status == "break" else None},
            "day": day, "avg_minutes": round(avg, 1), "version": version, "updated_at": iso(t), "entries": out}


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


ALL = ("patient", "doctor", "staff", "admin")


@route("POST", "/api/register")
def register(user, body):
    username, password = need(body, "username").strip().lower(), need(body, "password")
    name, phone = need(body, "name").strip(), body.get("phone", "").strip()
    if len(password) < 6:
        raise HTTPError(400, "Password must be at least 6 characters.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken. Choose another.")
    db.execute("INSERT INTO users(username, pw, role, name, phone) VALUES(?,?,?,?,?)",
               (username, hash_pw(password), "patient", name, phone))
    return login(None, body)


@route("POST", "/api/login")
def login(user, body):
    u = row("SELECT * FROM users WHERE username = ?", need(body, "username").strip().lower())
    if not u or not check_pw(need(body, "password"), u["pw"]):
        raise HTTPError(401, "Wrong username or password.")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (token, u["id"], iso(now())))
    return {"_cookie": token, **public_user(u)}


@route("POST", "/api/logout", ALL)
def logout(user, body):
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    return {"_cookie": "", "ok": True}


def public_user(u):
    return {k: u[k] for k in ("id", "username", "role", "name", "doctor_id")}


@route("GET", "/api/me", ALL)
def me(user, body):
    return public_user(user)


@route("GET", "/api/departments", ALL)
def departments(user, body):
    """Departments with doctors and today's load, so patients can see less busy options (FR-034, advisory only)."""
    today = date.today().isoformat()
    deps = rows("SELECT * FROM departments ORDER BY name")
    for dep in deps:
        dep["doctors"] = []
        for d in rows("SELECT id FROM doctors WHERE department_id = ? ORDER BY name", dep["id"]):
            q = queue_state(d["id"], today)
            waiting = [e for e in q["entries"] if e["ahead"] is not None]
            last = max((e["eta"] for e in waiting if e["eta"]), default=None)
            clears = iso(parse(last) + timedelta(minutes=q["avg_minutes"])) if last else None
            dep["doctors"].append({**q["doctor"], "waiting": len(waiting), "clears_at": clears})
    return {"departments": deps}


@route("POST", "/api/book", ("patient",))
def book(user, body):
    doctor_id = need(body, "doctor_id", int)
    day = body.get("day") or date.today().isoformat()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPError(400, "Date must look like 2026-11-02.")
    t, p = now(), policy()
    doc = doctor_or_404(doctor_id)
    if d < t.date():
        raise HTTPError(400, "Choose today or a later date.")
    if d == t.date() and t.time() >= time.fromisoformat(p["opd_end"]):
        raise HTTPError(409, f"OPD has closed for today (closes {p['opd_end']}). Choose another date.")
    # ponytail: availability is a same-day flag; add per-date schedules when admins need to plan leave ahead
    if d == t.date() and effective_status(doc, t) == "unavailable":
        raise HTTPError(409, f"{doc['name']} is not available today. Choose another doctor or date.")
    existing = row("SELECT id FROM appointments WHERE patient_id = ? AND doctor_id = ? AND day = ?", user["id"], doctor_id, day)
    if existing:  # FR-009: a repeat submission returns the same booking instead of a duplicate
        return {"existing": True, **appointment_view(existing["id"])}
    entries = queue_entries(doctor_id, day)
    token = max((e["token"] for e in entries), default=0) + 1
    cur = db.execute("INSERT INTO appointments(patient_id, doctor_id, day, token, position, booked_at) VALUES(?,?,?,?,?,?)",
                     (user["id"], doctor_id, day, token, engine.end_position(entries), iso(t)))
    log(user, "booked", doctor_id, day, cur.lastrowid, f"token {token}")
    return {"existing": False, **appointment_view(cur.lastrowid)}


def appointment_view(appt_id):
    a = row("SELECT * FROM appointments WHERE id = ?", appt_id)
    q = queue_state(a["doctor_id"], a["day"])
    e = next(x for x in q["entries"] if x["id"] == appt_id)
    alert_min = int(policy()["alert_minutes"])
    eta = parse(e["eta"])
    alert = (eta is not None and a["status"] in engine.WAITING and a["day"] == date.today().isoformat()
             and eta - now() <= timedelta(minutes=alert_min))
    return {**e, "doctor": q["doctor"], "day": a["day"], "updated_at": q["updated_at"], "arrival_alert": alert}


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
    if a["day"] != date.today().isoformat():
        raise HTTPError(409, "Check-in opens on the day of the appointment.")
    t = iso(now())
    if a["status"] == "booked":
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ? WHERE id = ?", (t, a["id"]))
        log(user, "checked_in", a["doctor_id"], a["day"], a["id"])
    elif a["status"] == "skipped":  # late arrival: back in at the end of the queue by default (FR-026)
        pos = engine.end_position(queue_entries(a["doctor_id"], a["day"]))
        db.execute("UPDATE appointments SET status = 'checked_in', checked_in_at = ?, due_at = NULL, position = ? WHERE id = ?",
                   (t, pos, a["id"]))
        log(user, "reinserted", a["doctor_id"], a["day"], a["id"], "late check-in, end of queue")
    else:
        raise HTTPError(409, "This appointment is already checked in.")
    return appointment_view(a["id"])


@route("GET", "/api/queue", ("doctor", "staff", "admin"))
def queue(user, body):
    doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    return queue_state(doctor_id, body.get("day") or date.today().isoformat())


QUEUE_ACTIONS = {  # action: roles allowed
    "call_next": ("doctor", "staff"), "start": ("doctor",), "complete": ("doctor",),
    "skip": ("doctor", "staff"), "emergency": ("staff", "admin"), "reinsert_front": ("staff", "admin"),
}


@route("POST", "/api/queue/action", ("doctor", "staff", "admin"))
def queue_action(user, body):
    action = need(body, "action")
    if action not in QUEUE_ACTIONS:
        raise HTTPError(400, f"Unknown action: {action}.")
    day = date.today().isoformat()
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
    q = queue_state(doctor_id, day)
    if "version" in body and int(body["version"]) != q["version"]:  # PR-003: no silent overwrite
        raise HTTPError(409, "The queue changed since you loaded it. It has been refreshed; try again.")
    t, reason = now(), (body.get("reason") or "").strip()
    entries = queue_entries(doctor_id, day)

    if action == "call_next":
        if any(e["status"] in ("called", "in_consultation") for e in entries):
            raise HTTPError(409, "Finish the current patient before calling the next one.")
        chosen, missed = engine.next_to_call(entries)
        for e in missed:
            if e["due_at"] is None:  # their turn came but they are not here: grace period starts now
                db.execute("UPDATE appointments SET due_at = ? WHERE id = ?", (iso(t), e["id"]))
                log(user, "turn_missed", doctor_id, day, e["id"], f"token {e['token']} not checked in")
        if not chosen:
            if missed:
                return {"called": None, "message": "Nobody waiting has checked in yet.", **queue_state(doctor_id, day)}
            raise HTTPError(409, "No patients are waiting.")
        db.execute("UPDATE appointments SET status = 'called' WHERE id = ?", (chosen["id"],))
        log(user, "called", doctor_id, day, chosen["id"], f"token {chosen['token']}")
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
    elif action == "emergency":
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
    log(user, action, doctor_id, day, a["id"], reason or None)
    return queue_state(doctor_id, day)


@route("POST", "/api/doctor/status", ("doctor", "staff", "admin"))
def doctor_status(user, body):
    doctor_id = user["doctor_id"] if user["role"] == "doctor" else need(body, "doctor_id", int)
    doctor_or_404(doctor_id)
    status = need(body, "status")
    if status not in ("available", "break", "unavailable"):
        raise HTTPError(400, "Status must be available, break or unavailable.")
    until = None
    if status == "break":
        minutes = need(body, "minutes", int)
        if not 1 <= minutes <= 240:
            raise HTTPError(400, "Break length must be 1 to 240 minutes.")
        until = iso(now() + timedelta(minutes=minutes))
    db.execute("UPDATE doctors SET status = ?, break_until = ? WHERE id = ?", (status, until, doctor_id))
    log(user, "doctor_" + status, doctor_id, date.today().isoformat(), None, until and f"until {until[11:16]}")
    return queue_state(doctor_id, date.today().isoformat())


# ---------- admin ----------

@route("GET", "/api/admin/overview", ("staff", "admin"))
def overview(user, body):
    """Workload per doctor today (FR-033)."""
    p, t, today = policy(), now(), date.today().isoformat()
    close = datetime.combine(t.date(), time.fromisoformat(p["opd_end"]))
    out = []
    for d in rows("SELECT id FROM doctors ORDER BY name"):
        q = queue_state(d["id"], today)
        waiting = [e for e in q["entries"] if e["status"] in engine.WAITING]
        current = next((e for e in q["entries"] if e["status"] in ("called", "in_consultation")), None)
        etas = [parse(e["eta"]) for e in q["entries"] if e["eta"] and e["ahead"] is not None]
        clears = max(etas) + timedelta(minutes=q["avg_minutes"]) if etas else None
        # ponytail: fixed thresholds for congestion; make them policy values when admins ask
        level = ("over capacity" if clears and clears > close else "busy" if len(waiting) >= 8 else "normal")
        out.append({**q["doctor"], "waiting": len(waiting), "current_token": current and current["token"],
                    "avg_minutes": q["avg_minutes"], "clears_at": iso(clears), "congestion": level,
                    "completed": sum(e["status"] == "completed" for e in q["entries"]),
                    "skipped": sum(e["status"] == "skipped" for e in q["entries"])})
    return {"doctors": out, "updated_at": iso(t), "opd_end": p["opd_end"]}


@route("GET", "/api/admin/events", ("admin",))
def events(user, body):
    return {"events": rows("""SELECT e.*, u.name AS actor, d.name AS doctor, a.token FROM events e
                              LEFT JOIN users u ON u.id = e.actor_id LEFT JOIN doctors d ON d.id = e.doctor_id
                              LEFT JOIN appointments a ON a.id = e.appointment_id ORDER BY e.id DESC LIMIT 100""")}


@route("POST", "/api/admin/department", ("admin",))
def add_department(user, body):
    name = need(body, "name").strip()
    if row("SELECT 1 FROM departments WHERE name = ?", name):
        raise HTTPError(409, "That department already exists.")
    db.execute("INSERT INTO departments(name) VALUES(?)", (name,))
    log(user, "department_added", detail=name)
    return {"ok": True}


@route("POST", "/api/admin/doctor", ("admin",))
def add_doctor(user, body):
    """Creates the doctor and their sign-in together."""
    name, dep = need(body, "name").strip(), need(body, "department_id", int)
    username, password = need(body, "username").strip().lower(), need(body, "password")
    avg = float(body.get("avg_minutes") or 10)
    if not row("SELECT 1 FROM departments WHERE id = ?", dep):
        raise HTTPError(404, "Department not found.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken.")
    if len(password) < 6 or not 1 <= avg <= 120:
        raise HTTPError(400, "Password needs 6+ characters and average time must be 1 to 120 minutes.")
    doc_id = db.execute("INSERT INTO doctors(name, department_id, avg_minutes) VALUES(?,?,?)", (name, dep, avg)).lastrowid
    db.execute("INSERT INTO users(username, pw, role, name, doctor_id) VALUES(?,?,?,?,?)",
               (username, hash_pw(password), "doctor", name, doc_id))
    log(user, "doctor_added", doc_id, detail=name)
    return {"ok": True}


@route("POST", "/api/admin/staff", ("admin",))
def add_staff(user, body):
    name, username, password = need(body, "name").strip(), need(body, "username").strip().lower(), need(body, "password")
    role = body.get("role") or "staff"
    if role not in ("staff", "admin"):
        raise HTTPError(400, "Role must be staff or admin.")
    if row("SELECT 1 FROM users WHERE username = ?", username):
        raise HTTPError(409, "That username is taken.")
    if len(password) < 6:
        raise HTTPError(400, "Password must be at least 6 characters.")
    db.execute("INSERT INTO users(username, pw, role, name) VALUES(?,?,?,?)", (username, hash_pw(password), role, name))
    log(user, "user_added", detail=f"{username} ({role})")
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
        for k in ("grace_minutes", "alert_minutes"):
            if k in new and not 0 <= int(new[k]) <= 180:
                raise ValueError
    except ValueError:
        raise HTTPError(400, "Times must be HH:MM and minutes 0 to 180.")
    for k, v in new.items():
        db.execute("INSERT INTO policy VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
    log(user, "policy_changed", detail=json.dumps(new))
    return policy()


# ---------- HTTP plumbing ----------

class Handler(BaseHTTPRequestHandler):
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
        cookie = None
        try:
            if method == "POST":
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.loads(raw or b"{}")
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
            cookie = result.pop("_cookie", None)
            self.send_json(200, result, cookie)
        except HTTPError as e:
            self.send_json(e.status, {"error": e.message})
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Request body is not valid JSON."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "That conflicts with existing data. Refresh and try again."})
        except Exception:
            import traceback
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on the server. Nothing was saved."})

    def current_user(self):
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        token = jar["sid"].value if "sid" in jar else None
        if not token:
            return None
        s = row("SELECT u.*, s.created FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?", token)
        if not s or now() - parse(s["created"]) > timedelta(hours=SESSION_HOURS):
            return None
        return s

    def send_json(self, status, data, cookie=None):
        extra = {}
        if cookie is not None:
            extra["Set-Cookie"] = (f"sid={cookie}; HttpOnly; SameSite=Strict; Path=/"
                                   + ("" if cookie else "; Max-Age=0"))
        self.send(status, json.dumps(data).encode(), "application/json", extra)

    def send(self, status, payload, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


def init_db():
    db.executescript(SCHEMA)
    if row("SELECT 1 FROM users LIMIT 1"):
        return
    with db:
        for name in ("General Medicine", "Paediatrics", "Orthopaedics"):
            db.execute("INSERT INTO departments(name) VALUES(?)", (name,))
        seed = [("Dr. Rao", 1, 8, "dr.rao"), ("Dr. Iyer", 1, 12, "dr.iyer"),
                ("Dr. Khan", 2, 10, "dr.khan"), ("Dr. Sen", 3, 15, "dr.sen")]
        for name, dep, avg, username in seed:
            doc_id = db.execute("INSERT INTO doctors(name, department_id, avg_minutes) VALUES(?,?,?)", (name, dep, avg)).lastrowid
            db.execute("INSERT INTO users(username, pw, role, name, doctor_id) VALUES(?,?,?,?,?)",
                       (username, hash_pw("doctor123"), "doctor", name, doc_id))
        for username, pw, role, name in [("admin", "admin123", "admin", "OPD Admin"),
                                         ("staff", "staff123", "staff", "Front Desk"),
                                         ("patient", "patient123", "patient", "Demo Patient")]:
            db.execute("INSERT INTO users(username, pw, role, name) VALUES(?,?,?,?)", (username, hash_pw(pw), role, name))
    print("Seeded demo accounts: admin/admin123, staff/staff123, patient/patient123, dr.rao (and dr.iyer, dr.khan, dr.sen)/doctor123")


if __name__ == "__main__":
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Smart OPD running at http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
