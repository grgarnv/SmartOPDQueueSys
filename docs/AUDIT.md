# Audit log: Smart OPD 1.0.0, 2026-11-09

An end-to-end audit of the application, from its baseline through fixes to regression testing. The rollback point is the git tag `audit-baseline` (commit 35b04bb). Every test ran against throwaway databases in a temporary folder. `app/opd.db` was never opened.

## 1. Assessment

The product is in good shape. It has a small, readable architecture: pure queue and ETA logic in `engine.py`, a single write path through `material()`, one global lock that makes queue actions atomic, and parameterised SQL everywhere. All user text in the UI goes through `esc()`. Sessions are hashed, passwords use PBKDF2 and the CSP is strict. Tests cover every role. The audit found no critical defects and no data-loss paths. The defects found sat at the edges: input validation, account management, date handling for days other than today, and UI polling behaviour.

**Works well and was left unchanged:** queue ordering, ETA calculation and the blended estimator; no-show grace and reinsertion rules; emergency priority; optimistic concurrency (the `version` check); alert rules and the de-duplication keys; notification dispatch outside the lock; role checks (`route` roles plus `can_operate`); path-traversal protection on reports; the simulator; the security headers; the visual design.

## 2. Baseline (before any change)

| Check | Result |
|---|---|
| `python3 app/test_engine.py` | pass (10 tests) |
| `python3 app/test_sim.py` | pass (8 tests) |
| `python3 app/test_api.py` | pass (80 assert lines; load: 720 requests, 40 threads, p95 11 ms, 0 errors) |
| App starts in `--demo` and production mode | yes |
| Console on the sign-in page | 401 `/api/me` (expected while signed out), 404 `/favicon.ico` |

## 3. What was tested

