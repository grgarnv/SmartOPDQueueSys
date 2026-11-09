# Frontend migration: vanilla HTML to React + TypeScript + Vite

Status: audit and architecture approved; foundation (project setup, design system, API client, authentication) done on the `react-migration` branch. See §5 for the phase log.

Figma source: `gruJF3iBGPiCUl8GbMBqAJ`, page `0:1` (26 screens, 27 dialogs, one foundations frame `2:41`).

## 1. Audit of the current application

### 1.1 Shape

| Part | What it is |
|---|---|
| `app/server.py` (1,881 lines) | Python standard library `ThreadingHTTPServer`, SQLite, cookie sessions, JSON API, server-sent events, notification worker, nightly backups. One global lock serialises requests. |
| `app/index.html` (869 lines) | All UI: inline CSS (CSS variables on `:root`) and inline JS. One view function per role, string templates, `innerHTML`. No build step, no dependencies. |
| `app/engine.py`, `notify.py`, `simulate.py` | Queue order, ETA, alert rules, simulation. Not touched by the frontend migration. |
| Tests | `test_engine.py`, `test_sim.py`, `test_api.py`, `test_features.py` exercise the backend only. `test_ui.py` drives `test_ui.js` (33 browser checks) through `playwright-cli` against a throwaway server. |

### 1.2 How the browser talks to the server

- **Transport:** `fetch` with JSON. GET for reads (query string), POST with a JSON body for writes. Errors come back as `{"error": "..."}` with a 4xx/5xx status, and the UI shows the message as-is.
- **Auth:** `POST /api/login` sets an `sid` cookie (`HttpOnly; SameSite=Strict; Path=/`, plus `Secure` under TLS). Sessions last 12 hours. A 401 from any call sends the UI back to sign-in. Role checks happen on the server for every route.
- **Live updates:** `GET /api/stream` is a server-sent events (SSE) stream that sends one message per committed change. The UI debounces it by 300 ms and refetches. Fallback: poll every 5 s while the stream is down, and every 30 s regardless so the ETAs, which change with the clock, stay fresh.
- **Optimistic concurrency:** `/api/queue/action` takes the `version` from the last `/api/queue` read. A stale version is rejected, so two desks can't act on the same queue at once.
- **Downloads:** CSV exports and simulation reports are plain links (`/api/admin/export?...`, `/api/sim/report?...`) that return `Content-Disposition: attachment`.
- **Security headers:** strict CSP (`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'`), `X-Frame-Options: DENY` and `Cache-Control: no-store` on every response. Because of the CSP, fonts and icons must come from our own origin, not a CDN.

### 1.3 Pages the server serves

| Path | Serves |
|---|---|
| `/`, `/index.html` | `app/index.html` |
| `/?display=KEY` | The same file, which switches to the waiting-room board (no sign-in). This link is printed and shared, so it must keep working. |
| `/favicon.ico` | 204 |
| Anything else that is not under `/api/` | 404 (there is no static file serving yet) |

### 1.4 API routes (46, all kept unchanged)

| Area | Routes (roles) |
|---|---|
| Public | `GET /api/health`, `POST /api/register`, `POST /api/login`, `POST /api/password/forgot`, `POST /api/password/reset`, `GET /api/display?key=` |
| Any signed-in user | `GET /api/me`, `POST /api/logout`, `POST /api/password`, `GET /api/departments[?day=]`, `GET /api/stream` |
| Patient | `POST /api/profile`, `/api/dependants`, `/api/dependants/remove`, `/api/delete-account`, `/api/book`, `/api/reschedule`; `GET /api/my-appointments` |
| Patient, staff, admin | `POST /api/cancel`, `POST /api/checkin` |
| Doctor, staff, admin | `GET /api/queue[?doctor_id=]`, `POST /api/queue/action`, `POST /api/doctor/status` |
| Staff, admin | `GET /api/lookup?q=`, `POST /api/staff/walkin`, `POST /api/staff/patient-password`, `GET /api/admin/overview`, `GET /api/admin/notifications`, `GET /api/admin/policy` |
| Admin | `GET /api/admin/events`, `/api/admin/doctors`, `/api/admin/users`, `/api/admin/export`, `/api/admin/analytics`, `/api/admin/backups`; `POST /api/admin/department`, `/department/update`, `/doctor`, `/doctor/update`, `/leave`, `/staff`, `/user/update`, `/policy`, `/backup` |
| Tester (runs also visible to admin) | `POST /api/sim/run`; `GET /api/sim/runs`, `/api/sim/report` |

