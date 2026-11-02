# Smart OPD Queue and Appointment Management System

A web application for outpatient departments that manages appointments and the live queue, estimates when each patient will be seen, and updates that estimate as the day unfolds. It follows the project SRS (`Smart OPD Queue and Appointment SRS.pdf`), the data flow diagrams and the UML diagrams in this folder.

Version 1.0.0. Needs only Python 3.11 or newer: no packages to install.

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

## Tests

```
python3 app/test_engine.py   # queue, ETA and alert rules
python3 app/test_sim.py      # simulation harness: reproducibility, isolation, reports
python3 app/test_api.py      # every role end to end on a throwaway server, plus a load check
```

## Simulation

```
python3 app/simulate.py --scenario all --seeds 100
```

Runs synthetic OPD days through the same queue and ETA code as the live system and compares them with a fixed-token FIFO baseline. Reports (Markdown and JSON) go to `app/sim_results/`. Testers can also run simulations from their screen. The 100-seed report for this version is in [docs/simulation-report.md](docs/simulation-report.md). All results are simulated and do not show real-world effectiveness.

## What each role can do

- **Patient**: register with contact details and an alert channel; book a department, doctor and date; see the token, the estimated time (marked as an estimate, with when it was last updated) and how many patients are ahead; check in on arrival; see alerts and whether they were sent.
- **Doctor**: see their own queue; call the next eligible patient; start and complete consultations; skip a patient whose grace period has run out; record a break, a delay or unavailability.
- **Front-desk staff**: see every doctor's workload and today's exceptions; find a patient by name, phone or token; check patients in; skip; give emergency priority (with a reason); reinsert a skipped patient next as a policy exception; follow alert delivery.
- **Administrator**: everything staff can see, plus departments, doctors, OPD days and leave, staff accounts and roles, queue policy, the audit log, CSV exports and simulation reports.
- **Developer / tester**: run simulations and download reports. Testers cannot see or change live patient data.

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

Without an email or SMS provider, alerts are written to the server log and shown as "sent, delivery not confirmed". Patients always see their status in the app.

Before real use, the SRS (Appendix E) requires decisions on hosting, the alert provider and its cost and consent, identity and authentication, hospital emergency and no-show policy, data retention and privacy, and expected volume. Put the server behind HTTPS (directly with the TLS variables or behind a reverse proxy), keep the disk encrypted, and back up the database regularly, for example `sqlite3 app/opd.db ".backup backup.db"`. The server uses local time.

## Code layout

| File | Purpose | DFD / UML |
|---|---|---|
| `app/engine.py` | Queue order, ETA calculation, who to call, skip and reinsertion rules. Pure functions. | Processes 3.2, 3.4, 4.3; class ETAService |
| `app/notify.py` | Alert rule (decision table 4) and provider adapters: log, SMTP, SMS webhook, mock | Process 5.0; NotificationProvider interface |
| `app/server.py` | HTTP API, SQLite storage, roles, notification worker | Processes 1.0 to 6.0; data stores D1 to D9 |
| `app/simulate.py` | Discrete-event simulation harness and reports | Process 7.0; data store D10 |
| `app/index.html` | Web interface for all roles | External entities' views |
| `app/test_*.py` | Automated checks | |
| `docs/TRACEABILITY.md` | Every SRS requirement mapped to code and tests | |
