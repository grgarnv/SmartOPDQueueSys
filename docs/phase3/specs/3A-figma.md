# 3A Figma layout spec: Front desk + Queue monitor

Sources: outlines in `SCRATCH/figma/` (2-25, 4-3942, 4-4081, 2-33, 4-2134, 4-2227, 4-4219, 4-4481, 4-4490, 4-2152, 4-3874; 4-2080 and 4-2114 for the reason-dialog pattern). There are **no PNG exports** (`design/figma-exports/` does not exist), so all values come from the outlines. Outline text is cut at 48 characters, so a few strings end in "…" below.

Conventions
- Positions are Figma px **relative to the Workspace** (abs − (256,104)) for pages, and relative to the dialog's top-left for dialogs. "x24 y66" means rel(24,66).
- Font size = text height / 1.45 (brief table). Weights follow the brief: titles and values 600, labels and names 500, captions 400.
- Colours use tokens from `design/tokens.css`. Components come from `design/ui.tsx` (Button, buttonClass, TextButton, Status, TextField, SelectField, Panel, EmptyState, LoadingState, ErrorState, Callout, Message, Overline), `design/Dialog.tsx`, `features/consultation/QueueTable.tsx` + `dialogs.tsx`, and `layout/AppShell.tsx`.
- Shell: the frames' sidebar and bar match frame 01, and AppShell already implements them. Bar identity text in the frames ("Anita Desai · Reception · Counter 02", "Dr. Aisha Mehta") comes from AppShell (`me.name`, `ROLE_LABEL`). "Riverside Hospital", the location block and "Counter 02" stay omitted, as decided in FRONTEND_MIGRATION §1.8. Nothing in AppShell changes for this milestone.

---

## 0. Shared pieces this milestone should create or generalise (2+ screens use each)

| Piece | Where | Why |
|---|---|---|
| `PageHeader` (title 27/600, sub 13 muted 5px below, actions right-aligned and top-aligned 3px down, wraps) | `design/ui.tsx` (+ ui.module.css). Move `.head/.title/.sub` out of consultation.module.css. | 01, 02 and 04 all use the same header. Consultation should switch to it too. |
| Queue dialogs moved to `features/queue/dialogs.tsx` (NoShow, NotHere, Pause, Availability, SkippedLate, FullQueue, Failure) plus new `ReasonDialog`, `EmergencyDialog`, `PriorityDialog`, `RemovePriorityDialog`, `ReinsertNextDialog`, `CancelVisitDialog`, `MoveDialog` (single patient and move-all) | `features/queue/dialogs.tsx` (move the dialog CSS rules into `features/queue/queue.module.css`) | The brief requires the Emergency/priority dialogs to sit in a shared place now, so the Emergency milestone reuses them. Update the Consultation imports. |
| `QueueTable` gains optional `pos` (server `ahead + 1`) and `arrival` (`checked_in_at`) columns plus a `dense` single-line row (54 px pitch) | `features/consultation/QueueTable.tsx` → move it to `features/queue/QueueTable.tsx` | Frame 04 live queue and 4:3874 full queue. Keep the existing actions column. |
| `TokenIssuedDialog` (4:2134 = 4:4219) and `TokenSlipDialog` (4:4481 = 4:4490) | `features/front-desk/` (only front desk uses them) | Walk-in result and check-in result share the same layout. |
| Dialog sizes: add `xs` = 480 (4:2134/4:4219) and `wide` = 680 (4:2227) | `design/Dialog.module.css` (one line each) + the size union in Dialog.tsx | Figma dialog widths are 480/560/600/680/760, and Dialog has only 560/600/760. |
| `doctorStatus()` should also accept an overview row | `features/queue/present.ts`: take `{status, break_until, holds_opd}` + `updated_at` + `inConsultation` instead of a whole QueueState | Session cards (overview) and the queue panel (queue_state) use the same labels and tones. |
| Types: `Overview`, `OverviewDoctor`, `OverviewException`, `Lookup`, `LookupVisit`, `LookupPatient`, `WalkinResult`, `AppointmentView`, `Policy`, `AlertRow` | `api/types.ts` | Shapes are in the data mapping below. |

---

## 1. FRONT DESK `/app/front-desk`: frame 02 (2:25); states 21 (4:3942) and 22 (4:4081)

Frames 21 and 22 are identical to 02 except for the footer line (§1.8). Workspace 1152 × 884.

### 1.1 Page header (y0–63) → `PageHeader`
| Element | Figma | Spec |
|---|---|---|
| Title "A smooth start to every visit." | x0 y0, 377×39 → **27 / 600 ink** | static copy |
| Sub "Register, verify and check patients in without l…" | x0 y44, h19 → **13 / 400 muted** | static copy |
| "+ New patient" | instance x982 y3, **170×44**, primary | ADAPT: there is no separate registration endpoint. The button focuses (and scrolls to) the walk-in "Full name" field. `Button kind="primary"`. |
| (added) "Open waiting room display" | not in 02; the same instance in 04 is 267×44 secondary | `<a className={buttonClass("secondary")} target="_blank" rel="noopener">` placed left of "+ New patient", 16 gap. Legacy workflow: "waiting-room display link". |
| (added) check-in code line | not in Figma | One line under the sub, 13 muted: "Check-in code today **{checkin_code}** · {require_checkin_code==='1' ? 'patients need it to check themselves in' : 'not required at the moment'}". Code in 600 ink with tabular numbers. Legacy workflow. |

