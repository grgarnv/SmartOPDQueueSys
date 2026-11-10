# 3A React inventory: Front desk + Queue monitor

Read for this: every file under frontend/src, plus app/server.py (handlers quoted below), app/engine.py (WAITING),
app/index.html (legacy staff queue at lines 400–470, desk at 520–590), app/test_ui_react.js, app/test_ui.py.
Paths below are relative to `frontend/src/` unless they start with `app/`.

---

## 1. What exists and must be reused (exact signatures)

### api/
- `api/client.ts`
  - `api<T>(path: string, body?: unknown): Promise<T>`: GET without a body, POST with one. Throws `ApiError(message, status)`. status 0 means the server could not be reached. A 401 ends the session.
  - `qs(params: Record<string, string|number|undefined|null>): string`: skips empty values. Use it for `/api/lookup?q=` and `/api/queue?doctor_id=`.
- `api/types.ts`: has `Role, Channel, User, Health, Ok, ApptStatus, DoctorStatus, QueueEntry, QueueState, Departments`.
  `QueueState["doctor"]` = `{id, name, department, department_id, status, break_until, holds_opd, opd_start, opd_end}`.

### lib/
- `lib/useLive.ts`
  - `useLive<T>(fetcher: () => Promise<T>, deps?: unknown[]) → { data?: T; error?: string; refresh(): Promise<void>; set(d: T): void }`. One shared SSE stream, 300 ms debounce, 5 s / 30 s polling. On error it keeps the last good data.
  - `useStreamLive(): boolean`, `useLastSync(): number`, `isLive()`, `closeStream()`.
- `lib/useFormAction.ts`: `useFormAction<T>(send: (fields: Record<string,string>, form) => Promise<T>, { ok?: string | ((r:T)=>string); after?: (r:T, form) => void }) → { onSubmit, msg, busy, setMsg }`.
  Use `after` to keep the server reply. The walk-in reply opens the "token issued" dialog this way.
- `lib/format.ts`: `hhmm(iso)`, `today()`, `ROLE_LABEL`, `LANGS` (en, hi; mirrors server LANGS), `CHANNELS`, `clock(t)` (12-hour), `longDate(day)`, `minutesBetween(from, to)`, `tokenText(n)` (3-digit).

### design/
- `design/ui.tsx`
  - `Button({kind?: "primary"|"secondary"|"danger", block?, ...button})`, `buttonClass(kind, block)` (use it for the display link `<a>`), `TextButton({danger?})`
  - `Status({tone?: Tone, children})`, where `Tone = "success"|"info"|"caution"|"urgent"|"neutral"`
  - `TextField({label, hint?, ...input})`, `SelectField({label, hint?, children, ...select})`
  - `Panel({title?, sub?, aside?, children, className?})`: gives a named region through aria-labelledby. The tests find regions by their title.
  - `EmptyState({title, children?, foot?})`, `LoadingState({title?, rows?})`, `ErrorState({title, children?, action?})`, `Callout({tone?: "success"|"info"|"caution"|"urgent", children})`, `Message({msg})`, `Overline({children})`, `Brand()`
- `design/Dialog.tsx`: `Dialog({open, onClose, title, description?, size?: "sm"|"md"|"lg", onSubmit?, footer?, children?})`. With `onSubmit`, the body and footer form one `<form>`.
- `design/tokens.css`: colours `--ink --muted --teal --tint --blue --blue-tint --amber --amber-tint --red --red-tint --bg --line --field-line --focus-line`. Type `--text-caption 12 / -field 13 / -label 13 / -body 14 / -section 18 / -dialog 23 / -page 27`. Spacing `--s1..--s6`, radii `--r-*`, `--target`.

### features/queue/ (the shared queue layer)
- `useQueue.ts`
  - `type QueueAction = "call_next" | "start" | "complete" | "skip" | "not_present"`
  - `type Failure = { message: string; status: number }`
  - `useQueue(doctorId?: number) → { queue?: QueueState; error?; refresh; busy; act(action, body?: {appointment_id?, reason?}); setStatus(status: DoctorStatus, minutes?); failure; clearFailure }`
  - `act` sends `{action, doctor_id: doctorId, ...body, version: q.data?.version}` and shows the server's `QueueState` reply through `q.set`. `setStatus` already sends `doctor_id`, so it works for staff as it is.
