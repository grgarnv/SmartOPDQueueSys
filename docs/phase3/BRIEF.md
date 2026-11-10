# SmartOPD React migration: Phase 3 brief

Written for whoever builds milestones 3B to 3E (Patient, Emergency, Waiting room, Admin). 3A (Front desk and Queue monitor) is done and committed.

**Cost note from the user:** do NOT use multi-agent Workflow runs for the remaining milestones (3A used 90 agents and ~5.4M tokens). Build each milestone in one plain session; if a review is wanted, run one `/code-review` at low or medium effort.
**Stop rule:** do not start the next milestone without being asked.


Repo: /Users/arnav/Desktop/Projects/SmartOPDQueueSys (git branch `react-migration`; never switch to `main`, never push, never commit — the lead commits).
Scratchpad: docs/phase3/ (call it SCRATCH below; per-frame outlines are in docs/phase3/figma-outlines/, specs in docs/phase3/specs/).

## 1. Non-negotiable rules
- Python backend (app/server.py, app/engine.py) and SQLite stay the source of truth. Do NOT change the schema, add business rules, change permissions, add endpoints for new capabilities, or rewrite backend logic. If something seems to need a backend change, report it instead of doing it.
- Never invent data. A Figma element whose data the backend does not provide is omitted or adapted (say which, and why, in a code comment near the component). No mock data, no placeholder patients, no fake numbers.
- The frontend never re-implements queue logic. Order, next patient, ETAs, grace periods, can_skip, permissions are the server's. Every queue action sends the `version` of the queue it was taken from; the screen then shows the server's reply. Refusals show the server's message.
- Don't remove existing functionality: every workflow the legacy UI (app/index.html) offers to a role must exist in the React UI for that role (docs/FRONTEND_MIGRATION.md §1.5 is the checklist).
- Legacy UI stays at `/` untouched; React lives at `/app/`. Do not edit app/index.html. Do not edit app/test_ui.js (legacy suite).
- No new dependencies unless truly unavoidable (none expected). No Tailwind.
- Late vs missed (user's product decision, must be visible in the UI):
  A. Late within grace (`turn_missed && !can_skip`, status booked): keeps original place; can check in (status → checked_in, same place).
  B. Skipped then arrives (status `skipped`, same day): visit stays on record; check-in puts them at the END of the queue (server does this); staff may "Reinsert next" (`reinsert_front`) only with a written reason (server requires it; audit logged).
  C. Never arrives (day passed, status skipped or booked/never checked in): show "Missed" in patient history; never modify it. "Rebooking assistance" card → "Book a new appointment" opens the normal booking flow prefilled with the old department and doctor, and creates a NEW appointment via POST /api/book. Never use /api/reschedule for a missed appointment. No automatic rescheduling, no new notifications.

## 2. Frontend architecture (reuse, don't duplicate)
- frontend/src/api/client.ts (api<T>(path, body?) — legacy api() contract; ApiError{status}), api/types.ts (add response types here as needed; read server.py for exact shapes).
- frontend/src/lib/useLive.ts (useLive(fetcher, deps) → {data,error,refresh,set}; shared SSE + 5s/30s polling; useStreamLive, useLastSync), lib/useFormAction.ts (form submit → message), lib/format.ts (hhmm, clock 12-hour, longDate, today, minutesBetween, tokenText 3-digit, ROLE_LABEL, LANGS, CHANNELS).
- frontend/src/design/: tokens.css (SmartOPD/* colours, type, spacing, radii), ui.tsx (Button, buttonClass, TextButton, Status(tone), TextField, SelectField, Panel, EmptyState, LoadingState, ErrorState, Callout, Message, Brand, Overline), Dialog.tsx (sizes sm 560 / md 600 / lg 760; onSubmit makes body+footer a form). Extend these rather than creating look-alikes. If a new shared component is needed by 2+ screens (e.g. a metric strip, data table, segmented tabs), put it in design/ and use it everywhere.
- frontend/src/features/queue/: useQueue(doctorId?) (act/setStatus with version + server reply; failure state), present.ts (display-only mapping of server fields: isWaiting, isLate, isCurrent, entryStatus, rowDetail, entryDetail, etaText, doctorStatus). Staff screens must use useQueue(doctorId) — extend its QueueAction union for staff actions (check-in is POST /api/checkin, cancel is POST /api/cancel; they return appointment views, not queue_state — refresh after them).
- frontend/src/features/consultation/QueueTable.tsx (rows from Figma "Upcoming queue"; supports an actions column) and dialogs.tsx (NoShowDialog, NotHereDialog, PauseDialog, AvailabilityDialog, SkippedLateDialog, FullQueueDialog, FailureDialog). Reuse/generalise them for staff screens instead of copying; if you move a component to a shared place, update imports.
- frontend/src/layout/AppShell.tsx (sidebar + bar; NAV is role-aware; Icon.tsx uses Figma SVGs as masks), routes.tsx (desk screens under the shell; /patient and /simulations currently `<NotMigrated bare>`; /design-system public).
- CSS Modules per feature; tokens via var(--…); comments cite Figma node ids for measured values. Responsive rules (Figma frame 07): ≥1280 full layout; 768–1279 compact nav / stacked; <768 one task per view, no sideways scroll.
- Accessibility: real buttons/links, labels on every field, named regions (Panel gets aria-labelledby from its title), dialogs via Dialog, keyboard reachable, status text never colour-only.

## 3. Figma (visual source of truth) — MCP is rate-limited; use these instead
- Per-frame outlines: docs/phase3/figma-outlines/<id>_<slug>.txt — every node with abs(x,y) from the frame's top-left, rel(x,y) from its parent, size and (for text) the literal text. Workspace starts at abs (256,104) on 1440×1000 frames (sidebar 224 + 32).
- Font size from a text node's height: height ≈ size × 1.45 (Inter, line-height 1.45): 15→10px, 16→11, 17→12, 19→13, 20→14, 22→15, 23→16, 25→17, 26→18, 28→19, 30→21, 33→23, 35→24, 39→27, 41→28, 42→29, 46→32. Weights/colours: follow the same element kind in frames already implemented (titles/values semibold, labels medium, captions regular; status pills, buttons, inputs, panels exactly as in ui.module.css), and the token names.
- Real Figma values already captured (use as ground truth for shared elements): frame 01/07 sidebar, bar, buttons (44px, radius 7), Status pills, Input (label 12 medium, 44px, #D1DBD9 border, radius 6), panels (white, radius 8/9, 24 inset), dialogs (radius 12, 28 inset, 23px title, 44px close, divider + footer Cancel-left / primary-right), Up next table rows (58px + 1px rule, columns 67/…/148/62).
- Figma PNG exports (all 54 frames, 1x; file names = Figma frame names, '?' and ':' replaced by '_') are at frontend/src/design/figma-exports/ . They ARE the visual source of truth: read the PNG for your frame, build to match it, and compare your screenshots against it at the same size. Never import them into the app.
- Frame ↔ route map:
  - Front desk `/app/front-desk` (staff, admin): 02 (2:25), 21 Registration saved (4:3942), 22 Appointment checked in (4:4081); dialogs Patient checked in 4:2134, Appointment found 4:2227, Appointment token issued 4:4219, Token print preview 4:4481, Appointment token print preview 4:4490 (Patient history 4:2213: no backend → omit).
  - Queue monitor `/app/queue-monitor` (staff, admin): 04 (2:33); full queue dialog 4:3874; Skipped & late 4:2152.
  - Emergency `/app/emergency` (staff, admin): 03 (2:29), 13 (4:1552) for the result state; dialog Approve priority override 4:2114.
  - Patient `/app/patient` (patient, mobile-first 390×844): 06 (2:819), 23 (4:4235).
  - Waiting room `/app/display?key=…` (public, no sign-in): 08 (2:848).
  - Admin `/app/admin/*` (admin): 05 (2:37) with tabs Overview, Departments, Doctors & staff, OPD sessions, Configuration; dialogs Manage OPD session 4:2246, Departments 4:2277, Doctors & staff 4:2307, Queue configuration 4:2337, Changes saved 4:2363, Configure department 4:3805, Staff access & assignment 4:3827, Invite a team member 4:3851, Daily operations report 4:4498. Legacy admin features with no Figma frame (audit log, alert log, analytics/CSV, exports, backups, simulation reports) get extra tabs in the same style. Tester `/app/simulations`: no frame; design-system components.

## 4. Backend facts (verify in app/server.py before relying on them)
- Roles: patient, doctor, staff, admin, tester. No nurse role. QUEUE_ACTIONS (server.py ~line 943): call_next/skip/not_present: doctor,staff; start/complete: doctor; emergency/priority/remove_priority/reinsert_front/transfer/transfer_all: staff,admin. Staff screens act on a doctor via doctor_id / appointment_id.
- Reasons: emergency, remove_priority, reinsert_front REQUIRE a reason; skip/not_present/cancel optional. Priority categories come from policy `priority_categories` (comma list; GET /api/admin/policy is staff+admin). Emergency is always above categories.
- /api/staff/walkin {name, phone?, lang?, doctor_id} or {patient_id, doctor_id} → creates a checked-in visit, returns token, username, warning, existing. /api/lookup?q= (staff/admin) → {results: today's visits, patients: accounts}. /api/checkin (patient/staff/admin; patient self check-in has window + optional code). /api/cancel {appointment_id, reason?}. /api/staff/patient-password.
- /api/admin/overview (staff/admin): doctors with status, waiting, current, avg, hours, clears_at, completed/skipped, congestion; today's exceptions (audit-like events incl. emergency/priority/reinsert/skip); failed_alerts. /api/admin/notifications (staff/admin). /api/admin/events (admin only, filters q/action/day/before). /api/admin/analytics?from&to (admin): per doctor booked/seen/not_seen/cancelled/avg_wait/avg_consult/seen_per_hour/eta_mae/eta_within_15, totals, by_hour. /api/display?key= (public): doctors with now, next[], waiting, status, break_until; checkin_code when required.
- Patient: /api/departments?day= (doctors with bookable/full/waiting/clears_at), /api/book {doctor_id, day, patient_id?} (returns appointment; existing=true if already booked), /api/reschedule (cancel+rebook, upcoming only), /api/cancel, /api/my-appointments (appointments with eta, ahead, updated_at, notifications, checkin_opens_at, checkin_code_required, arrival_alert, doctor{name,department,holds_opd}), /api/checkin {appointment_id, code?}, /api/profile, /api/dependants(+/remove), /api/delete-account.

## 5. Verification
- Build: `cd frontend && npm run build` (tsc strict + vite). Must be clean.
- Browser suites: `cd app && python3 test_ui.py` runs legacy (36 checks) + React (app/test_ui_react.js, prepared by `prepare_react` in app/test_ui.py). To run only the React suite:
  `cd app && python3 -c "import shutil,test_ui; test_ui.run(shutil.which('playwright-cli'),'test_ui_react.js','React UI',test_ui.prepare_react)"`
  Only ONE agent may run browser tests at a time (fixed playwright session name). Add checks to test_ui_react.js for every new workflow (role/label selectors, no CSS-class selectors); extend prepare_react in test_ui.py if you need seeded data — keep existing checks passing. Backend suites: `cd app && for t in test_engine test_sim test_api test_features; do python3 $t.py | tail -1; done`.
- Screenshots: start your own server `OPD_DB=SCRATCH/shots/<name>.db OPD_PORT=<unique port 8800–8899> python3 app/server.py --demo` (seed via API as prepare_react does), drive it with `playwright-cli -s=<unique session> open about:blank` + `run-code --filename=<script>` (script form: `async page => { ... }`, no URL global), save PNGs under SCRATCH/shots/<milestone>/, then stop the server (`pkill -f "OPD_PORT=<port>"` won't match — kill by PID you recorded) and close the session.