`/api/queue/action` actions and who may use them (the server enforces this):

| Action | Roles |
|---|---|
| `call_next`, `skip`, `not_present` | doctor, staff |
| `start`, `complete` | doctor |
| `emergency`, `priority`, `remove_priority`, `reinsert_front`, `transfer`, `transfer_all` | staff, admin |

### 1.5 Workflows that must be preserved (the regression contract)

**Everyone**
- Sign in, sign out, and change their own password (this signs out their other sessions).
- Reset a forgotten password with a code. The reply is the same whether or not the account exists.
- When a session expires, the user is sent back to sign-in with a notice.

**Patient**
- Register with phone or email, an alert channel and an alert language.
- Book by date, then department, then doctor. A doctor who is full or has no OPD that day can't be chosen. Each doctor shows how many are booked and when the queue clears. A doctor with a shorter queue in the same department is suggested; the patient decides.
- Book for a family member.
- Reschedule: the booking form switches into "Move appointment" mode.
- Cancel, with confirmation.
- Self check-in once the window opens, with the reception code when policy requires it.
- Live ETA, "N ahead" and "last updated", always labelled as an estimate.
- An alert banner when their turn is near and when they've been called.
- Missed-turn messaging.
- The list of alerts and whether each was delivered.
- Contact details, alert channel, language and alert lead time.
- Add or remove family members.
- Delete their data, with password and confirmation.

**Doctor**
- Their own queue.
- Call next, Start, Complete.
- Not here (keeps the place), Skip (only once `can_skip` is true; reason optional).
- Set their status: Available, Break 15 min, Running 10 min late, Unavailable.
- Focus and selection survive live refreshes.
- Enter on a focused button starts the consultation.

**Front-desk staff**
- Workload overview: status, waiting, current token, average consult, hours, clear time, done/skipped, congestion.
- Today's exceptions.
- Walk-in token for a new or existing patient account.
- Find a patient by name, phone, username or token: check them in, open their queue, give a walk-in token, reset their password.
- Pick any doctor's queue and act on it: check in, Not here, Skip, Emergency (reason required), Priority category, Remove priority (reason), Move to a colleague in the same department, Move all waiting, Cancel (reason), Reinsert next (reason).
- Set doctor status.
- Waiting-room display link and today's check-in code.
- Patient alert delivery log.

**Administrator**
- Everything staff can do, under Operations.
- Doctors: add and edit (department, usual consult time, OPD days, own hours, daily limit, active, password), learned consultation time, leave (add and remove; booked patients are alerted).
- Departments: add and rename.
- Queue policy (13 fields; changing retention asks for confirmation).
- Staff, admin and tester accounts: add, change role, disable or enable, reset password. An admin can't change their own row.
- Audit log: search, filter by action and date, load older pages.
- Analytics by date range: per-doctor table, chart by hour, CSV.
- Exports: queue, audit, alerts.
- Backups: list, back up now.
- Simulation reports.

**Developer / tester**
- Pick scenarios and seeds, start a run, see progress, results tables and report downloads.
- Testers can't see live patient data.

**Waiting-room display (no sign-in)**
- Per doctor: now serving, next tokens and waiting count. Tokens only, never names.
- Today's check-in code when it's required.
- Refreshes every 5 s.

### 1.6 Native browser dialogs used today (to be replaced)

`prompt()` is used for reasons (skip, not here, emergency, remove priority, reinsert, cancel), for priority-category and colleague pickers (`pick()`), for password resets and for the check-in code. `confirm()` is used to cancel an appointment, delete data and change retention. The Figma file has a dialog for most of these. They become `<dialog>`-based components with the same required/optional rules.

### 1.7 Test selectors that depend on the current DOM

`test_ui.js` uses IDs and data attributes: `#lu #lp #login #logout #pwbtn #pwdlg #fpdlg #fpu #fpf1 #fpmsg #fpcancel #dn #adep #for #dep #est #ecap #app #runs #queue tr #events`, `[data-tab] [data-edit] [data-move] [data-cancel] [data-checkin] [data-priority] [data-pw] [data-act=not_present]`, `.appt`. It also overrides `window.prompt` and `window.confirm`. These selectors won't survive a component rewrite, so the suite is ported (see 3.5) rather than patched.

### 1.8 Where the Figma design needs data or features the backend doesn't have

Per the instruction not to change the schema in the initial migration and not to use mock data, these regions **are not rendered** until the backend supports them:

| Design element | Backend today | Plan |
|---|---|---|
| Patient age and sex, UHID, chief complaint, allergy alert, visit type, last visit, patient history dialog | Not stored | Leave out; the layout closes the gap. Proposed later as a schema change. |
| Hospital name and location in the sidebar and top bar | Not stored | Show the department and role from `/api/me`. A hospital name could become a `policy` key later (no schema change needed). |
| "Pause queue" / "Queue paused · Return at 10:45" | Doctor `break` status with `break_until` | Map Pause to `break` with a chosen duration. Same behaviour: order kept, ETAs shift. |
| "Let patients know about a delay" | Doctor `delayed` status (the alert rule already re-notifies when ETAs shift) | Map to `delayed` with minutes. |
| "End session" / "OPD session ended · Handover" | Nothing. The session ends at `opd_end`. | Leave out. Needs a business-rule decision. |
| Nurse role; the doctor approving emergency priority | Roles are patient, doctor, staff, admin, tester; `emergency` is staff/admin only | Keep the current rules: the emergency screen is for staff and admin. Changing who approves emergencies is a business-rule change for you to decide. |
| "Invite a team member" | Admin creates the account and password directly | Implement as the existing "Add user" form using the dialog design. |
| Token print preview, daily operations report | No print view; analytics exists | Print preview: a `@media print` layout of data we already have (no backend change). Daily report: built from `/api/admin/analytics` for one day. |

The **login, registration, booking, family, delete-data, audit, analytics, backups, exports and simulation** screens have no Figma frame. They are built from the Figma design system's components and tokens, not redesigned.

## 2. Proposed architecture

### 2.1 Stack

| Choice | Why |
|---|---|
| React 19 + TypeScript (strict) + Vite | As requested. Vite's dev proxy keeps the browser on one origin, so the `SameSite=Strict` cookie and SSE work unchanged. |
| React Router (library mode) | Role-based routes, deep links, and a redirect for the legacy `/?display=` link. |
| Plain CSS: global token file plus CSS Modules | Built into Vite, so no dependency. Figma variables map 1:1 to CSS custom properties. Tailwind isn't used because the generated Figma code is a reference, not something to paste in, and the existing app is already CSS-variable based. |
| `lucide-react` | Icons. Each Figma icon is checked against its Lucide equivalent before substituting. Anything that doesn't match exactly ships as the downloaded SVG. |
| `@fontsource-variable/inter` | Inter served from our own origin, because the CSP blocks font CDNs. |
| No state library, no data-fetching library, no UI kit | Server state is "refetch on SSE tick", which one small hook (`useLive`) covers. Session state is one React context. Revisit only if a real need appears. |

Runtime dependencies: `react`, `react-dom`, `react-router`, `lucide-react`, `@fontsource-variable/inter`. Development dependencies: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react*`.

### 2.2 Directory structure

```
frontend/                          # new; the Python app stays in app/
  index.html
  package.json  vite.config.ts  tsconfig.json
  src/
    main.tsx                       # mounts router and session provider
    routes.tsx                     # route table, role guard, legacy ?display= redirect
    api/
      client.ts                    # get/post wrapper: same error and 401 contract as today's api()
      types.ts                     # response shapes mirrored from server.py
    lib/
      useLive.ts                   # SSE + 5 s/30 s polling fallback (one shared EventSource)
      format.ts                    # hhmm, today, status/alert labels
    design/                        # Figma foundations (frame 07)
      tokens.css                   # SmartOPD/* variables, type scale, spacing, radii
      base.css
      Button.tsx  Status.tsx  Field.tsx  Dialog.tsx  Panel.tsx  Metric.tsx
      QueueRow.tsx  EmptyState.tsx  DataTable.tsx
    layout/
      AppShell.tsx  Sidebar.tsx  AppBar.tsx   # 224 px nav, 72 px bar, responsive rules
    auth/
      SessionProvider.tsx  RequireRole.tsx  LoginPage.tsx  PasswordDialogs.tsx
    features/
      queue/                       # shared by doctor, desk and admin
        useQueue.ts                # /api/queue + action() carrying `version`
        QueueTable.tsx  ReasonDialog.tsx  ColleagueDialog.tsx  PriorityDialog.tsx
      consultation/                # doctor · Figma 01, 09–20, 24–26 + dialogs
      front-desk/                  # staff/admin · 02, 21, 22 + dialogs
      emergency/                   # staff/admin · 03, 13, 19, 20 + approval dialog
      queue-monitor/               # staff/admin · 04
      admin/                       # admin · 05 + configuration dialogs; audit, analytics, backups, exports
      patient/                     # patient · 06, 23 (mobile-first)
      display/                     # public board · 08
      simulations/                 # tester
  public/icons/                    # any Figma SVG without an exact Lucide match