- `present.ts` (display only): `isCurrent(e)`, `isWaiting(e)` (booked or checked_in, turn not missed), `isLate(e)` (skipped or turn_missed), `onHold(q)`, `entryStatus(e) → {tone,label}`, `entryDetail(e)`, `rowDetail(e)`, `etaText(e, q)` ("On hold" / "Pending" / "Next" / "~N min"), `doctorStatus(q) → {tone,label,short}`.

### features/consultation/ (to generalise; doctor screen must keep working)
- `QueueTable({ q: QueueState; rows: QueueEntry[]; highlightFirst?; actions?: (e) => ReactNode; label: string })`. Rows are keyed by appointment id. Styles live in `consultation.module.css` (`.table .withActions .first .firstUrgent .tok .tealText .redText .rowName .rowSub .eta .rowActions`, plus the `<768px` rules for `.table` at the bottom of that file).
- `dialogs.tsx`. Every dialog uses the private helpers `field(e, name)` and `footer(cancel, primary, busy)`, and classes from `consultation.module.css` (`cancelBtn primaryBtn calloutSub dialogTick choices choice chosen choiceLabel choiceHint lateList lateRow lateToken lateText lateName lateSub dialogTable failure failureTitle srOnly`).
  - `NoShowDialog({e: QueueEntry|null, busy, onClose, onConfirm(reason)})`: skip, with a reason select.
  - `NotHereDialog({e, busy, onClose, onConfirm(note)})`: not_present, with an optional note.
  - `PauseDialog({open, q?, busy, onClose, onConfirm(minutes)})`: doctor wording.
  - `AvailabilityDialog({open, q?, busy, onClose, onConfirm(status, minutes?)})`: all 4 statuses plus a minutes select. Title "Your availability". Hints and the `statusNow()` description are written in the second person.
  - `SkippedLateDialog({open, q?, busy, onClose, onNoShow(e)})`: lists `q.entries.filter(isLate)`. Its only action is "Skip / no-show".
  - `FullQueueDialog({open, q?, busy, onClose, onNotHere(e), onNoShow(e)})`: rows are waiting entries plus late entries that are not skipped. The actions are hard-coded for the doctor.
  - `FailureDialog({failure, onClose, onRefresh})`: title "The queue could not be updated", shows the server's message.
- `ConsultationPage.tsx`
  - Local `Metric({label, value, note, small})`. Its `.pulse/.metric*` CSS is in consultation.module.css.
  - Local `run(send, say)` + `feedback` state with a 12 s timeout. The live line reads `Live updates on/reconnecting · Last updated hh:mm`.
  - Gets `clears_at` from `/api/departments`.

### auth/ and layout/
- `auth/session.tsx`: `useMe(): User`, `useSession()`, `HOME` (staff → `/front-desk`, admin → `/admin`; keep both).
- `auth/RequireRole.tsx`: `RequireRole({roles, children})`.
- `auth/PasswordDialogs.tsx`: `ChangePasswordDialog` is the pattern for the desk's "Reset patient password" dialog: useFormAction, a TextField with minLength 8, and Message.
- `layout/AppShell.tsx`: `NAV` already has `/front-desk` (users icon) and `/queue-monitor` (pulse icon) for `["staff","admin"]`. Crumbs come from the NAV label. **No change needed.**
- `features/pending/NotMigrated.tsx`: stays for `/emergency`, `/admin/*`, `/patient` and `/simulations`.

---

## 2. Extensions needed (and how, without breaking the consultation screen)

