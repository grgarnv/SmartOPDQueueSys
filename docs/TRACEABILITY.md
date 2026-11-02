# Requirements traceability: Smart OPD 1.0.0

Each SRS requirement, where it is implemented and how it is verified. Status is **Met**, **Partly met** (with the gap stated) or **Deployment** (depends on choices the SRS leaves to the deploying hospital, Appendix E).

Test names: `engine` = app/test_engine.py, `sim` = app/test_sim.py, `api` = app/test_api.py (sections are commented in the file).

## Functional requirements

| ID | Requirement (short) | Implementation | Verified by | Status |
|---|---|---|---|---|
| FR-001 | Patient account or sign-in before booking | `register`, `login` in server.py; booking route requires the patient role | api: permissions, registration | Met |
| FR-002 | Authentication and role-based permissions | Session cookie (hashed token, 12 h), `route(..., roles)`, `can_operate` | api: permissions | Met |
| FR-003 | Collect only needed patient details | Name, phone or email, alert channel; `valid_contact`; `/api/profile` | api: registration rules | Met |
| FR-004 | Patients see only their own data; staff by role | Patient routes filter by `patient_id`; queue routes need staff roles | api: "patients cannot touch others' bookings" | Met |
| FR-005 | Choose department and doctor from available options | `/api/departments?day=` lists active doctors with `bookable` | api: leave and inactive doctors | Met |
| FR-006 | Block unavailable doctor, closed hours, invalid options | `book`: past date, `holds_opd` (active, working day, leave), unavailable today, OPD closed | api: booking, leave, working day, inactive | Met |
| FR-007 | Unique appointment reference and token, booking time, initial ETA | `book` inserts with `UNIQUE(doctor_id, day, token)` and returns ETA | api: booking (AC-001) | Met |
| FR-008 | Show doctor, department, date, token, status, ETA together | `appointment_view`; patient card in index.html | api: my-appointments fields | Met |
| FR-009 | No duplicate active appointments | `UNIQUE(patient_id, doctor_id, day)`; repeat returns the existing booking | api: `dup["existing"]` | Met |
| FR-010 | One authoritative queue per doctor and day | `appointments` table keyed by doctor and day; single write path `material()` | api: queue flow | Met |
| FR-011 | ETA from position, observed durations, availability, breaks, rules | `engine.compute_etas`, `engine.expected_minutes` (blended estimator) | engine: ETA tests; sim | Met |
| FR-012 | Recalculate ETA after every material event | `material()` calls `after_change()`; ETAs also computed fresh on every read | api: delay shifts ETA; engine | Met |
| FR-013 | All views show the same committed state | One `queue_state()` for every role | api: "views converge" | Met |
| FR-014 | ETA labelled as estimate with last-updated time | index.html patient card and queue header | Browser check | Met |
| FR-015 | Unavailable status instead of a fabricated time | `compute_etas(available=False)` returns None; UI explains why | engine; api: doctor unavailable | Met |
| FR-016 | Keep event history to reproduce ETAs | `events` table with queue version; `eta_snapshots` with cause and version | api: "ETA history stored" | Met |
| FR-017 | Arrival alert at threshold when a channel exists | `notify.alert_purposes`, `after_change`, ticker every 30 s | engine: decision table 4; api: arrival alert | Met |
| FR-018 | Alert on material ETA change | Same rule, `eta_change_minutes` policy (default 15) | engine: R4, R5 | Met |
| FR-019 | Record channel, purpose, time, outcome | `notifications` table | api: notifications | Met |
| FR-020 | Alert failure never blocks; show status | `dispatch_once` runs outside the request lock; status shown to patient and staff | api; sim notification_degradation | Met |
| FR-021 | No duplicate alerts unless retry policy | `event_key UNIQUE`; retries only via `notify_retries` | api: "no duplicate arrival alerts" | Met |
| FR-022 | Record check-in with timestamp | `/api/checkin` (patient or staff) | api: queue flow | Met |
| FR-023 | Call next, start, complete, skip | `queue_action`; `engine.next_to_call` (DT-3) | api: queue flow; engine | Met |
| FR-024 | Apply configured grace period before skipping | `engine.can_skip`, `engine.turn_cutoff`; `grace_minutes` policy | engine; api: "grace not over" | Met |
| FR-025 | Skipped patient kept with reason | Status `skipped`, `skip_reason`; never deleted | api; sim | Met |
| FR-026 | Reinsertion, default end of eligible queue | Late check-in uses `engine.end_position`; staff exception uses `front_position` | engine; api: order `[3, 1]` | Met |
| FR-027 | Log actor, time, action, reason for skips, reinsertions, overrides | `log()` on every action | api: audit checks | Met |
| FR-028 | Queue and ETA update after these actions | `material()` | api | Met |
| FR-029 | Staff can mark emergency under policy | `emergency` action for staff and admin only, reason required | api: emergency | Met |
| FR-030 | System never infers emergency | No code sets priority except the staff action | Code review | Met |
| FR-031 | Reorder and recalculate after emergency | Priority in `engine.order`; `material()` | api; sim emergency scenario | Met |
| FR-032 | Log who applied emergency; notify affected | Audit entry with actor and reason; affected patients get change alerts by rule | api: emergency audit row | Met |
| FR-033 | Admin workload view | `/api/admin/overview` | api: workload (AC-007) | Met |
| FR-034 | Less-loaded options within department | Doctor load per date in booking form plus a same-department suggestion | Browser check | Met |
| FR-035 | Suggestions advisory only | Suggestion only changes the form selection; patient books | Code review (AC-008) | Met |
| FR-036 | Configure availability, departments, hours, alert, grace, queue policies | Doctor update, leave, policy screen | api | Met |
| FR-037 | Create and update departments, doctors, schedules | `/api/admin/department(/update)`, `/api/admin/doctor(/update)`, `/api/admin/leave` | api | Met |
| FR-038 | Operational overview of queues, workload, delays, exceptions | Overview with exceptions and failed-alert count | api | Met |
| FR-039 | Audit log with actor, action, time, object, outcome | `events` table; admin audit tab | api | Met |
| FR-040 | Export simulation results and operational summaries | `/api/admin/export` (CSV); `/api/sim/report` (Markdown, JSON) | api: exports, report download | Met |

