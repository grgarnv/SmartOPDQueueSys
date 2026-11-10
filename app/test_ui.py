"""Browser checks (test_ui.js for the legacy UI, test_ui_react.js for /app/) against throwaway demo servers. Run: python3 app/test_ui.py

Optional: needs playwright-cli (npm install -g @playwright/cli) and its Chromium. Without it the
check is skipped, so the other suites keep working with Python alone.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import sqlite3
from datetime import date, datetime, timedelta

from test_api import TMP, Client, start_server

HERE = Path(__file__).parent


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("ui: skipped (playwright-cli is not installed)")
        return
    failed = run(cli, "test_ui.js", "legacy UI")
    if (HERE.parent / "frontend" / "dist" / "index.html").is_file():
        failed += run(cli, "test_ui_react.js", "React UI", prepare_react)
    else:
        print("ui (React): skipped (frontend not built: cd frontend && npm run build)")
    if failed:
        sys.exit(f"ui: {failed} failed")


def prepare_react(base, db):
    """Dr. Rao's queue for the React consultation checks, made through the API like a real day; one patient's
    missed turn is moved 11 minutes back in the database (as test_api.py does) so their grace period is over."""
    admin = Client(base).login("admin", "admin123")
    admin("/api/admin/policy", {"opd_start": "00:00", "opd_end": "23:59", "block_after_close": 0})
    staff = Client(base).login("staff", "staff123")
    for name in ("Asha Verma", "Bilal Khan", "Chitra Nair"):
        assert staff("/api/staff/walkin", {"name": name, "doctor_id": 1})[0] == 200
    s, booking = Client(base).login("patient", "patient123")("/api/book", {"doctor_id": 1, "day": date.today().isoformat()})
    assert s == 200, booking
    assert staff("/api/staff/walkin", {"name": "Esha Gill", "doctor_id": 1})[0] == 200
    con = sqlite3.connect(db)
    con.execute("UPDATE appointments SET due_at = ? WHERE id = ?",
                ((datetime.now() - timedelta(minutes=11)).isoformat(timespec="seconds"), booking["id"]))
    con.commit()
    # Front desk / queue monitor checks use Dr. Iyer (doctor 2), so they do not depend on the doctor checks above:
    # 001 Gita Rao, 002 Hari Das checked in; 003 Ira Skipped and 005 Rhea Again skipped; 004 Lal Late booked, turn
    # missed a minute ago (late within grace); 006 Tara Twice booked.
    for name in ("Gita Rao", "Hari Das"):
        assert staff("/api/staff/walkin", {"name": name, "doctor_id": 2})[0] == 200
    ids = {}
    for user, name, phone in (("ira.skipped", "Ira Skipped", "+91 90000 11111"), ("lal.late", "Lal Late", "+91 90000 22222"),
                              ("rhea.again", "Rhea Again", "+91 90000 33333"), ("tara.twice", "Tara Twice", "+91 90000 44444")):
        c = Client(base)
        assert c("/api/register", {"name": name, "username": user, "password": "longenough", "phone": phone})[0] == 200
        s, b = c("/api/book", {"doctor_id": 2, "day": date.today().isoformat()})
        assert s == 200, b
        ids[user] = b["id"]
    for user, minutes in (("ira.skipped", 11), ("rhea.again", 11), ("lal.late", 1)):
        con.execute("UPDATE appointments SET due_at = ? WHERE id = ?",
                    ((datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds"), ids[user]))
    con.commit()
    con.close()
    for user in ("ira.skipped", "rhea.again"):
        s, r = staff("/api/queue/action", {"action": "skip", "appointment_id": ids[user]})
        assert s == 200, r
    # Dr. Khan (doctor 3): Kiran Khan booked, turn passed 11 minutes ago, so the monitor can skip them (grace over)
    c = Client(base)
    assert c("/api/register", {"name": "Kiran Khan", "username": "kiran.khan", "password": "longenough", "phone": "+91 90000 55555"})[0] == 200
    s, b = c("/api/book", {"doctor_id": 3, "day": date.today().isoformat()})
    assert s == 200, b
    con = sqlite3.connect(db)
    con.execute("UPDATE appointments SET due_at = ? WHERE id = ?", ((datetime.now() - timedelta(minutes=11)).isoformat(timespec="seconds"), b["id"]))
    con.commit()
    con.close()
    # a family member (alerts go to the guardian; the desk cannot reset their password)
    assert Client(base).login("lal.late", "longenough")("/api/dependants", {"name": "Lila Late"})[0] == 200


def run(cli, name, label, prepare=None):
    """One browser script against its own throwaway demo server. Returns the number of failed checks."""
    db = f"{TMP}/{name}.db"
    proc, base = start_server(db)
    if prepare:
        prepare(base, db)
    script = Path(TMP) / name
    script.write_text((HERE / name).read_text().replace("__BASE__", base))
    session = ["-s=opd-ui-test"]
    try:
        subprocess.run([cli, *session, "open", "about:blank"], capture_output=True, check=True, timeout=60, cwd=TMP)
        result = subprocess.run([cli, *session, "run-code", f"--filename={script}"], capture_output=True, text=True, timeout=300, cwd=TMP)
    finally:
        subprocess.run([cli, *session, "close"], capture_output=True, timeout=60, cwd=TMP)  # cwd: the CLI writes its logs there
        proc.terminate()
        log = proc.communicate(timeout=5)[0]
    # the CLI prints Markdown sections; the script's return value is the JSON line under "### Result"
    sections = result.stdout.split("### ")
    found = next((s for s in sections if s.startswith("Result")), None)
    if found is None:
        sys.exit(f"ui ({label}): the browser checks stopped with an error:\n{next((s for s in sections if s.startswith('Error')), result.stdout + result.stderr)}")
    report = json.loads(found.splitlines()[1])
    print(report)
    failed = [line for line in report.splitlines() if line.startswith("FAIL")]
    passed = sum(line.startswith("PASS") for line in report.splitlines())
    assert "Traceback" not in log, log
    print(f"ui ({label}): {passed} passed, {len(failed)} failed")
    return len(failed)


if __name__ == "__main__":
    main()