### 2.1 `api/types.ts`: add these response types (shapes checked against app/server.py)
```ts
/** appointment_view() (server.py ~826): /api/checkin, /api/cancel; also spread into the walk-in reply */
export interface AppointmentView extends QueueEntry {
  doctor: QueueState["doctor"]; day: string; updated_at: string; arrival_alert: boolean; patient_id: number;
  notifications: { purpose: string; channel: Channel; status: string; created_at: string; updated_at: string }[];
  checkin_opens_at: string | null; checkin_code_required: boolean;
}
/** POST /api/staff/walkin. create_booking() + username. `warning` is absent when existing=true. */
export interface WalkIn extends AppointmentView { existing: boolean; warning?: string | null; username: string }
/** GET /api/lookup?q= (today's visits; patient accounts) */
export interface Lookup {
  results: { id: number; token: number; status: ApptStatus; day: string; patient_name: string; phone: string | null; doctor: string; doctor_id: number }[];
  patients: { id: number; username: string; name: string; phone: string | null; guardian: string | null }[];
}
export type Congestion = "normal" | "busy" | "over capacity";
/** GET /api/admin/overview (staff, admin) */
export interface Overview {
  doctors: (QueueState["doctor"] & { waiting: number; current_token: number | null; current_status: ApptStatus | null;
    avg_minutes: number; clears_at: string | null; congestion: Congestion; completed: number; skipped: number; emergencies: number })[];
  exceptions: { at: string; action: string; detail: string | null; doctor: string | null; token: number | null }[];
  failed_alerts: number; updated_at: string; opd_end: string;
}
/** GET /api/admin/policy (staff, admin). Every value is a string. priority_categories is a comma list. */
export interface Policy { [key: string]: string; priority_categories: string; require_checkin_code: string; grace_minutes: string; checkin_code: string; display_key: string }
/** GET /api/admin/notifications */
export interface AlertLog { notifications: { id: number; purpose: string; channel: Channel; status: string; attempts: number; created_at: string; updated_at: string; detail: string | null; patient: string; token: number | null; doctor: string | null }[] }
```
Notes:
- `Overview.doctors[].waiting` counts **booked + checked_in, late ones included** (engine.WAITING). `present.isWaiting` does not count late patients. Label the overview number "waiting" and do not compare it with a count of `isWaiting` rows.
- Overview gives **no next-call ETA**. On a session card, show "next call" only for the selected doctor. Use `etaText(first isWaiting entry, q)` from that doctor's useQueue. Omit it on the other cards. Leave a comment saying so near the card.
- `Departments` does not need extending. Overview already has `department`, `department_id`, `holds_opd`, `status`, `waiting` and `clears_at` for every active doctor, so one fetch covers the walk-in picker, the session card and the colleague picker (§2.4).

### 2.2 `features/queue/useQueue.ts`: extend; keep the current API exactly
- Widen the union so the doctor's calls still type-check:
  `type QueueAction = "call_next"|"start"|"complete"|"skip"|"not_present"|"emergency"|"priority"|"remove_priority"|"reinsert_front"|"transfer"|"transfer_all"`
- Widen the body type: `{ appointment_id?: number; reason?: string; category?: string; to_doctor_id?: number }`. `transfer_all` is QUEUE_WIDE, so it already gets `doctor_id: doctorId`.
- Check-in and cancel return an `AppointmentView`, not `queue_state`. **Never pass that to `q.set`.** Generalise `send` so it can show the reply in different ways:
  ```ts
  async function send<T>(request: () => Promise<T>, show: (r: T) => void = (r) => q.set(r as unknown as QueueState)) { ... show(reply) ... }
  const checkIn = (appointment_id: number) => send(() => api<AppointmentView>("/api/checkin", { appointment_id }), () => q.refresh());
  const cancel  = (appointment_id: number, reason?: string) => send(() => api<AppointmentView>("/api/cancel", { appointment_id, reason }), () => q.refresh());
  return { ...existing, checkIn, cancel };
  ```
  These two endpoints ignore `version`. Say so in a one-line comment. `busy`, `failure` and the 409 refresh behave the same for every action.
- **Staff must not call `useQueue()` without an id.** `/api/queue` without `doctor_id` returns 400 for staff. Render the queue component only once a doctorId is chosen (default: the first overview doctor with `holds_opd`). Keep the hook's signature as it is.
- Server rules the UI must follow (from QUEUE_ACTIONS, server.py ~942). **Admin cannot use `call_next`, `skip` or `not_present`** (doctor and staff only). Staff and admin can use emergency, priority, remove_priority, reinsert_front, transfer and transfer_all. Hide the doctor/staff-only actions for admin, as the legacy UI does (`isDoc || isStaff`).

### 2.3 `features/queue/present.ts`: additive only
- `doctorStatus(q)` needs a `QueueState`, but overview rows are not one. Pull the logic out without changing the doctor's call:
  `export function statusOf(d: QueueState["doctor"], updatedAt: string, inConsultation: boolean)`, with `doctorStatus = (q) => statusOf(q.doctor, q.updated_at, q.entries.some(e => e.status === "in_consultation"))`.
  Session cards call `statusOf(row, overview.updated_at, row.current_status === "in_consultation")`.
