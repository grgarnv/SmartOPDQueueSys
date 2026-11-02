# Smart OPD Queue and Appointment Management System

Initial working build (SRS phases 2 and 3): accounts and roles, departments and doctors, booking with tokens, check-in, live queue, dynamic ETA, doctor controls, no-show grace period, skip and reinsertion, emergency priority, workload view and audit log.

Needs only Python 3.11+. No packages to install.

```
python3 app/server.py          # http://localhost:8000  (optional port: python3 app/server.py 9000)
python3 app/test_engine.py     # queue and ETA checks
```

The database (`app/opd.db`) is created and seeded on first run. Delete it to start fresh.

| Role | Username | Password |
|---|---|---|
| Admin | admin | admin123 |
| Front-desk staff | staff | staff123 |
| Patient | patient | patient123 (or register a new one) |
| Doctors | dr.rao, dr.iyer, dr.khan, dr.sen | doctor123 |

Default policy: OPD 09:00–17:00, 10 min no-show grace, arrival alert 30 min before ETA. Admins can change these.

## Layout

- `app/engine.py`: queue order and ETA logic, pure functions with no I/O, reusable by the simulator
- `app/server.py`: HTTP API, SQLite storage, auth and role checks
- `app/index.html`: the web UI for patients, doctors, staff and admins
- `app/test_engine.py`: engine checks

## Not built yet

- Real SMS/email alerts: alerts show in the app only.
- Simulation harness (SRS phase 5).
- Per-date doctor schedules: availability is a same-day status.