### 1.2 Appointment lookup panel: y92, 1152×94, white, radius 8 (`--r-panel`)
| Element | Figma | Spec |
|---|---|---|
| Container | rel(0,92) 1152×94, padding 16 top / 24 sides | `Panel` with a tighter top padding (16), or a plain section with `.panel` styles. Name the region by the label below. |
| Label "Find a patient or appointment" | x24 y16, h20 → **14 / 600 ink** | Real `<label>` for the search input (TextField `label`, restyled to 14/600). |
| Search input | x24 y44, **750×36**, placeholder 12 muted (h17) | `TextField` control. **Use 44 high** (the 44 px target rule; the button beside it is 44) and bottom-align with the button. Placeholder: "Search by name, phone, username or token". |
| "⌘ K" hint | x689 inside the input, 11 muted | OMIT: no such shortcut exists in the app, so no hint for a shortcut that does nothing. |
| "Find appointment" | instance x806 y36, **322×44**, primary (the input's right edge to the button is 32) | `Button type="submit"` labelled "Search" or "Find patient". The form submits GET /api/lookup?q=. |
| (added) Results region | not in Figma | Below the input row, inside the same panel (the panel grows). Two lists: **"Today's visits (n)"** and **"Patient accounts (n)"**. Each has an Overline heading (10/600 muted) and rows using the QueueTable row metrics (58 px + 1 px `--line` rule, token 16/600, name 13/500, sub 11 muted). A `Message` shows "{n} on today's list, {m} patient accounts." Nothing found → `EmptyState title="Nobody matches."`. |
| Visit row actions | | `Details` (opens Appointment found 4:2227), `Check in` (only when status is `booked` or `skipped`; skipped is labelled "Check in · end of queue"), `Open queue` (link to `/app/queue-monitor?doctor={doctor_id}`). Secondary buttons 36 high like `.rowActions`. |
| Patient-account row actions | | `Token with {selected walk-in doctor}` (POST /api/staff/walkin {patient_id, doctor_id}; disabled until a doctor is chosen in the walk-in form, the same as legacy), and `Reset password…` (hidden when `guardian` is set, because the server refuses family members). |

### 1.3 Walk-in registration panel: rel(0,210), 716×638, white, radius 9, 24 inset
Measured grid: two columns, **320 | 24 gap | 324**, inner width 668.

| Element | Figma | Spec |
|---|---|---|
| Title "Walk-in registration" | x24 y22, h28 → **19 / 600** (Panel title is 18: accept 18) | `Panel title` |
| "New visit" pill | x599 y20, 71×25 | `Status tone="info"` in Panel `aside`. Text: "Walk-in". (The tone can't be read from the outline; info is the closest meaning.) |
| Steps "01 Patient details · 02 Visit details · 03 Check-in" | y66, 13/500 (h19), divider at y101 668 wide | OMIT the step row: the form is one step and the server creates the visit and checks it in atomically, so a wizard would be misleading. Keep the divider at y101 → becomes the panel-head rule. |
| "Full name *" + input | label y124 (12/500), input y149 **320×44** | `TextField name="name" required`. Figma placeholder value "Kavita Joshi" → empty field, no sample value. |
| "Mobile number *" + input | x368 y124, input **324×44** | `TextField name="phone" type="tel"`. ADAPT: **optional** (server: `phone` optional; valid_contact pattern `\+?[0-9 ]{7,16}`). Label "Phone for alerts (optional)". Hint (12 muted): "Without a phone the patient gets no SMS alerts." |
| "Age *" 145 + "Gender *" 151 | y220/245 | OMIT: not stored. Row 2 becomes **Alert language** (320, `SelectField name="lang"` from `LANGS`, default en) on the left. |
| "Patient identifier" (324, "Auto-generated on registration") | x368 y220 | ADAPT: disabled `TextField label="App username"` with placeholder "Created when you save". The server does generate `walkin-xxxx` and returns it. No value until then. |
| Divider | y310, 668 | `<hr>` `--line` |
| "Visit details" | x24 y329, h20 → **14 / 600** | sub-heading |
| "Department *" 320 | y367/392 | `SelectField required`. Options are the distinct departments among overview doctors that hold OPD and are not unavailable. |
| "Doctor / session *" 324 | x368 y367/392 | `SelectField label="Doctor *" required`. Options: doctors in the chosen department with `holds_opd && status !== "unavailable"`. Text "{name} · OPD {clock(opd_start)}–{clock(opd_end)}" (append " · fully booked" when departments `full`; staff can still book and get a warning). "Morning" session → OMIT (one OPD session per day; no sessions concept). Placeholder option "Choose a doctor" (no default doctor). |
| "Reason for visit" 668×44 | y463/488 | OMIT: not stored. The panel closes the gap. |
| Status line "● Queue open · 12 waiting · Approx. 96–112 min …" | x24 y551, h17 → **12 / 500**, dot coloured by tone | ADAPT: "● {doctorStatus.label} · {waiting} waiting · queue clears around {clock(clears_at)}". Omit the clears part when `clears_at` is null. **No wait range.** Shown only after a doctor is chosen. Dot colour uses the consultation `.dot` tone classes. |
| Footer divider | y581, full panel width 716 (edge to edge) | |
| "Required fields are marked *" | x24 y604, h16 → **11 / 400 muted** | static |
| "Save & check in" | x448 y590, **244×44** primary | `Button type="submit"`. POST /api/staff/walkin {name, phone, lang, doctor_id}. Success → `TokenIssuedDialog` (§1.9), form reset, footer line (§1.8). Refusal → `Message` with the server text (e.g. "Dr X is not available today…"). |

### 1.4 Session visibility card: rel(740,210), 412×260, white, radius 9, 24 inset
Follows the **doctor selected in the walk-in form**. With no doctor chosen → `EmptyState title="Choose a doctor"`: "Their queue status appears here."

| Element | Figma | Spec |
|---|---|---|
| "General medicine" | x24 y22, h25 → **17 / 600** | `department` |
| "Dr. Aisha Mehta · Room 104" | y52, h17 → **12 / 400 muted** | "{name} · OPD {opd_start}–{opd_end}" (Room → OMIT) |
| Status pill "In consultation" | y83, 103×25 | `Status` from generalised `doctorStatus()` (In consultation = info, Available = success, On a break = caution, Running late / Unavailable = urgent, No OPD today = neutral) |
| Divider | y130, 364 | |
| "12" + "waiting" | y145 h42 → **29 / 600** tabular; label y187 12 muted | `waiting` |
| "96–112 min" + "estimated wait for a new walk-in" | x173 y149 h33 → **23 / 600**; label y187 h16 → 11 muted | ADAPT: value `clock(clears_at)`, label "queue clears around (estimate)". When `clears_at` is null: value "–", label "no estimate (no one waiting or doctor away)". **No range.** |
| "Estimates may change for priority cases." | y226, h16 → 11 muted | static |

### 1.5 Recent check-ins card: rel(740,490), 412×344, white, radius 9, 24 inset
Data: `useQueue(selectedDoctorId)`. Entries with `checked_in_at`, any status, sorted by `checked_in_at` descending. Show the newest **3**.

| Element | Figma | Spec |
|---|---|---|
| "Recent check-ins" | y22 h25 → 17/600 (Panel title 18) | `Panel title` |
| "Today · Counter 02" | y52 12 muted | "Today · {doctor name}" (Counter → OMIT: not stored) |
| Row (×3) pitch **68** (y98, 166, 234), rules at y153/221/289 (364 wide) | token x24 h23 → **16 / 600** tabular; name x86 h19 → **13 / 500**; sub x86 +24 h16 → **11 muted**; "✓" x357 h25 → 17 teal | token `tokenText(token)`, `patient_name`, sub "{clock(checked_in_at)} · {entryStatus(e).label}" ("· Walk-in / Appointment / Follow-up" → OMIT: visit type not exposed to staff). ✓ is `aria-hidden` and shown only for `checked_in`; the status text carries the meaning. |
| "View registration log →" | y310, 13/500 teal | ADAPT: `TextButton` "View all {n} check-ins today →", shown only when n > 3. It opens a `Dialog size="md"` with the full list in the same rows. (No registration log endpoint for staff; `/api/admin/events` is admin-only.) |
| Empty | | `EmptyState title="No check-ins yet today."` |

### 1.6 Patient alerts (alert delivery log), added below the two-column grid
No Figma frame. Built from design-system parts, matching legacy "Patient alerts".
- `Panel title="Patient alerts" sub="Failed alerts never hold up the queue. Patients also see their status in the app."`, full width (1152), 24 below the grid.
- Table with header row styling from QueueTable (10/500 muted caps): CREATED (`hhmm`) · PATIENT · DOCTOR · TOKEN · ALERT (purpose label) · CHANNEL · STATUS (`Status`: failed → urgent, pending → caution, sent/delivered → success, unconfirmed → neutral) · TRIES · DETAIL (11 muted).
- Body scrolls inside the panel (max-height ≈ 420). `EmptyState title="No alerts sent yet."`.
- Data: `useLive(GET /api/admin/notifications)`.

### 1.7 Footer line
- 02: "Patient information is visible only to authorize…" at y857, h16 → **11 / 400 muted**, static copy.

### 1.8 States: 21 Registration saved / 22 Appointment checked in
The footer line becomes the action result at y867: "✓  Kavita Joshi registered and checked in · Toke…", **11 / 500 teal**. Use `Message` (role=status) restyled to 11/500.
- After walk-in: "✓  {patient_name} registered and checked in · Token {tokenText(token)}". If `existing`: "✓  {patient_name} already had a visit with {doctor.name} today · Token {tok} · checked in". If the server rejected, the error goes in `msgErr` red.
- After check-in from lookup (22): "✓  {patient_name} checked in · Token {tok}". For a skipped patient: "✓  {patient_name} checked in · rejoined at the end of the queue · Token {tok}".
- The rest of the page is unchanged in 21 and 22. The dialog (§1.9) opens at the same time.

### 1.9 Dialog: Patient checked in (4:2134) = Appointment token issued (4:4219), 480×585 → `Dialog size="xs"`
One component, `TokenIssuedDialog`, fed by the walk-in reply or the /api/checkin reply.

| Element | Figma | Spec |
|---|---|---|
| Title "Patient checked in" | 28,26 h33 → **23 / 600** | Dialog title |
| Description "The visit is saved and the live queue is updated" | 28,70 h19 → 13 muted | Dialog description |
| Close × | 416,16 44×44 | built into Dialog |
| Issued token box | 28,126 **424×192**, `--tint` bg, radius 9 | div |
| "YOUR TOKEN" | +24,+18 h16 → **11 / 600 teal** | Overline "TOKEN" |
| "034" | +24,+48 h87 → **60 / 600 teal**, tabular | `tokenText(token)` |
| "Kavita Joshi · 34 years · Female" | +24,+143 h20 → 14 / 500 | `patient_name` (age/gender → OMIT) |
| "General medicine · Dr. Aisha Mehta" | 28,343 h22 → **15 / 600** | `{doctor.department} · {doctor.name}` |
| "Room 104 · Morning session" | 28,375 h19 → 13 muted | ADAPT: "{ahead} ahead in the queue" when `ahead != null` (server). A skipped patient's check-in adds "· rejoined at the end of the queue". Room/session → OMIT. |
| "Estimated wait: 104–120 min" | 28,410 h22 → **15 / 600** | ADAPT: "Expected around {clock(eta)} · estimate" when `eta`. Otherwise "No expected time yet" plus the doctor status (break/unavailable). **No range.** |
| "An SMS with the token and tracking link has been…" | 28,448 h17 → 12 muted | ADAPT: if the reply's `notifications[0]` exists, show "{purpose label}: {CHANNEL} {status}". Otherwise OMIT; don't claim an SMS was sent. Walk-in only: "App username: **{username}**. Reset the password from Find a patient if they want to use the app." (server `username`) |
| (added) warning | not in Figma | `Callout tone="caution"` with the server `warning` (capacity problem) when present. |
| Divider | y505, full width | Dialog footer rule |
| "Done" | 28,523 **130×44** secondary | `Button kind="secondary"` |
| "Print token" | 174,523 **278×44** primary (16 gap; no space-between) | opens `TokenSlipDialog`. Footer layout: `justify-content:flex-start`, Print grows to fill. |

### 1.10 Dialog: Token print preview (4:4481) = Appointment token print preview (4:4490), 560×590 → `Dialog size="sm"`
No close × and no description in Figma. Keep the Dialog close button anyway (Escape/close is a Dialog contract and an accessibility basic).

| Element | Figma | Spec |
|---|---|---|
| Title "Token print preview" | 28,28 h33 → 23/600 | Dialog title |
| "Riverside Hospital · General medicine" | 28,103 h20 → 14 / 500 | `doctor.department` (hospital name → OMIT, §1.8 of the migration doc) |
| "034" | 28,153 h99 → **68 / 600** tabular | `tokenText(token)` |
| "Kavita Joshi · UHID RH-009873" | 28,265 h25 → **17 / 600** | `patient_name` (UHID → OMIT) |
| "Dr. Aisha Mehta · Room 104 Morning session · 09 …" | 28,315 490×66, about 3 lines at 15 (or 2 at 23; can't tell from the outline) → use **15 / 400**, line breaks as written | "{doctor.name}" / "OPD {opd_start}–{opd_end} · {longDate(day)}" / "Checked in {clock(checked_in_at)}" (Room/session → OMIT) |
| "Keep this token. Track your turn using the SMS l…" | 28,437 490×38 → 2 lines of **13 muted** | ADAPT: "Keep this token. Watch the waiting-room screen for your number; times are estimates." (static and true: the display shows tokens) |
| "Done" | 28,520 **504×44** (full width) | ADAPT: Figma has no print trigger. Footer = `Done` (secondary) + `Print` (primary, calls `window.print()`), each half width. |
| Print CSS | | `@media print`: hide everything except the open slip (`dialog[open] .slip`). The slip contains only the fields above (all from the server reply). |

### 1.11 Dialog: Appointment found (4:2227), 680×534 → `Dialog size="wide"`
Opened from a lookup visit row (`Details`). It also loads `useQueue(row.doctor_id)` to read the entry (`turn_missed`, `can_skip`, `ahead`, `eta`) and the `version` needed for Reinsert next.

| Element | Figma | Spec |
|---|---|---|
| Title "Appointment found" | 28,26 → 23/600 | |
| Description "Confirm patient identity and appointment before …" | 28,70 → 13 muted | static copy |
| "Patient search" label + 624×44 input | 28,127 / 28,152 | OMIT: search lives in the lookup panel. The body starts with the name line, about 40 below the description (Dialog `.body` padding). |
| "Priyanka Das · 31 years · Female" | 28,223 h28 → **19 / 600** | `patient_name` |
| "UHID RH-003872 · Appointment AP-1048" | 28,260 h19 → 13 muted | "Token {tok} · Mobile ending {phone.slice(-4)}" (when `phone`) (UHID / appointment code → OMIT) |
| Verification box | 28,303 **624×87**, `--tint`, radius 7 | div; tone follows the state below |
| "✓  Appointment verified" | +14,+12 h20 → **14 / 600 teal** | state title (below) |
| "Today, 10:45 AM · Dr. Aisha Mehta · Room 104" | +14,+45 h19 → 13 ink | "Today · {doctor} · {expected around clock(eta) \| status label}" (Room → OMIT) |
| "✓  Patient identity confirmed using name and mob…" | 28,416 h17 → **12 / 500 teal** | ADAPT to an instruction (no backend verification): "Confirm the name and mobile number with the patient before checking in." 12 muted, no ✓. |
| Divider | y454 full width | |
| "Cancel" | 28,472 **112×44** secondary | close |
| "Check in & issue token" | 412,472 **240×44** primary | state-dependent label (below). POST /api/checkin → close → `TokenIssuedDialog` + footer line. |

States of the verification box and primary action (late vs missed rules A/B):
| Server state | Box (tone) | Primary | Extra |
|---|---|---|---|
| `booked`, not `turn_missed` | tint/teal "✓ Booked for today" | "Check in" | – |
| `booked` + `turn_missed` (late within grace) | `--amber-tint`/amber "Turn passed · grace period running" (or "grace period over" when `can_skip`) | "Check in · keeps their place" | Callout info: "Checking in now keeps their original place in the queue." |
| `skipped` (same day) | `--amber-tint`/amber "Skipped at their turn" + `skip_reason` | "Check in · rejoin at end" | Callout caution: "**Checking in puts {name} at the end of {doctor}'s queue.** The visit stays on record." A secondary `Reinsert next…` (danger-text TextButton, labelled "Policy exception") opens `ReinsertNextDialog`. It must be offered **instead of** check-in: after check-in the status is no longer `skipped`, and the server only reinserts skipped visits. |
| `checked_in`, `called`, `in_consultation` | neutral "Already {status label}" | none (Close only) | – |
| `completed` / `cancelled` | neutral "Completed" / "Cancelled" | none | Never reschedule; no rebook action here. |

---

## 2. QUEUE MONITOR `/app/queue-monitor`: frame 04 (2:33)

Selected doctor = URL `?doctor={id}` (front desk "Open queue" links set it). Default: the first overview doctor holding OPD. Data: `useLive(GET /api/admin/overview)`, `useQueue(selectedId)`, `GET /api/admin/policy` (categories, display_key).

### 2.1 Page header (y0–63) → `PageHeader`
| Element | Figma | Spec |
|---|---|---|
| "Every queue. One clear picture." | 409×39 → 27/600 | static |
| "Live OPD flow across departments · Last updated …" | y44 h19 → 13 muted | "Live OPD flow across departments · Last updated {clock(overview.updated_at)}" |
| "Open waiting room display" | x885 y3 **267×44** secondary | `<a className={buttonClass("secondary")} href={"/?display=" + display_key} target="_blank" rel="noopener">`. This is the legacy display URL, which works today and is the printed and shared link; switch it to `/app/display?key=` when the Display milestone ships. |

### 2.2 Monitoring filters bar: y92, 1152×64, white, radius 8, padding 10 / 16
| Element | Figma | Spec |
|---|---|---|
| "All departments ⌄" | x16 y10 **223×44** | `SelectField` (visually hidden label "Department") filtering the session cards client-side by `department`. Display filter only. |
| "Morning session ⌄" | x255 y10 222×44 | OMIT: one OPD session per day; no session concept on the server. |
| "4 active sessions" | x763 y23 h17 → 12 muted | "{n} doctors holding OPD" = count of overview doctors with `holds_opd && status !== "unavailable"` |
| "● Live updates" pill | x990 y19 109×25 | `Status tone={live ? "success" : "caution"}` text "● Live updates" / "● Reconnecting…" from `useStreamLive()` |

### 2.3 Session cards: y180, 4 × **270×238**, 24 gap (exactly 1152), white, radius 9, **20 inset**
Grid `repeat(auto-fill, minmax(250px, 1fr))`, gap 24 (more than 4 doctors wrap). Each card is a `<button aria-pressed>` that selects the doctor. Selected card: 1 px `--teal` border (ADAPT: Figma shows no selection state).

| Element | Figma (card-relative) | Spec |
|---|---|---|
| Department | 20,20 h25 → **17 / 600** | `department` |
| Doctor | 20,51 h17 → **12 / 500 ink** | `name` |
| "Room 104" | 20,72 h16 → 11 muted | ADAPT: "OPD {opd_start}–{opd_end}" (Room → OMIT) |
| Status pill | 20,104 (h25) | generalised `doctorStatus()`: "In consultation" when `current_status === "in_consultation"`, "Called {tok}"-style info when `called`, "Available", "On a break", "Running late", "Unavailable", "No OPD today" |
| Waiting number + "waiting" | 20,148 h42 → **29 / 600**; label 60,164 h16 → 11 muted (inline, baseline) | `waiting` |
| "~8 min" + "next call" | 158,151 h33 → **23 / 600**; label 158,184 → 11 muted | ADAPT: overview supplies no per-doctor next-call ETA, so this slot shows **"{clock(clears_at)}" / "queue clears"**. When `clears_at` is null: "–" / "no estimate". Next-call ETAs show per row in the selected doctor's live queue (EST. WAIT), from the server. No N parallel /api/queue fetches. |
| Footnote "On track" / "+15 min delay" / "Resumes 10:45" | 20,212 h16 → **11 / 500**, tone colour | Priority order: break → "Resumes {clock(break_until)}" (amber); delayed → "Running late until {clock(break_until)}" (red); congestion `over capacity` → "Over capacity · runs past {opd_end}" (red); `busy` → "Busy" (amber); `normal` → "Normal load" (teal). "On track" → ADAPT: the server reports load, not ETA adherence. |
| (optional, server) | not in Figma | "{completed} done · {skipped} skipped" 11 muted under the footnote, plus "Now {tok}" when `current_token`. Covers the legacy overview columns (current token, done / skipped). Avg consult → "avg {avg_minutes} min". Without these the legacy overview table loses data, so keep them; the card grows to fit. |

### 2.4 Live queue panel: rel(0,442), **760×398**, white, radius 9
| Element | Figma (panel-relative) | Spec |
|---|---|---|
| Title "General medicine · Live queue" | 24,22 h26 → **18 / 600** | `Panel title={`${doctor.department} · Live queue`}` |
| "Room 104 / Dr. Aisha Mehta" | 24,52 h17 → 12 muted | "{doctor.name} · {doctorStatus(q).label} · OPD {opd_start}–{opd_end}" (Room → OMIT) |
| "12 waiting" pill | 638,20 76×25 | `Status tone="neutral"` "{n} waiting" (n = entries with `ahead != null`) |
| (added) Queue controls row | not in Figma | ADAPT, needed for legacy staff parity: a row under the head, 12 top / 12 bottom, buttons 44 high: **Call next patient** (primary; `act("call_next")`; show `called` or `message` from the reply), **Doctor status…** (secondary → generalised `AvailabilityDialog`, title "{doctor.name} · availability", same 4 options + minutes → `setStatus`), **Move all waiting…** (secondary → `MoveDialog` all → `act("transfer_all", {to_doctor_id})`; show the server `message`). Wraps on narrow widths. |
| Table header strip | 0,88 **760×36**, `--bg` fill, edge to edge | QueueTable `<thead>` |
| Headers | POS. x24 · TOKEN / PATIENT x92 · ARRIVAL x367 · STATUS x468 · EST. WAIT x640; h15 → **10 / 500 muted** | column template inside 24 inset: **68 · 275 · 101 · 172 · 96** (+ actions). ARRIVAL/STATUS are 93/180 measured from the pill at 460. |
| Rows | first text y146, pitch **54** (rules at 185/239/293/347, 712 wide) | `QueueTable dense pos arrival`: POS "01" = `ahead+1` 2-digit, **12 / 400 muted**; "025  Sunita Patel" one line, token 13/600 tabular + 2 spaces + name 13/500; ARRIVAL `clock(checked_in_at)` or "—", 12 muted; STATUS `Status` from `entryStatus()`; EST. WAIT `etaText(e,q)` 12/500 muted ("Pending" when no eta, "On hold" on break). |
| (added) Row action | not in Figma | Last column, **120**, one `Button kind="secondary"` "Actions" (36 high) → `PatientActionsDialog` (§2.7). Keeps one control per row instead of up to 9 buttons. |
| Rows shown | 4 in Figma | First **4** entries with `ahead != null`, in server order. Current patient (called / in consultation) is not a row; it shows as "Now {tok} · {status}" text in the sub line. |
| "View complete queue →" | 24,369 h17 → 13/500 teal | `TextButton` → FullQueueDialog (§2.6) |
| Empty | | `EmptyState title="All caught up."` "No patients are waiting for {doctor}." |
| Loading / error | | `LoadingState rows={4}` / `ErrorState` with a "Try again" button calling `refresh` |

### 2.5 Needs attention panel ("Delays & exceptions"): rel(784,442), **368×398**, white, radius 9, 24 inset
| Element | Figma | Spec |
|---|---|---|
| "Needs attention" | 24,22 h26 → 18/600 | `Panel title` |
| Count pill "2" | 311,20 26×25 | `Status tone="caution"` with the item count (neutral "0") |
| Item title "Cardiology running 15 min late" | 24,84 h19 → **13 / 600** (320 wide) | items below |
| Item sub "9 patients notified. New ETA includes the delay." | 24,111 h17 → 12 muted | items below |
| Dividers | y167, y315 (320 wide) | between items |
| "2 patients missed their call" / "General medicine · Confirm arrival before reinse…" | 24,190 / 24,217 | selected-queue late item |
| "Review skipped patients →" | 24,271 13/500 teal | `TextButton` → SkippedLateDialog (staff variant) |
| Footer notes "Estimates are ranges, not promises." / "Priority cases may change queue order." | 24,337 h17 (12) / 24,359 h16 (11), muted | ADAPT the first to "Estimates are estimates, not promises." (the app shows single times, not ranges). The second is static. |

Item sources, in order (all server data). The list scrolls inside the panel when long.
1. Doctors in overview with status `delayed` → "{department} running late · until {clock(break_until)}" / "Waiting estimates include the delay." ("9 patients notified" → OMIT: no per-doctor alert count.) `break` → "{name} on a break · back {clock}". `unavailable` while `holds_opd` → "{name} unavailable today". `congestion === "over capacity"` → "{name}'s queue runs past {opd_end}".
2. Selected queue: `entries.filter(isLate)` count > 0 → "{n} patients missed their call" / "{department} · Confirm arrival before reinserting." + "Review skipped patients →".
3. `failed_alerts > 0` → "{n} patient alerts failed today" / "Patients still see their status in the app." (TextButton → front desk alert log, `/app/front-desk#alerts`).
4. **Today's exceptions** (legacy "Today's exceptions"): `overview.exceptions` newest first. Each line: "{clock(at)} · {doctor} · token {tok}" (12 muted) over "{action with _ → space}{detail ? ': ' + detail : ''}" (13/500). This could go in a TextButton "Today's exceptions ({n}) →" opening a `Dialog size="lg"` table (Time · Doctor · Token · What · Detail) to keep the panel at Figma height. Recommended.

### 2.6 Dialog: Full queue (4:3874), 760×820 → generalised `FullQueueDialog size="lg"`
| Element | Figma | Spec |
|---|---|---|
| Title "General medicine · Full queue" | 28,24 h35 → **24 / 600** (Dialog title is 23: accept) | `{department} · Full queue` |
| Sub "12 waiting · 9 checked in · 3 not arrived · Room…" | 28,70 13 muted | counts of the server entries shown: "{waiting} waiting · {checked_in} checked in · {booked} not arrived" (Room → OMIT) |
| Rows | token x28 (h20 → 14/600), name x108 (13/500), status x408 (12; Figma plain text → use `Status` pill for consistency with frame 04), wait x640 (12 muted); pitch **48**, rule 35 below the text, 704 wide | `QueueTable` with `actions` render prop. Staff → "Actions" button → §2.7. Doctor (consultation) keeps its Not here / No-show buttons. Refactor `FullQueueDialog` to take `actions` instead of `onNotHere/onNoShow`. |
| "~8 min" / "Pending" | x640 | `etaText` |
| Footer note "Token numbers are assigned at booking; only chec…" | 28,729 h16 → 11 muted | static: "Token numbers are assigned at booking; order follows clinical priority, then check-in." (true per engine) |
| "Close queue" | 472,757 **260×44** | Footer with the note on the left and `Button kind="secondary"` "Close" on the right (min 260). |

### 2.7 Patient actions (no Figma frame) → `PatientActionsDialog size="md"`
Title "Token {tok} · {patient_name}", description `entryDetail(e)`. Body: a vertical list of full-width secondary buttons. Each is shown **only when the server state allows it** (same gates as legacy index.html lines 416–430):
| Button | Shown when | Calls |
|---|---|---|
| Check in | status `booked` | POST /api/checkin → refresh. Late within grace: label "Check in · keeps place". |
| Check in · end of queue | status `skipped` | POST /api/checkin → refresh (server puts them at the end; reply shows `ahead`) |
| Reinsert next… *(policy exception)* | status `skipped` | `ReinsertNextDialog` → `act("reinsert_front", {appointment_id, reason})` |
| Not here… | status `called` or `checked_in` | `NotHereDialog` (existing) → `not_present` |
| Skip / no-show… | `can_skip` | `NoShowDialog` (existing) → `skip` |
| Emergency priority… | waiting and not `emergency` | `EmergencyDialog` → `emergency` (reason required) |
| Priority category… | waiting and no `priority` | `PriorityDialog` → `priority {category}` |
| Remove priority… | `priority` | `RemovePriorityDialog` → `remove_priority` (reason required) |
| Move to a colleague… | waiting | `MoveDialog` → `transfer {to_doctor_id}` |
| Cancel visit… | waiting | `CancelVisitDialog` → POST /api/cancel {appointment_id, reason?} → refresh |
"Waiting" = status in `booked/checked_in` (server WAITING). Every queue action sends `version`. Refusals → `FailureDialog` (existing 4:2200).

### 2.8 Reason dialogs (pattern 4:2080, 560×412 → `Dialog size="sm"`)
Layout from 4:2080: field label at 133 (12/500), input **504×44** at 158; notice box at 231 **504×65** (`Callout`, title 14/600 at +10, sub 12 at +35); divider at 332; footer Cancel **112** left, primary **240** right. Reuse the existing `footer()` helper and `.cancelBtn/.primaryBtn`.
| Dialog | Field | Callout | Primary |
|---|---|---|---|
| `EmergencyDialog` | `TextField "Reason *" required` | urgent: "**Goes above every priority category.** Logged with your name." | danger "Give emergency priority" |
| `PriorityDialog` | `SelectField "Category *"` from `policy.priority_categories` split by "," | caution: "Ranked after emergencies and before routine patients." | "Set priority" |
| `RemovePriorityDialog` | `TextField "Reason *" required` | caution: "Was {priority}. The reason is kept on record." | "Remove priority" |
| `ReinsertNextDialog` | `TextField "Reason for the exception *" required` | caution: "**Policy exception.** {name} goes next instead of rejoining at the end. Logged with your name and reason." | "Reinsert next" (title "Reinsert token {tok} next?") |
| `CancelVisitDialog` | `TextField "Reason (optional)"` | caution: "The patient is told the visit was cancelled." | danger "Cancel visit" |
| `MoveDialog` (one / all) | `SelectField "Move to *"`: overview doctors with the same `department_id`, `id !== current`, `holds_opd`, `status !== "unavailable"`. None → `EmptyState` "No other doctor in this department is holding OPD now." | info: "They join the end of {to}'s queue and are told." / all: "Everyone still waiting moves, in queue order." | "Move patient" / "Move all waiting" |

`EmergencyDialog`'s visual reference for the later Emergency milestone is 4:2114 (600×558: summary box 544×98 at 127, divider 362, "APPROVING AS" overline 385). Its "P1", "Nurse", "Requested by", "E01" and impact-preview ("024 continues → E01 next…", "13 patients will wait") elements are **OMIT**: no such data, and the preview would need client-side queue simulation.

### 2.9 Dialog: Skipped & late patients (4:2152), 600×478 → generalised `SkippedLateDialog size="md"`
| Element | Figma | Spec |
|---|---|---|
| Title | 28,26 → 23/600 | "Skipped & late patients" |
| Description "Confirm arrival before reinserting. No visit is …" | 28,70 13 muted | staff: "Confirm arrival first. No visit is deleted." |
| Row card | 28,128 **544×92**, `--bg`, radius 7; next row 236 (16 gap) | existing `.lateRow` |
| Token | +16,+18 h35 → **24 / 600** | `.lateToken` |
| Name | 112,143 h22 → **15 / 600** | `.lateName` |
| "Called 10:02 AM · Patient now present" | 112,173 h17 → 12 muted | `entryDetail`-style: skipped → "Skipped · {skip_reason}"; turn_missed → "Turn missed · grace period running/over". "Called HH:MM" → OMIT (no call time in queue_state). "Patient now present / Not yet returned" → OMIT (no presence data). |
| (row actions) | not in Figma | staff variant via an `actions` prop: skipped → "Check in · end of queue" + "Reinsert next…"; turn_missed → "Check in · keeps place"; `can_skip` → "Skip / no-show…". Doctor variant unchanged. |
| "✓  Arrival confirmed for Ritu Kapoor · Token 021" | 28,365 h17 → 12/500 teal | `Message` with the result of the last action from the server reply (e.g. "✓ Ritu Kapoor checked in · rejoined at the end · Token 021") |
| Footer Cancel 112 / "Reinsert 021 after next" 240 | 28,416 / 332,416 | ADAPT: per-row actions replace the single footer primary. Footer = Close (secondary). The server's reinsert_front puts the patient **next**, not "after next", so never use the Figma wording. |

---

## 3. Responsive (frame 07 rules + AppShell breakpoints)

| Width | Front desk | Queue monitor |
|---|---|---|
| ≥1280 | As measured: lookup full width; grid `716fr 24 412fr` (`minmax(0,716fr) minmax(0,412fr)`); right column = session (260) + 20 gap + recent (344); alert log full width below. | Filters bar; session cards auto-fill (4 across at 1152); `760fr 24 368fr` row for live queue + needs attention. |
| 768–1279 (shell icon rail 72, workspace 24 inset) | Lookup input + button wrap (button full width under 900). Grid → one column: walk-in full width, then session + recent **side by side** (2 equal columns) ≥1024, stacked below 1024. Walk-in keeps 2 field columns. | Cards 2–3 across (auto-fill). Live queue full width, needs attention below it, full width. Queue controls wrap. |
| <768 (drawer nav, 16 inset) | One task per view, stacked in this order: lookup, walk-in, session, recent, alerts. Walk-in fields one column. Header actions full width. Result rows: QueueTable mobile template (48 · 1fr · auto, actions on their own line). Alert log becomes stacked rows (no table scroll). Title 22. | Filters stack (select full width, count + live pill on one line). Cards one column. Live queue: QueueTable mobile rules, with POS and ARRIVAL folded into the sub line ("#01 · arrived 10:11 AM"). Needs attention below. Dialogs are already `min(w, 100vw−32)`. Nothing scrolls sideways. |

---

## 4. DATA MAPPING (every Figma text or value → backend source)

Endpoints: **OV** = GET /api/admin/overview `{doctors[], exceptions[], failed_alerts, updated_at, opd_end}`. OV.doctor = queue_state.doctor `{id,name,department,department_id,status,break_until,holds_opd,opd_start,opd_end}` + `{waiting,current_token,current_status,avg_minutes,clears_at,congestion,completed,skipped,emergencies}`. **Q** = GET /api/queue?doctor_id (queue_state). **LK** = GET /api/lookup?q → `results[] {id,token,status,day,patient_name,phone,doctor,doctor_id}`, `patients[] {id,username,name,phone,guardian}`. **WI** = POST /api/staff/walkin → `{existing, warning?, username, ...appointment_view}`. **AV** = appointment_view `{...queue entry (id,token,patient_name,status,emergency,priority,checked_in_at,skip_reason,turn_missed,can_skip,ahead,eta), doctor{...}, day, updated_at, arrival_alert, notifications[≤3]{purpose,channel,status,created_at,updated_at}, patient_id, checkin_opens_at, checkin_code_required}` (also the reply of POST /api/checkin and /api/cancel). **POL** = GET /api/admin/policy `{...policy, checkin_code, display_key}`. **NT** = GET /api/admin/notifications `notifications[] {id,purpose,channel,status,attempts,created_at,updated_at,detail,patient,token,doctor}`. **DEP** = GET /api/departments (`doctors[].full`, `bookable`).

### Front desk (02 / 21 / 22)
| Figma text / value | Source |
|---|---|
| "A smooth start to every visit." / "Register, verify and check patients in…" | static copy |
| "+ New patient" | UI action (focus walk-in form); no data |
| "Find a patient or appointment" / "Find appointment" | static; submits LK |
| "Search by name, UHID, mobile number or appointment…" | ADAPT → "name, phone, username or token" (what LK matches); UHID OMIT: not stored |
| "⌘ K" | OMIT: no such shortcut |
| "Walk-in registration" | static |
| "New visit" pill | static "Walk-in" |
| "01 Patient details / 02 Visit details / 03 Check-in" | OMIT: single atomic step |
| "Full name *" → "Kavita Joshi" | user input → WI.name; no sample value |
| "Mobile number *" → "+91 98765 43210" | user input → WI.phone (**optional** on server); placeholder may show the format "+91 98765 43210", as legacy does |
| "Age *" "34", "Gender *" "Female" | OMIT: not stored |
| "Patient identifier" "Auto-generated on registration" | ADAPT → "App username": server-generated, shown from WI.username after save |
| (legacy) Alert language | user input → WI.lang (LANGS) |
| "Department *" "General medicine" | OV.doctors[].department (distinct, eligible doctors) |
| "Doctor / session *" "Dr. Aisha Mehta · Morning" | OV.doctors[] filtered `holds_opd && status!=='unavailable'` → name, opd_start/opd_end; "Morning" OMIT: no sessions; "fully booked" from DEP.full |
| "Reason for visit" "Headache and dizziness" | OMIT: not stored |
| "● Queue open · 12 waiting · Approx. 96–112 min" | doctorStatus(OV row).label · OV.waiting · clock(OV.clears_at); range OMIT: would need client-side simulation |
| "Required fields are marked *" | static |
| "Save & check in" | POST /api/staff/walkin |
| Session "General medicine" | OV.department |
| "Dr. Aisha Mehta · Room 104" | OV.name · OV.opd_start–opd_end; Room OMIT: not stored |
| "In consultation" | OV.current_status === "in_consultation" → else OV.status / holds_opd via doctorStatus |
| "12" "waiting" | OV.waiting |
| "96–112 min" "estimated wait for a new walk-in" | ADAPT → clock(OV.clears_at) "queue clears around (estimate)"; range OMIT |
| "Estimates may change for priority cases." | static |
| "Recent check-ins" | static |
| "Today · Counter 02" | "Today · " + Q.doctor.name; Counter OMIT: not stored |
| "033" / "Arjun Verma" | Q.entries[].token (tokenText) / patient_name, filtered `checked_in_at`, sorted desc |
| "10:29 AM · Walk-in / Appointment / Follow-up" | clock(Q.entries[].checked_in_at) · entryStatus label; visit type OMIT (walk-in flag only in admin-only events; follow-up not stored) |
| "✓" | decorative for status `checked_in` |
| "View registration log →" | ADAPT → "View all n check-ins today →" (Q data); a registration log OMIT: /api/admin/events is admin-only |
| "Patient information is visible only to authorize…" | static |
| (legacy) display link | POL.display_key → `/?display={key}` |
| (legacy) check-in code | POL.checkin_code, POL.require_checkin_code |
| (legacy) lookup result rows | LK.results[] / LK.patients[] (`guardian` hides Reset password) |
| (legacy) reset password result "They sign in as {username}" | POST /api/staff/patient-password → `username` |
| (legacy) Patient alerts table | NT.notifications[] |
| 21/22 "✓ Kavita Joshi registered and checked in · Token 034" | WI.patient_name / WI.token (WI.existing changes the wording); 22: AV.patient_name, AV.token, prior status skipped → "rejoined at the end" |

### Patient checked in / Appointment token issued (4:2134, 4:4219)
| Figma | Source |
|---|---|
| "Patient checked in" / "The visit is saved and the live queue is updated" | static |
| "YOUR TOKEN" "034" | WI.token / AV.token |
| "Kavita Joshi · 34 years · Female" | patient_name; age/gender OMIT: not stored |
| "General medicine · Dr. Aisha Mehta" | AV.doctor.department · AV.doctor.name |
| "Room 104 · Morning session" | ADAPT → "{AV.ahead} ahead" (+ "rejoined at the end" for a skipped check-in); room/session OMIT |
| "Estimated wait: 104–120 min" | ADAPT → "Expected around clock(AV.eta) · estimate" (or minutesBetween(AV.updated_at, AV.eta)); range OMIT; null eta → "No expected time yet" |
| "An SMS with the token and tracking link has been…" | AV.notifications[0] {purpose, channel, status} if present, else OMIT (no tracking link exists; don't claim a send) |
| (added) username / warning | WI.username, WI.warning |
| "Done" / "Print token" | UI |

### Token print preview (4:4481, 4:4490)
| Figma | Source |
|---|---|
| "Token print preview" | static |
| "Riverside Hospital · General medicine" | AV.doctor.department; hospital name OMIT: not stored |
| "034" | AV.token |
| "Kavita Joshi · UHID RH-009873" | AV.patient_name; UHID OMIT |
| "Dr. Aisha Mehta · Room 104 Morning session · 09 …" | AV.doctor.name; "OPD {AV.doctor.opd_start}–{opd_end}"; longDate(AV.day); clock(AV.checked_in_at); room/session OMIT |
| "Keep this token. Track your turn using the SMS l…" | ADAPT static copy (no SMS tracking link exists) |
| "Done" | UI (+ added "Print" → window.print) |

### Appointment found (4:2227)
| Figma | Source |
|---|---|
| "Appointment found" / "Confirm patient identity and appointment before…" | static |
| "Patient search" "Priyanka Das · Mobile ending 6721" | OMIT the input (search is on the page) |
| "Priyanka Das · 31 years · Female" | LK.results[].patient_name; age/gender OMIT |
| "UHID RH-003872 · Appointment AP-1048" | ADAPT → "Token {LK.token} · Mobile ending {LK.phone last 4}"; UHID / appointment code OMIT |
| "✓ Appointment verified" | state from LK.status + Q entry (`turn_missed`, `can_skip`) for doctor_id |
| "Today, 10:45 AM · Dr. Aisha Mehta · Room 104" | "Today · {LK.doctor} · expected around clock(Q.entry.eta)"; room OMIT; no booked slot time exists (tokens, not slots) |
| "✓ Patient identity confirmed using name and mob…" | ADAPT → instruction text; no verification data |
| "Cancel" / "Check in & issue token" | UI / POST /api/checkin (label by state); Reinsert next → POST /api/queue/action reinsert_front {reason, version: Q.version} |

### Queue monitor (04)
| Figma | Source |
|---|---|
| "Every queue. One clear picture." | static |
| "Live OPD flow across departments · Last updated …" | clock(OV.updated_at) |
| "Open waiting room display" | POL.display_key |
| "All departments ⌄" | distinct OV.doctors[].department (client-side filter) |
| "Morning session ⌄" | OMIT: no sessions |
| "4 active sessions" | count OV.doctors[] `holds_opd && status!=='unavailable'` → "{n} doctors holding OPD" |
| "● Live updates" | useStreamLive() |
| Card "General medicine" / "Dr. Aisha Mehta" | OV.department / OV.name |
| "Room 104" | OMIT → OV.opd_start–opd_end |
| "In consultation" / "Delayed" / "Available" / "On break" | doctorStatus(OV row) with OV.current_status |
| "12" "waiting" | OV.waiting |
| "~8 min" "next call" | OMIT on cards (overview has no next-call ETA) → clock(OV.clears_at) "queue clears"; per-patient ETAs in the live queue from Q.entries[].eta |
| "On track" / "+15 min delay" / "Resumes 10:45" | OV.congestion ("Normal load" / "Busy" / "Over capacity"); delayed → clock(OV.break_until); break → "Resumes clock(OV.break_until)"; "+15 min" = minutesBetween(OV.updated_at, OV.break_until) only for `delayed` |
| (legacy) current token, avg consult, done/skipped | OV.current_token, OV.avg_minutes, OV.completed / OV.skipped |
| "General medicine · Live queue" | Q.doctor.department |
| "Room 104 / Dr. Aisha Mehta" | Q.doctor.name (+ status, OPD hours); room OMIT |
| "12 waiting" | count Q.entries `ahead != null` |
| "POS." "01" | Q.entries[].ahead + 1 |
| "025  Sunita Patel" | Q.entries[].token, patient_name |
| "ARRIVAL" "10:11 AM" / "—" | clock(Q.entries[].checked_in_at) / "—" when null |
| "STATUS" "Checked in" / "Not arrived" | entryStatus(Q entry) |
| "EST. WAIT" "~8 min" / "Pending" | etaText(entry, Q) (from Q.entries[].eta, Q.updated_at) |
| "View complete queue →" | UI → FullQueueDialog(Q) |
| "Needs attention" "2" | count of the item list below |
| "Cardiology running 15 min late" | OV.doctors[] status `delayed` + department + minutesBetween(OV.updated_at, break_until) |
| "9 patients notified. New ETA includes the delay." | "9 patients notified" OMIT (no per-doctor alert count); "Waiting estimates include the delay." static and true (compute_etas uses break_until) |
| "2 patients missed their call" | count Q.entries.filter(isLate) |
| "General medicine · Confirm arrival before reinse…" | Q.doctor.department + static copy |
| "Review skipped patients →" | UI → SkippedLateDialog(Q) |
| (legacy) Today's exceptions | OV.exceptions[] {at, action, detail, doctor, token} |
| (legacy) failed alerts | OV.failed_alerts |
| "Estimates are ranges, not promises." | ADAPT static (no ranges shown) |
| "Priority cases may change queue order." | static |
| "Public displays show tokens only. Patient names…" | static (true for /api/display) |

### Full queue (4:3874)
| Figma | Source |
|---|---|
| "General medicine · Full queue" | Q.doctor.department |
| "12 waiting · 9 checked in · 3 not arrived · Room…" | counts over Q.entries (`ahead != null`; status checked_in; status booked); room OMIT |
| "025" "Sunita Patel" | Q.entries[].token / patient_name |
| "Checked in" / "Not arrived" | entryStatus |
| "~8 min" / "Pending" | etaText |
| "Token numbers are assigned at booking; only chec…" | static (adapted wording, true per engine) |
| "Close queue" | UI |

### Skipped & late (4:2152)
| Figma | Source |
|---|---|
| "Skipped & late patients" / "Confirm arrival before reinserting…" | static |
| "021" "Ritu Kapoor" | Q.entries.filter(isLate)[].token / patient_name |
| "Called 10:02 AM" | OMIT: no call timestamp in queue_state |
| "Patient now present" / "Not yet returned" | OMIT: no presence data. Show status: skipped + skip_reason, or turn_missed + can_skip (grace running/over) |
| "✓ Arrival confirmed for Ritu Kapoor · Token 021" | result of the last server reply (AV / Q) |
| "Reinsert 021 after next" | ADAPT → per-row "Reinsert next…" (reinsert_front puts them next; reason required) |

### Never rendered (no backend data), across this milestone
Age, gender, UHID, appointment code (AP-…), room, session (Morning), reason for visit, counter, hospital name/location, visit type (walk-in / appointment / follow-up) for staff, nurse / "Requested by", P1/P2 acuity, call timestamps, presence confirmation, per-doctor notified counts, wait **ranges**, per-doctor next-call ETA on overview cards, and any "who goes next if…" preview (would need client-side queue simulation).