- Add `staffActions(e: QueueEntry, role: Role)`. It returns the visible actions and copies the legacy conditions in index.html 419–431 exactly:
  - check in: booked or skipped
  - not here: called or checked_in, staff only
  - skip: `e.can_skip`, staff only
  - emergency: waiting and `!e.emergency`
  - priority: waiting and `!e.priority`
  - remove priority: `e.priority`
  - move and cancel: waiting
  - reinsert next: skipped

  "Waiting" means `status ∈ {booked, checked_in}`. This decides what is shown, nothing more; the server still decides the rest.
- Add the congestion pill: `congestionStatus(c: Congestion) → {tone, label}`, with normal → success, busy → caution, over capacity → urgent, and the label taken from the server value.

### 2.4 Colleague / doctor lists: one helper, not three
- Walk-in doctor picker. Group overview doctors by `department` and keep those with `holds_opd && status !== "unavailable"` (matches create_booking). **Do not filter on capacity.** Staff bookings go through and come back with `warning`.
- Move / Move all colleagues: overview doctors with the same `department_id`, a different id, `holds_opd` and status not unavailable. This is the legacy `colleagues()` at index.html ~452.
- Put both filters in `features/queue/present.ts` as `openDoctors(o: Overview)` and `colleaguesOf(o: Overview, doctorId: number)`. The Emergency milestone will need them too.

### 2.5 Move the dialogs to the shared queue folder (Emergency reuses them)
Move `consultation/dialogs.tsx` → `queue/dialogs.tsx` and `consultation/QueueTable.tsx` → `queue/QueueTable.tsx`. Move the CSS they use into `queue/queue.module.css`:
- the table block with its `<768px` table rules
- the dialog block
- `.srOnly`

`ConsultationPage.tsx` then imports from `../queue/...`. Keep the class names and values unchanged so the doctor screen looks the same pixel for pixel. Re-run the React suite after the move: the doctor checks cover all of these dialogs.

Generalise the moved dialogs. Keep all current props and defaults:
- `AvailabilityDialog`: add `doctorName?: string`. When set, the title is `${doctorName}: availability` and the description and hints switch to the third person. Leave the doctor's wording unchanged. The tests rely on "Your availability", "Running late", "Delay duration", "Update & notify" and "Update availability".
- `SkippedLateDialog`: add optional `onCheckIn?(e)` and `onReinsert?(e)`. Show them only when passed, so the doctor screen is unchanged.
  - Check-in on a skipped row must say: "Checks in at the end of the queue".
  - Check-in on a late-within-grace row (`turn_missed && !can_skip`) must say: "Keeps their place".
  - Reinsert next, labelled "Reinsert next · policy exception", opens the ReasonDialog.
  - Figma 4-2152 says "Reinsert 021 after next", but the server's `reinsert_front` puts the patient **next** (engine.front_position). Use "Reinsert next".
- `FullQueueDialog`: add an `actions?: (e) => ReactNode` override and a `rows?` override (staff sees skipped rows too). When those are not passed, the current doctor behaviour stays as it is.
- `NoShowDialog`, `NotHereDialog` and `FailureDialog` can be reused as they are.

New shared dialogs in `queue/dialogs.tsx`. Emergency will import these, so do not create look-alikes in queue-monitor/:
- `ReasonDialog({open, title, description?, label, required: boolean, primary, danger?, callout?, busy, onClose, onConfirm(reason)})`. One component covers emergency (required), remove priority (required), reinsert next (required, with the callout "Policy exception · recorded in the audit log") and cancel (optional; the callout says the patient is told). TextField `required` matches the server's rules. The server's 400 text still shows through FailureDialog.
- `EmergencyDialog` = ReasonDialog with `required`, danger primary "Give emergency priority", and the callout "Ranked above every other patient and every priority category." Name it so the Emergency page (4-2114) can extend it later.
- `PriorityDialog({e, categories: string[], busy, onClose, onConfirm(category)})`: a SelectField of the policy categories.
- `MoveDialog({e?: QueueEntry|null /* null = move all waiting */, colleagues: Overview["doctors"], busy, onClose, onConfirm(toDoctorId)})`. With an empty list it shows an EmptyState: "No other doctor in this department is holding OPD now." (the legacy text).

