# Smart OPD Queue and Appointment Management System

A web application for outpatient departments that manages appointments and the live queue, estimates when each patient will be seen, and updates that estimate as the day unfolds. It follows the project SRS (`Smart OPD Queue and Appointment SRS.pdf`), the data flow diagrams and the UML diagrams in this folder.

Version 1.1.0. Needs only Python 3.11 or newer: no packages to install.

## Run it

```
python3 app/server.py --demo        # local demo with sample departments, doctors and accounts
```

Open http://localhost:8000. Demo accounts:

| Role | Username | Password |
|---|---|---|
| Administrator | admin | admin123 |
| Front-desk staff | staff | staff123 |
| Developer / tester | tester | tester123 |
| Patient | patient | patient123 (or register a new one) |
| Doctors | dr.rao, dr.iyer, dr.khan, dr.sen | doctor123 |

Data is stored in `app/opd.db`. Delete it to start again.

**Upgrading from 1.0:** just start the new version. It saves a backup to `app/backups/` first, then upgrades the database in place (new columns, and a rebuilt appointments table that allows cancellations). 1.0 emergencies keep their priority.

## New interface (in progress)

A React frontend is being built from the Figma designs on the `react-migration` branch ([docs/FRONTEND_MIGRATION.md](docs/FRONTEND_MIGRATION.md)). While it is migrated it is served at http://localhost:8000/app/ and the current interface stays at `/`. Building it needs Node 20 or newer; running the server still needs only Python.

```
cd frontend && npm install && npm run build   # then start the server as above and open /app/
npm run dev                                    # development: http://localhost:5173/app/, API proxied to :8000
```

## Tests

```
python3 app/test_engine.py   # queue, ETA and alert rules
python3 app/test_sim.py      # simulation harness: reproducibility, isolation, reports
python3 app/test_api.py      # every role end to end on a throwaway server, plus a load check
python3 app/test_features.py # the 1.1 features, and an upgrade of a real 1.0 database
python3 app/test_ui.py       # browser checks for every role, legacy and React (optional: needs playwright-cli, skipped without it)
```

## Simulation

```
python3 app/simulate.py --scenario all --seeds 100
```

Runs synthetic OPD days through the same queue and ETA code as the live system and compares them with a fixed-token FIFO baseline. Reports (Markdown and JSON) go to `app/sim_results/`. Testers can also run simulations from their screen. The 100-seed report for this version is in [docs/simulation-report.md](docs/simulation-report.md). All results are simulated and do not show real-world effectiveness.

## What each role can do

- **Patient**: register with contact details, an alert channel and language (English or Hindi); book a department, doctor and date, for themselves or a family member; cancel or change an appointment; see the token, the estimated time (marked as an estimate, with when it was last updated) and how many patients are ahead; check in on arrival (self check-in opens a set time before the turn, optionally with the code shown at reception); choose how early the arrival alert comes; see alerts and whether they were sent; reset a forgotten password with a code; delete their data.
- **Doctor**: see their own queue; call the next eligible patient; mark a called patient who is not at the door as "not here" (they keep their place); start and complete consultations; skip a patient whose grace period has run out; record a break, a delay or unavailability (unavailability lasts for that day).
- **Front-desk staff**: see every doctor's workload and today's exceptions; give walk-in patients a token; find a patient or patient account by name, phone, username or token; reset a patient's password; check patients in; mark not here; skip; give emergency priority or a priority category (with a reason) and remove it; move one patient or a whole queue to a colleague in the same department; cancel; reinsert a skipped patient next as a policy exception; open the waiting-room display; follow alert delivery.
- **Administrator**: everything staff can see, plus departments, doctors (OPD days and own hours, daily limit, leave, learned consultation time, password reset), staff accounts and roles, queue policy (check-in window and code, booking window and limits, priority categories, data retention), the searchable audit log, analytics with measured ETA accuracy, CSV exports, backups and simulation reports.
- **Developer / tester**: run simulations and download reports. Testers cannot see or change live patient data.
- **Everyone** can change their own password from the header. Administrators reset staff passwords (Staff and policy) and doctor passwords (Edit doctor).

## Production setup

Start without `--demo`. On first run only an `admin` account is created. Its password comes from `OPD_ADMIN_PASSWORD`, or a random one is printed once.

| Variable | Default | Purpose |
|---|---|---|
| `OPD_HOST` / `OPD_PORT` | `127.0.0.1` / `8000` | Address to listen on |
| `OPD_DB` | `app/opd.db` | SQLite database file |
| `OPD_ADMIN_PASSWORD` | random | First admin password |
| `OPD_TLS_CERT`, `OPD_TLS_KEY` | none | Serve HTTPS directly and mark cookies Secure |
| `OPD_SMTP_HOST`, `OPD_SMTP_PORT`, `OPD_SMTP_USER`, `OPD_SMTP_PASSWORD`, `OPD_SMTP_FROM` | none | Email alerts |
| `OPD_SMS_WEBHOOK`, `OPD_SMS_TOKEN` | none | SMS alerts through an HTTP gateway (POST `{to, subject, body}`) |
| `OPD_SIM_DIR` | `app/sim_results` | Where simulation reports are saved |
| `OPD_TICK_SECONDS`, `OPD_DISPATCH_SECONDS` | `30`, `5` | How often arrival alerts are checked and sent |
| `OPD_BACKUP_DIR`, `OPD_BACKUP_KEEP` | `backups/` next to the database, `14` | Nightly backups and how many are kept |

Without an email or SMS provider, alerts are written to the server log and shown as "sent, delivery not confirmed". Patients always see their status in the app. Password reset codes go through the same provider, so without one patients reset their password at the desk. The Hindi alert texts in `app/server.py` should be checked by a native speaker before use.

The waiting-room display is a link (Staff and policy, or the front-desk panel) that works without signing in and shows tokens only. Treat the link like a key: anyone with it can see the token board.

Before real use, the SRS (Appendix E) requires decisions on hosting, the alert provider and its cost and consent, identity and authentication, hospital emergency and no-show policy, data retention and privacy, and expected volume. Put the server behind HTTPS (directly with the TLS variables or behind a reverse proxy), keep the disk encrypted, and back up the database regularly, for example `sqlite3 app/opd.db ".backup backup.db"`. The server uses local time.

## Code layout

| File | Purpose | DFD / UML |
|---|---|---|
| `app/engine.py` | Queue order, ETA calculation, who to call, skip and reinsertion rules. Pure functions. | Processes 3.2, 3.4, 4.3; class ETAService |
| `app/notify.py` | Alert rule (decision table 4) and provider adapters: log, SMTP, SMS webhook, mock | Process 5.0; NotificationProvider interface |
| `app/server.py` | HTTP API, SQLite storage, roles, notification worker | Processes 1.0 to 6.0; data stores D1 to D9 |
| `app/simulate.py` | Discrete-event simulation harness and reports | Process 7.0; data store D10 |
| `app/index.html` | Web interface for all roles | External entities' views |
| `frontend/` | React interface (in progress), built from the Figma designs | External entities' views |
| `app/test_*.py`, `app/test_ui.js`, `app/test_ui_react.js` | Automated checks | |
| `docs/TRACEABILITY.md` | Every SRS requirement mapped to code and tests | |