## Simulation requirements

| ID | Implementation | Verified by | Status |
|---|---|---|---|
| SIM-001 | `app/simulate.py`, synthetic patients only | sim: isolation | Met |
| SIM-002 | Scenario settings: arrivals, check-in behaviour, durations, no-shows, breaks, delays, emergencies, alert failures | sim | Met |
| SIM-003 | Seed recorded; `random.Random(scenario:seed:doctor)` | sim: same seed reproduces the same day | Met |
| SIM-004 | `SimQueue` adapter calls `engine.py`; `MockProvider`; no database import | sim: isolation | Met |
| SIM-005 | Fixed-token FIFO baseline on identical draws | sim: shared draws, baseline sends no alerts | Met |
| SIM-006 | normal, disruption, emergency, notification_degradation, stress | docs/simulation-report.md | Met |
| SIM-007 | 100 seeds per scenario by default; actual count reported; shortfall flagged | sim: "below target" | Met |
| SIM-008 | MAE, median error, share within 15 min, wait, revisions, throughput, no-shows, reinsertions, alerts, order violations, runtime | sim: report complete | Met |
| SIM-009 | Report has config, seeds, both policies, definitions, 95% intervals | docs/simulation-report.md | Met |
| SIM-010 | Every report labelled SIMULATED with a disclaimer | sim | Met |
| SIM-011 | Harness and engine are separate modules | sim: isolation | Met |

## Performance requirements

| ID | Evidence | Status |
|---|---|---|
| PR-001 | api load check: 720 requests from 40 concurrent threads, p95 about 10 ms on a laptop. Not yet tested at 500 concurrent sessions. | Partly met: rerun at the target load on the production host |
| PR-002 | ETAs computed on every read; screens refresh every 5 s | Met |
| PR-003 | Global lock plus queue version check; stale actions get 409 | Met (api: "stale version rejected") |
| PR-004 | 100 seeds x 5 scenarios x 2 policies in about 4 s | Met |
| PR-005 | Errors measured against simulated actual start times | Met (simulate.py `metrics`) |