### 2.6 Other shared pieces worth promoting (used by both screens)
- `Metric` (ConsultationPage) is wanted for the front-desk session card ("12 waiting") and the monitor session cards. Move it to `design/ui.tsx` as `Metric({label, value, note, small?})` and its `.metric*` CSS to `ui.module.css`. Leave `.pulse` (a consultation layout) where it is. Update the ConsultationPage import. Only do this if both new screens use it. Otherwise leave it.
- Action feedback: the 12 s `feedback` state plus `run()` in ConsultationPage will be needed in both new pages. Add `useFlash()` (about 5 lines: `[text, say]` that clears after 12 s) to `lib/useFormAction.ts` next to the form hook rather than adding a file. Don't rewrite ConsultationPage to use it in this milestone.
- Label maps for exceptions and alert delivery. Add these to `lib/format.ts`; the Admin audit log and Patient alerts will reuse them:
  - `EVENT_LABEL` for the overview exception actions: skip, emergency, reinsert_front, reinserted, doctor_delayed, doctor_unavailable, doctor_break, priority, remove_priority, not_present, transferred_out, cancelled. Anything missing falls back to `action.replace(/_/g, " ")`.
  - `ALERT_LABEL` and `SENT_LABEL`, copied from index.html:116–118: `ALERT = {arrival, eta_change, called, skipped, doctor_unavailable, doctor_leave, transferred, cancelled, reset_code}` and `SENT = {pending: "sending", sent, delivered, unconfirmed: "sent, delivery not confirmed", failed}`.
- `useOverview()`: `useLive(() => api<Overview>("/api/admin/overview"))`. Put it in `features/queue/useOverview.ts` (it is one line, so it could also be inlined, but three screens use it). `usePolicy()` is the same with `/api/admin/policy` and can sit in the same file.

---

## 3. Duplication risks (do not)
- Do not copy QueueTable or the dialogs into front-desk/ or queue-monitor/. Move them (§2.5).
- Do not write a second `fetch("/api/queue/action")` path. Every queue change goes through `useQueue(doctorId).act / checkIn / cancel / setStatus`. Front-desk lookup check-in uses `useQueue(selectedDoctorId).checkIn(id)`; the server does not need the doctor, and SSE refreshes the other doctors' views. The Patient checked in dialog takes its data from the AppointmentView the call returns, so `checkIn` must return the reply (`send` returns it).
- Do not compute waiting, wait ranges or clear times on the client. Figma's "96–112 min" and "Estimated wait: 104–120 min" become server `clears_at` (overview) and the reply's `eta` / `ahead`. Leave a comment where the range was dropped.
- Do not invent fields. Leave out, with a comment near the component:
  - age, gender, UHID, reason for visit, Room, "Morning session", Counter 02, Walk-in/Appointment/Follow-up subtitles, "SMS with tracking link sent", hospital name
  - "Patient identity confirmed" ticks, unless they are a real checkbox the staff member ticks (UI-only confirmation, nothing stored)
- Do not parse policy twice. `priority_categories.split(",").map(s=>s.trim()).filter(Boolean)` goes in one place (usePolicy or present.ts).
- Do not add a second live-line component. The AppShell sidebar `Connection` already shows the stream state. Page footers can reuse the ConsultationPage text pattern with `useStreamLive()`.
- Do not use `/api/departments` and `/api/admin/overview` together on one screen. Overview is enough (§2.1).

---

## 4. Routes and nav
- `routes.tsx`: `deskScreens` maps every entry to `<NotMigrated screen={title} />`. Add an optional `element` field (`element?: ReactNode`) and render `element ?? <NotMigrated screen={title} />`. Give `/front-desk` `<FrontDeskPage />` and `/queue-monitor` `<QueueMonitorPage />`. Leave `/emergency` and `/admin/*` as they are. Leave `/patient` and `/simulations` as they are.
- `layout/AppShell.tsx` NAV: no change. Both entries exist for staff and admin, and the crumb label is "Front desk" / "Queue monitor".
- Waiting-room display link. `/app/display` is **not built** in this milestone, and `*` there redirects to sign-in. Link to the legacy board instead: `"/?display=" + policy.display_key` (same as index.html:523), with `target="_blank" rel="noopener"` and `buttonClass("secondary")`. Add `// switch to /app/display?key= when the Display milestone lands`.
- Queue monitor deep link from the front desk ("open that doctor's queue"). Use `navigate("/queue-monitor?doctor=" + doctor_id)`, and have QueueMonitorPage read `useSearchParams()` (react-router is already a dependency) for the initial selection.