```

Each feature folder holds its page, its components and a hook that does its API calls. Components get data through props and don't call `fetch` themselves.

### 2.3 Routes

| Route | Role(s) | Figma |
|---|---|---|
| `/login` | public | none (built from the design system) |
| `/consultation` | doctor | 01 and state variants |
| `/front-desk` | staff, admin | 02, 21, 22 |
| `/emergency` | staff, admin | 03, 13, 19, 20 |
| `/queue-monitor` | staff, admin | 04 |
| `/admin/*` | admin | 05 and dialogs; tabs for doctors, people and policy, audit, reports |
| `/patient` | patient | 06, 23 |
| `/simulations` | tester (runs also viewable by admin under reports) | none |
| `/display?key=` | public | 08 |
| `/?display=KEY` | public | redirects to `/display?key=KEY` |

`/` sends each role to its home. The sidebar shows only the items that role may use. Route guards are only for convenience: the server still enforces every permission.

## 3. How React talks to the Python backend

### 3.1 Development

`npm run dev` (Vite on :5173) proxies `/api` (including the `/api/stream` SSE stream) to `python3 app/server.py --demo` on :8000. The browser sees one origin, so cookies, CSP and SSE behave as in production.

### 3.2 Production

`npm run build` writes `frontend/dist/`. The Python server serves it. Runtime is still Python only; Node is needed only to build.

### 3.3 Server changes (additive, about 25 lines, no API or schema change)

1. Serve `frontend/dist/assets/*` with the correct content type, resolving the path inside the folder so `..` can't escape it. Hashed files get `Cache-Control: immutable`.
2. **Changed during setup:** during the migration React lives under **`/app/`** and the legacy UI keeps `/` (and `/?display=`) untouched, instead of moving the legacy UI to `/legacy`. Existing users, printed display links and `test_ui.js` see no change at all until cutover. `/app/*` serves `frontend/dist/index.html` (client-side routes); without a build it answers 503 with build instructions.
3. At cutover the base moves from `/app/` to `/`, `/?display=KEY` redirects to `/display?key=KEY`, and `app/index.html` is removed.
4. The CSP stays as it is. Vite's asset inlining is turned off (`assetsInlineLimit: 0`) because the CSP blocks `data:` URIs. Vite's built output is a same-origin module script, and fonts and icons are same-origin.

### 3.4 Client contract

`api/client.ts` keeps exactly the rules of today's `api()`: JSON in and out, `{error}` shown verbatim, and 401 going to sign-in with "Your session ended". `useLive(fetcher)` repeats today's refresh behaviour: one shared `EventSource`, a 300 ms debounce, polling every 5 s while the stream is down and every 30 s regardless. Queue actions always send the `version` from the last read.

### 3.5 Tests

- The backend suites are unchanged and must stay green after every phase.
- `tsc --noEmit` and `vite build` run as the frontend's compile checks.
- `test_ui.py` runs two browser suites on separate throwaway servers: `test_ui.js` (legacy UI at `/`, unchanged) and `test_ui_react.js` (React at `/app/`, role- and label-based selectors). The React suite grows screen by screen; it is skipped with a message when `frontend/dist` is not built. Legacy checks retire only at cutover.
- Phase 5 adds a visual comparison: Playwright screenshots of each implemented frame at 1440×1000, set beside `get_screenshot` from Figma, plus 1024 px and 390 px runs for the responsive rules.

## 4. Migration sequence and rollback

| Phase | Work | Done when | Rollback |
|---|---|---|---|
| 1 | Audit and architecture (this document) | Approved | n/a |
| 2 | Scaffold `frontend/`, tokens and base CSS, design-system components, API client, `useLive`, session, router, login. Server: static serving, SPA fallback, `/legacy`. | Login and `/api/me` round-trip work through the dev proxy and the Python-served build; backend suites green | Delete `frontend/dist`: the server falls back to the legacy UI |
| 3 | App shell, then the Consultation workspace (01 and its state variants and dialogs) wired to `/api/queue`, actions and doctor status | The doctor workflows in 1.5 pass in the browser; screenshot matches frame 01 apart from the regions in 1.8 | `/legacy` |
| 4 | One role at a time: front desk, then emergency, queue monitor, admin, patient, display, tester. Each ports its share of `test_ui.js`. | Every workflow in 1.5 is covered on React | `/legacy` |
| 5 | Full regression, visual comparison, responsive runs (1440, 1024, 390), performance (bundle size, refresh cost under SSE bursts), then cutover: remove `/legacy` and `app/index.html` | All suites green; you sign off | Revert the cutover commit |

Each phase is its own commit (or set of commits) on a `react-migration` branch. `main` keeps the working legacy UI until Phase 5.

## 5. Risks

1. **Design and data gaps (1.8).** Several of the design's most visible regions (allergy, chief complaint, patient history, end session) have no backend data. Leaving them out keeps the "no mock data" rule, but the consultation screen will look sparser than frame 01 until you decide on schema additions.
2. **Business-rule differences.** The design has doctors approving emergencies and a nurse role. Today staff and admins grant priority. This is kept as-is until you decide.
3. **Build step.** Deploying now needs a Node build, though the runtime stays Python only. Without a build the server keeps serving the legacy UI, so nothing breaks silently.
4. **Live-refresh behaviour.** The legacy UI preserves focus and open `<details>` across refreshes by skipping identical HTML. React gets this from reconciliation if keys are stable; the "focus kept across refresh" check guards it.
5. **Screens without Figma frames** (login, booking, admin tabs, simulations) must be built from the design system. That needs care so they match without inventing new patterns.
6. **Figma is fixed at 1440 px.** Smaller layouts follow the written breakpoint rules in frame 07, not drawn frames, so tablet and phone layouts for desktop screens are an interpretation.
7. **Icon fidelity.** Lucide is used only where it exactly matches the Figma icon; otherwise the Figma SVG is shipped.

## 5. Phase log

### Foundation (setup, design system, API client, authentication)

Implemented
- `frontend/`: React 19, TypeScript (strict), Vite, React Router, `lucide-react`, self-hosted Inter. `npm run dev` proxies `/api` to the Python server on :8000; `npm run build` type-checks and writes `frontend/dist`.
- Design system from Figma frame 07 and variables: `design/tokens.css` (all 13 `SmartOPD/*` colours, type scale, spacing, radii, 44 px targets), `Button` (primary, secondary, danger, disabled), `TextButton`, `Status` (5 tones), `TextField`, `SelectField` (Figma chevron), `Panel`, `EmptyState`, `LoadingState`, `ErrorState`, `Callout`, `Message`, `Brand`, `Overline`, and `Dialog` (from dialog frames 4:2063, 4:2200, 4:2337). The 9 Figma icons are downloaded to `design/icons/`.
- `api/client.ts` (legacy `api()` contract), `api/types.ts`, `lib/useLive.ts` (shared SSE stream, 300 ms debounce, 5 s / 30 s polling fallback), `lib/useFormAction.ts`, `lib/format.ts`.
- Auth: session provider (`/api/me`, 401 → sign-in with notice), sign-in, patient registration, forgot-password and change-password dialogs, sign-out, role guard, role home redirects, route table for every screen.
- Screens not yet migrated show `NotMigrated`: the signed-in account, the live connection state, and a link to the legacy UI. No mock data.
- `/app/design-system`: internal page laid out like Figma frame 07 for screenshot comparison.
- Server: `/app/` route (+25 lines, path-escape guarded, hashed assets cached). No API, schema, auth or permission change.

Verified
- Backend suites unchanged and passing: engine, simulator, API (with new `/app/` and path-escape checks), features.
- Legacy browser suite: 36/36. React browser suite: 25/25 (sign-in, wrong password, forgot password, every role's landing page, role guard, deep link while signed out, reload keeps the session, live stream connects, change password, session ended elsewhere, registration, dialog, 390 px without sideways scroll, no console errors, which also proves no CSP violations).
- Screenshots: `/app/design-system` against frame 07 and the dialog against 4:2063 match on colour, type, spacing, sizes and radii. Sign-in has no Figma frame and was checked against the design-system rules at 1440 and 390 px.

Not yet done / known differences
- The Queue row component (4:2404) and the sidebar and top bar come with the Consultation screen, where they are first used.
- Icons: Figma's icons are Lucide icons drawn at 20 px with a 1.7 stroke. Whether `lucide-react` reproduces them exactly is checked when the sidebar is built; until then the downloaded SVGs are the reference.
- The dialog backdrop colour is not specified in Figma (ink at 45% is used).