## Non-functional requirements

| ID | Implementation | Status |
|---|---|---|
| NFR-001 | All protected routes require a session | Met |
| NFR-002 | Role checks per route and per queue | Met |
| NFR-003 | PBKDF2 password hashes, hashed session tokens, optional TLS, Secure cookies under TLS. Encryption at rest relies on the host's disk encryption. | Deployment |
| NFR-004 | Patient routes scoped to the signed-in patient | Met |
| NFR-005 | Simulation uses synthetic data only | Met |
| NFR-006 | Each request commits before replying, rolls back on error | Met |
| NFR-007 | Alert worker separate from requests; failures recorded, never treated as delivered | Met |
| NFR-008 | Unavailable ETA shown while the queue is kept | Met |
| NFR-009 | Serialised writes, unique constraints, version check | Met |
| NFR-010 | Token, status and ETA at the top of each card, plain language | Met |
| NFR-011 | Change alerts and screens say the time is an estimate | Met |
| NFR-012 | Responsive layout, labelled controls, visible focus, keyboard use | Met (formal accessibility audit still recommended) |
| NFR-013 | Every error says what failed and what to do | Met |
| NFR-014 | All policy values configurable in the admin screen | Met |
| NFR-015 | Unit, simulation and end-to-end tests | Met |
| NFR-016 | Version, config, seeds, scenario, time and metrics in every report | Met |
| NFR-017 | Same version, config and seed give the same trace hash | Met |
| NFR-018 | Definitions and limitations in every report | Met |
| NFR-019 | Interface, engine, notification adapters, storage and simulation in separate files | Met |
| NFR-020 | README covers setup, tests and settings | Met |

## Acceptance criteria (Appendix B)

| ID | Verified by | Result |
|---|---|---|
| AC-001 | api: booking | Pass |
| AC-002 | api: delay, unavailable, skip, reinsertion, emergency; engine | Pass |
| AC-003 | api: views converge | Pass |
| AC-004 | api: arrival alert; sim notification_degradation | Pass |
| AC-005 | api: grace period, skip, reinsertion | Pass |
| AC-006 | api: permissions | Pass |
| AC-007 | api: workload | Pass |
| AC-008 | Suggestion only pre-selects a doctor; no transfer code exists | Pass (review) |
| AC-009 | sim: reproducibility | Pass |
| AC-010 | sim: report; docs/simulation-report.md | Pass |
| AC-011 | 100 seeds per scenario; shortfall disclosed when fewer | Pass |
| AC-012 | Report wording | Pass |

## Simulation summary (100 seeds per scenario, docs/simulation-report.md)

Share of ETAs within 15 minutes of the simulated start, baseline vs Smart OPD: normal 88.4% vs 95.1% (target of 80% met), disruption 27.2% vs 72.5%, emergency 67.9% vs 91.8%, notification degradation 89.4% vs 91.6%, stress 26.6% vs 68.0%.

Trade-off found: on disruption and stress days Smart OPD completes slightly fewer consultations per hour (stress: 12.3 vs 13.4) and skips more patients, because patients who follow live ETAs arrive closer to their turn and the doctor waits more often. This should be reviewed with OPD stakeholders, for example by raising the arrival buffer. These are simulated outcomes only.

## Design decisions made during implementation

- **Missed turns.** When nobody waiting has checked in, only the patient at the head of the queue counts as having missed their turn. The grace period never starts before the time the patient was last told to come (`engine.turn_cutoff`). Simulation showed that without this, patients were skipped while running ahead of schedule.
- **Duration estimate.** The doctor's usual time is blended with the last 10 observed consultations (`engine.expected_minutes`). Compared with a plain rolling mean, simulation showed lower ETA error in every scenario and about 45% fewer alerts.
- **Data stores.** D1 to D9 are SQLite tables. D10 (simulation runs) is a folder of JSON and Markdown reports, so the harness never writes to the live database.