---

## 5. Test helpers to reuse (app/test_ui_react.js, app/test_ui.py)

### test_ui_react.js
Helpers to reuse:
- `check(name, ok, detail)`, `wait(ms)`
- `login(u, p)`, `signOut()`, `account(item)`
- `heading()` (h1 text), `path()`
- `noSideScroll()`, `region(name)` (by Panel title)
- `click(name, scope)` (first matching button + 700 ms wait)
- the console-error collector, which must stay green

Patterns to reuse:
- **second desk session**: `desk = page.context().newPage()` on `localhost` with `dpost(path, body)` and `deskQueue()`, at lines 180–186. Use it for "a change elsewhere appears live" on the monitor, and for building state through the API.
- **stale-version check** with `page.route("**/api/stream", r => r.fulfill({status: 204}))`, at lines 198–212.
- `said()` reads `main p[role=status]` last. Reuse it only if the new pages put their feedback line last in `<main>` as `p[role=status]`.

Changes required:
- Line 61 expects the staff h1 to be exactly "Front desk". When the page takes the Figma title ("A smooth start to every visit."), update that tuple. ConsultationPage did the same with "Your OPD, at a glance."
- Line 79 (`/app/front-desk` signed-out redirect) still holds.
- Put the new desk and monitor blocks **after the consultation block and before the responsive block** (line 216). The doctor block changes Dr. Rao's queue: Demo Patient ends up skipped, Farah Iqbal is a walk-in, and so on. Do not depend on that state; seed your own (below).
- `firstRow()` and `tabs()` are specific to the consultation screen. Write new label-based ones, for example a `table` named "Live queue".

### test_ui.py
- `prepare_react(base, db)` already:
  - sets the policy to OPD 00:00–23:59 with `block_after_close` 0
  - makes walk-ins Asha Verma, Bilal Khan, Chitra Nair and Esha Gill with Dr. Rao (doctor_id 1)
  - books `patient` (Demo Patient) with Dr. Rao and moves `due_at` back 11 min, so grace is over and `can_skip` is true

  Reuse `Client(base).login(...)`, the `staff(...)` call style, and the sqlite `due_at` trick.
- Extend it for 3A (append; keep the existing lines exactly). Seed **Dr. Iyer (doctor_id 2, General Medicine)** so desk tests do not depend on what the doctor block did:
  - walk-ins `"Gita Rao"` and `"Hari Das"` with doctor 2
  - register two patient accounts through `/api/register`. Do not use the username `react.tester`; the register test uses it. Book each with doctor 2 for today.
    - Account A: set `due_at = now - 11 min`, then `staff("/api/queue/action", {"action": "skip", "appointment_id": ...})` to make a **skipped** visit. This covers "checks in at the end" and Reinsert next.
    - Account B: set `due_at = now - 2 min`. Grace is 10 min by default, so this is **late within grace** (`turn_missed && !can_skip`), which keeps its place on check-in.
  - Dr. Rao (id 1, same department) is the transfer target for Move and Move all. Dr. Khan (id 3, Paediatrics) checks that colleagues are limited to the same department.
- Demo doctors (server.py init_db): 1 Dr. Rao GM, 2 Dr. Iyer GM, 3 Dr. Khan Paediatrics, 4 Dr. Sen Orthopaedics. All have work_days 0123456.
- Run only the React suite: `cd app && python3 -c "import shutil,test_ui; test_ui.run(shutil.which('playwright-cli'),'test_ui_react.js','React UI',test_ui.prepare_react)"`.

---