**Browser (Playwright, Chromium):** sign-in, registration form, sign-out; patient booking, check-in, appointment cards and the profile section; doctor call next, start and complete, using mouse and keyboard; staff overview, patient lookup with check-in, the queue for any doctor, alerts; all five admin tabs (adding a department, editing a doctor, resetting a doctor's password, policy, staff accounts, audit, exports); tester simulation runs and the report list; the change-password dialog; mobile width (375 px) for sign-in, staff and tester; a fresh production install with no doctors.

**API probes (19 edge cases):** whitespace-only and overlong names, non-string JSON values, malformed numbers, invalid usernames, an empty set of working days, non-JSON and array bodies, formula injection into CSV, future and past-day ETAs, check-in of a completed visit, a negative Content-Length.

**Not exercised:** real SMTP or SMS delivery (no credentials; the log provider was used), TLS mode, load at the SRS target of 500 sessions, browsers other than Chromium.

## 4. Issues

Severity: C critical, H high, M medium, L low. Category: A defect, B usability, C technical, D subjective.

| ID | Sev | Cat | Area | Problem → expected | Status |
|---|---|---|---|---|---|
| AUD-01 | H | A | Accounts | No account could change its own password. On a production first run the server prints "Sign in and change it", which was impossible, and doctors' passwords could not be reset by anyone. **Repro:** sign in as admin and look for a way to change the password. | Fixed: `POST /api/password` plus a "Change password" dialog for every role; the admin's Edit doctor form takes a new password |
| AUD-02 | M | C | CSV export | Register a patient named `=HYPERLINK(...)` and book. The audit CSV then holds a live spreadsheet formula (CSV injection). | Fixed: cells starting with `= + - @` are prefixed with `'` |
| AUD-03 | M | C | HTTP | `Content-Length: -1` made the handler call `read(-1)` and hang until the client disconnected. Non-numeric values gave a 500. | Fixed: 400 |
| AUD-04 | M | A | ETA | A doctor marked "unavailable" today wiped the ETAs of all *future* bookings ("Time not available"). | Fixed: current status only affects today's queue |
| AUD-05 | M | A | Patient card | An unserved booking from yesterday showed "Expected around 23:16 on 2026-11-08", today's clock time with yesterday's date. | Fixed: no ETA for past days; the card says the date has passed |
| AUD-06 | M | B | All polled screens | The 5 s refresh rebuilt each panel. Keyboard focus jumped to `<body>` (a doctor tabbing to "Start" lost it) and an expanded simulation report collapsed again. | Fixed: `put()` redraws a panel only when its HTML changed |
| AUD-07 | M | B | Sign out | Signing out ended every session of the account. One desk signing out the shared `staff` account signed out every other desk. | Fixed: ends this session only; a password change ends the others |
| AUD-08 | M | A | Validation | Whitespace-only names were accepted for departments, patients, doctors and staff. A blank department sorted first and became the default, leaving an empty Doctor list. There was no length limit. | Fixed: `need()` rejects blank values and anything over 200 characters |
| AUD-09 | L | A | Validation | A non-numeric `version`, `avg_minutes` or `department_id`, or a numeric `phone`, gave "Something went wrong" (500). | Fixed: 400 with the field name (`opt()`, `text()`) |
| AUD-10 | L | A | Doctors | Unchecking every OPD day was silently ignored on Edit ("Saved.") and silently became Mon–Sat on Add. | Fixed: 400 |
| AUD-11 | L | A | Accounts | Doctor and staff usernames skipped the patient username rule (`<b> y` was accepted). | Fixed: same rule everywhere |
| AUD-12 | L | A | Header | "Sign out" showed on the sign-in page: `button { display:inline-block }` overrode `hidden`. | Fixed: `[hidden] { display:none !important }` |
| AUD-13 | L | B | Booking | Departments with no doctors were offered, and the first one could be preselected with an empty Doctor list. | Fixed: patients see only departments that have doctors |
| AUD-14 | L | A | Fresh install | Operations tab with no doctors: a failing `/api/queue` request every 5 s and a blank, unexplained panel. | Fixed: explanatory message, no request |
| AUD-15 | L | B | Lookup | After "Check in" from search results, the row still said Booked and kept the button. | Fixed: the row updates |
| AUD-16 | L | B | Accessibility | Form errors and confirmations were not announced to screen readers. | Fixed: `role="status"` on all 16 message areas |
| AUD-17 | L | A | Mobile | The tester's Results panel overflowed at 375 px (page scrolled sideways). | Fixed: `grid-template-columns: minmax(0, 1fr)` on `.appt` |
| AUD-18 | L | A | Visual | Appointment cards of unequal height spread their content vertically. | Fixed: `align-content: start`, as `section` already uses |
| AUD-19 | L | A | Check-in | Checking in a completed visit said "already checked in". | Fixed: "already complete" |
| AUD-20 | L | C | Performance | `/api/sim/runs` re-parsed every report on each 5 s poll **while holding the global request lock**: 101 ms with 50 reports, during which booking and queue requests waited. | Fixed: cached by file modification time, 2.7 ms |
| AUD-21 | L | C | Console | `/favicon.ico` 404 on every page load. | Fixed: 204 (a `data:` icon would need the CSP loosened) |
| AUD-22 | M | — | Booking | Patients cannot cancel a booking. Not in the SRS FR list. Needs a new appointment status, which means changing the `CHECK` constraint on existing databases (a schema migration). | **Needs your approval**, not started |
| AUD-23 | L | C | Login | The lockout is per username, so anyone can lock a known account (such as `admin`) for 5 minutes. `failed_logins` grows without bound. | Documented: standard trade-off. Consider IP-based limiting at the reverse proxy |
| AUD-24 | L | C | Login | Response timing shows whether a username exists. | Won't fix: registration already says "That username is taken" |
| AUD-25 | L | B | Doctor status | "Unavailable" stays set into the next day until someone presses Available. Next morning, today's bookings are blocked. | Documented: hospital policy decision (reset daily or not) |
| AUD-26 | L | B | Booking | After OPD closes, today's doctors still look bookable; booking returns a clear 409 "OPD has closed". | Documented |
| AUD-27 | — | C | Deployment | The `Secure` cookie flag is set only when TLS terminates in this process, not behind a TLS reverse proxy. | Documented (NFR-003 is already "Deployment") |
| AUD-28 | L | C | Accounts | Change password has no attempt limit (it needs a valid session). | Documented |
| AUD-29 | — | D | UI | `prompt()` for reasons; tabs without arrow-key navigation; registration defaults to SMS, so an email-only user must change the channel (the error message says so). | Subjective, not changed |

## 5. Changes

| File | Change |
|---|---|
| `app/server.py` | `need()` blank and length checks; new `opt()`, `text()`, `valid_username()`; `/api/password`; logout ends this session only; ETA availability limited to today and later days; check-in message; doctor password reset; working-days handling; CSV cell guard; cached report summaries; Content-Length validation; favicon 204 |
| `app/index.html` | `[hidden]` rule; `put()` for polled panels; change-password dialog; doctor password field; `.appt` grid fixes; departments filter; past-date card; no-doctors message; lookup row update; `role="status"` on messages |
| `app/test_api.py` | New `audit_fixes()` section (23 asserts) covering AUD-01 to AUD-11 and AUD-19 |
| `README.md` | One line on password changes |

No schema changes, no new dependencies and no removed features.

## 6. Results after the changes

| Check | Result |
|---|---|
| `test_engine.py` | pass, 10/10 |
| `test_sim.py` | pass, 8/8 |
| `test_api.py` | pass, 103 assert lines (80 existing, unchanged, + 23 new); load p95 12 ms (baseline 11 ms), 0 errors |
| New API checks run against the baseline server | fail at the first new check, as expected |
| Browser regression (19 checks) | 19 pass, 0 fail |
| API edge-case probes (19) | 19 behave as expected; 0 server tracebacks (baseline: 4 tracebacks, 1 hung handler) |
| `/api/sim/runs`, 50 reports | 101 ms → 2.7 ms (repeat polls) |

**Regressions during the work:** (1) the first favicon fix (`<link rel="icon" href="data:,">`) was blocked by the CSP, so it moved to a server-side 204; (2) the browser run found the tester-panel overflow (AUD-17) and the card spacing (AUD-18). Both were already in the baseline and are now fixed. None remain open.

## 7. Needs manual checking

- Email and SMS delivery with real provider credentials.
- HTTPS mode (`OPD_TLS_CERT` / `OPD_TLS_KEY`) and the `Secure` cookie.
- A screen reader pass (VoiceOver or NVDA) on the queue and booking screens.
- Safari and Firefox (only Chromium was automated).
- Load at the SRS target of 500 concurrent sessions (PR-001, already "Partly met").

---

# Part 2: features and model gaps, 2026-11-09 to 2026-11-10 (version 1.1.0)

All 26 suggested items were implemented on request ("do all"). That request also approved the database migration needed by items F-10, F-11 and F-14 (AUD-22 above is now done as F-10). The F-numbers match docs/TRACEABILITY.md, "Additions in 1.1.0".

## What was built

| ID | Gap or feature | What changed |
|---|---|---|
| F-01 | A called patient who was not at the door blocked "Call next" for good | "Not here": they lose check-in and keep their place; a called patient's grace period starts |
| F-02 | Unserved bookings stayed "booked" forever | Earlier days close automatically ("not seen: OPD day closed"); a consultation left open is completed without an end time, so it never skews averages |
| F-03 | Leave did not tell anyone | Patients booked that day get an alert straight away |
| F-04 | No limit on a doctor's day | Optional daily cap; patient bookings refused once the queue would run past closing (policy `block_after_close`); the desk can still add a walk-in, with a warning |
| F-05 | "Unavailable" carried into the next day | It lasts for the day it was set |
| F-06 | Patients could check in from home | Self check-in opens `checkin_minutes` before the ETA (default 60); optional daily 6-digit code shown on the reception display. The desk can always check someone in |
| F-07 | One account could book without limit | Booking window (default 14 days) and upcoming bookings per patient (default 3) |
| F-08 | Priorities could not be undone | "Remove priority", reason required and logged |
| F-09 | Everyone needed an account | Walk-in at the desk: record found by exact name and phone, or created; token issued already checked in |
| F-10 | No cancel or reschedule | Cancel (patient or desk; the desk's cancellations alert the patient) and atomic reschedule. Rebooking a cancelled slot reuses the row with a new token |
| F-11 | One patient per account | Family members; their alerts go to the guardian's channel and language |
| F-12 | No waiting-room screen | `/?display=<key>`: tokens only, no names, no staff session left on a public screen |
| F-13 | No way to move patients | Move one, or all waiting, to an available colleague in the same department; patient alerted |
| F-14 | One set of hours for every doctor | Optional per-doctor OPD hours, used for ETAs, closing and capacity |
| F-15 | Only "emergency" | Admin-defined categories (default: Senior citizen, Pregnant, Disability), ranked after emergencies |
| F-16 | Forgotten passwords were a dead end | One-time code through the account's alert channel (single use, 15 minutes, 5 tries, neutral reply), or a reset at the desk |
| F-17 | ETA accuracy only simulated | Measured: the ETA held at check-in vs the actual start |
| F-18 | Usual time typed in by hand | Learned: median of the last 28 days once 10 visits exist |
| F-19 | No analytics | Per-doctor and total: booked, seen, not seen, cancelled, waits, consult time, throughput, ETA accuracy, busiest hours chart; CSV |
| F-20 | English only | Alert language per patient: English or Hindi |
| F-21 | One alert lead time for all | Each patient can set their own (5 to 180 minutes) |
| F-22 | Audit log: latest 200 only | Search, action and date filters, "Load older" |
| F-23 | 5-second polling | Server-sent events: screens refresh as soon as anything changes; polling stays as the fallback |
| F-24 | No retention or erasure | Retention policy (default 0 = keep everything), applied on save and nightly; "Delete my data" anonymises the account and family, cancels upcoming visits |
| F-25 | No backups | Nightly backup (14 kept), "Back up now", and a backup before any schema upgrade |
| F-26 | Browser checks lived outside the repo | app/test_ui.py and app/test_ui.js (skipped when playwright-cli is missing) |

## Schema change and upgrade

New columns on `users` and `doctors`; `appointments` is rebuilt (SQLite cannot change a CHECK constraint) to allow `cancelled` and to add `priority_label` and `cancelled_at`. On first start of 1.1, `migrate()` saves `backups/opd-<time>-pre-upgrade.db`, then rebuilds in one transaction and runs a foreign-key check before committing. 1.0 emergencies (priority 1) become priority 2 with the label "emergency". **Verified** by `test_features.py`: it builds a database with the real 1.0 code (commit 35b04bb), upgrades it, and checks the data, new statuses, new columns, the backup and foreign keys. `app/opd.db` itself was not opened; it upgrades the first time you start 1.1.

## Behaviour changes to be aware of

These follow from the features and are all policy settings an admin can change:
- Patients can self check-in only from 60 minutes before their ETA; the desk can check anyone in at any time.
- Patients can book up to 14 days ahead and hold up to 3 upcoming appointments per person.
- Patient bookings are refused once a doctor's queue is projected to run past closing; turn `block_after_close` off to allow overflow.
- A doctor marked "unavailable" is available again the next day without anyone resetting it.

## Tests (final run)

| Suite | Result |
|---|---|
| test_engine.py | pass, 11/11 (1 new: learned prior) |
| test_sim.py | pass, 8/8 |
| test_api.py | pass, 103 asserts; load p95 15 ms (11–12 ms before part 2), 0 errors |
| test_features.py | pass, 115 asserts, including the 1.0 upgrade |
| test_ui.py (Chromium) | pass, 36/36 browser checks, 0 console errors |

The one existing test line changed in part 2: test_api.py's setup now also sets `block_after_close: 0`, because its bookings run at any hour against a 23:59 close (the run at 23:45 correctly hit the new rule). The new rule is tested deterministically in test_features.py.

**Regressions found and fixed during part 2:**
- The admin Reports tab scrolled sideways at phone width. The analytics table pushed its section wider, and the long backup path did not wrap. Fixed with `section { grid-template-columns: minmax(0, 1fr) }` and `overflow-wrap: break-word` on `body`.
- Browser-test harness issues, not app defects: native dialogs are held by playwright-cli, `selectOption` takes no regex, and a locator matched rows in several tables.

**Performance:** load p95 went from 11–12 ms to 15 ms. The department list now checks each doctor's capacity. This is still far inside the 2 s budget.

## Limitations and follow-ups

- **Hindi** alert texts need review by a native speaker before use.
- **Pick lists** for Priority, Move and Move all use the browser's numbered `prompt()`, matching the existing reason prompts. A proper dropdown would be nicer (subjective; not changed).
- **Display key** and the daily check-in code come from one server secret (the `_secret` row in `policy`). To revoke a leaked display link, delete that row and restart; this also changes the check-in code.
- **Live updates** hold one server thread per open screen, which suits one OPD. A reverse proxy in front must not buffer `/api/stream`.
- **Walk-in matching** finds an existing record only on exact name and phone (case-insensitive). Anything else creates a new record. This is deliberate, so two people sharing a phone are never merged.
- **Moving patients** is allowed only within a department. A moved patient joins the end of the colleague's queue.
- **Retention** deletes visits, their ETA history and alerts, and audit events older than the limit. Patient accounts stay until the patient deletes them.
- **Not tested with real providers:** SMS or email delivery of reset codes. Without a provider, codes go to the server log, so patients use the desk reset instead.
- **Not tested:** Safari and Firefox, HTTPS together with live updates, and load at 500 sessions.
- **Simulation report:** docs/simulation-report.md still says 1.0.0. The simulator does not use the learned prior or any 1.1 feature, so its results are unchanged and were not regenerated.