## 6. Recommended file layout
```
frontend/src/
  api/types.ts                      + AppointmentView, WalkIn, Lookup, Congestion, Overview, Policy, AlertLog
  lib/format.ts                     + EVENT_LABEL, ALERT_LABEL, SENT_LABEL
  lib/useFormAction.ts              + useFlash()
  design/ui.tsx, ui.module.css      + Metric (moved from ConsultationPage, only if both screens use it)
  features/queue/
    useQueue.ts                     extended union/body; send<T>(request, show); checkIn, cancel
    useOverview.ts                  useOverview(), usePolicy() (+ categories parse)
    present.ts                      + statusOf, staffActions, congestionStatus, openDoctors, colleaguesOf
    QueueTable.tsx                  moved from consultation/ (+ optional position/arrival columns for frame 04: POS = ahead+1, ARRIVAL = clock(checked_in_at) or "—")
    dialogs.tsx                     moved from consultation/ + ReasonDialog, EmergencyDialog, PriorityDialog, MoveDialog; generalised Availability/SkippedLate/FullQueue
    SessionCard.tsx                 one doctor's card from an Overview row (status pill, waiting, clears_at, congestion, optional next-call); used by both screens
    queue.module.css                table + dialog + srOnly CSS moved from consultation.module.css, + session card
  features/consultation/            ConsultationPage imports ../queue/{QueueTable,dialogs}; CSS for moved blocks deleted here
  features/front-desk/
    FrontDeskPage.tsx               page: header (Figma 02 title), lookup panel, walk-in panel, session visibility (SessionCard + selected doctor), recent check-ins, reception panel (display link, check-in code), alert log
    Lookup.tsx                      search form (useLive keyed on the submitted term so statuses refresh), results table, accounts table
    WalkInForm.tsx                  name, phone, alert language (LANGS), department → doctor (openDoctors); POST /api/staff/walkin via useFormAction
    dialogs.tsx                     AppointmentFoundDialog (4-2227), CheckedInDialog (4-2134 / 4-4219, from AppointmentView/WalkIn), TokenSlip + print (4-4481 / 4-4490), GiveTokenDialog (pick doctor for an existing account), PatientPasswordDialog
    AlertLog.tsx                    GET /api/admin/notifications table (ALERT_LABEL / SENT_LABEL); admin's later tab can import it
    frontDesk.module.css            incl. @media print rules showing only the slip
  features/queue-monitor/
    QueueMonitorPage.tsx            header + "Open waiting room display", session cards grid (useOverview), selected doctor's live queue (useQueue(id)), doctor status controls (AvailabilityDialog with doctorName), Needs attention panel, all dialogs
    NeedsAttention.tsx              overview.exceptions (EVENT_LABEL) + selected queue's isLate rows → SkippedLateDialog with onCheckIn/onReinsert
    queueMonitor.module.css
```

### Front-desk specifics
- **Recent check-ins.** No endpoint lists check-ins across every doctor. `/api/lookup` needs a non-empty `q` and returns no `checked_in_at`. Use the selected session doctor's `useQueue(id).queue.entries`: filter `checked_in_at`, sort descending, show token, name and `clock(checked_in_at)`. Label it with the doctor's name. Fanning out `/api/queue` to every doctor is possible but costs N requests per refresh, so leave it out unless asked.
- **Print.** The slip shows only reply fields: `tokenText(token)`, `patient_name`, `doctor.name`, `doctor.department`, `day`, `username`, `eta` if present (labelled as an estimate), and `warning`. Call `window.print()` with a global `@media print` rule (`:global(body *) { visibility: hidden }` + the slip visible) in frontDesk.module.css.
- **Check-in outcome wording** comes from the row's status before the call plus the server's reply:
  - booked → "Checked in · keeps their place". This covers late-within-grace too, because server.py checkin() keeps the position for any booked patient.
  - skipped → "Rejoined at the end of the queue", plus the reply's `ahead` / `eta`.
  - On the button or dialog **before** confirming a skipped patient: "Checks in at the end of the queue. Use Reinsert next (policy exception, reason required) to put them next."
- **Lookup rows**:
  - No reset-password button when `guardian` is set (the server answers 409). The legacy UI hides it too.
  - "Open queue" links to `/queue-monitor?doctor=<doctor_id>`.
  - "Give token" on an account → GiveTokenDialog (doctor picker) → `/api/staff/walkin {patient_id, doctor_id}`.
- **Reception card**: `policy.checkin_code`, plus `require_checkin_code === "1" ? "patients need it to check themselves in" : "not required at the moment"` (the legacy text).
