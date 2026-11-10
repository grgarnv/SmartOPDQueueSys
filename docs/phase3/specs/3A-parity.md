# 3A legacy parity spec: Front desk and Queue monitor

Sources: app/index.html (legacy UI, lines cited as `html:N`), app/server.py (`py:N`), app/engine.py (`eng:N`).
Every error string below is copied from server.py. All errors arrive as HTTP status + `{"error": "<message>"}` (py:1727).
The React `api()` already throws `ApiError(message, status)`; show `message` as-is.
Generic errors any call can return:
- 401 "Please sign in." (no session)
- 403 "You do not have permission for this action." (role not in the route's list, py:1712)
- 400 "Missing field: X."
- 400 "X is too long (at most 200 characters)."
- 400 "Invalid value for X."
- 409 "That conflicts with existing data. Refresh and try again." (IntegrityError)
- 500 "Something went wrong on the server. Nothing was saved."

Every POST calls `bump()`, so every open screen gets an SSE message on `/api/stream` (py:1716).

---

## 0. Legacy screen layout (what we are replacing)

- **Staff** (`staffView`, html:570): one page with Workload overview + exceptions → Front desk (reception line, walk-in, find a patient) → "Queue for" doctor picker → Queue panel → Patient alerts. One `startPolling` refreshes overview, the selected queue and notifications together (html:575).
- **Admin** (`adminView` "Operations" tab, html:615): the same page without the Patient alerts panel. Admin sees alerts in "Alerts and audit" (html:754), which belongs to the Admin milestone. Showing the alert log on the React desk screens to admin is allowed: the route allows staff and admin.
- **Desk context** `loadCtx` (html:493) is loaded once per view:
  - `GET /api/departments` gives `ctx.doctors`, a flat list of every active doctor with `dep` (department name).
  - `GET /api/admin/policy` gives `ctx.policy` and `ctx.categories`: `priority_categories.split(",").map(trim).filter(Boolean)`.
  - In legacy these go stale until the view reloads. React should keep them live (useLive) without adding logic.

---

## 1. Front desk workflows

### 1.1 Waiting-room display link and today's check-in code
- **Roles:** staff, admin.
- **API:** `GET /api/admin/policy`. Returns all policy keys as strings plus `checkin_code` (6-digit string) and `display_key` (20 hex chars) (py:1340).
- **Legacy** (`receptionLine`, html:522):
  - Link: `${location.origin}${location.pathname}?display=${display_key}` with pathname `/`, so the URL is `/?display=KEY`. It opens with `target="_blank" rel="noopener"`.
  - Link text: "open the waiting-room display (tokens only, no names; works without signing in)".
  - Code text: "Check-in code today: **CODE** (patients need it to check themselves in)" when `require_checkin_code === "1"`. Otherwise the parenthesis reads "(not required at the moment)".
- **React:**
  - `/app/display` is NOT built in this milestone. routes.tsx has no `/display` route, so `*` redirects to Home. Until then the link must point to the legacy board `/?display=KEY`.
  - Do not build it from `location.pathname`: on React that is `/app/front-desk`.
  - Leave a comment saying the Display milestone switches the link to `/app/display?key=`.
- **Edge cases:**
  - The code changes daily (HMAC of `checkin:<date>`), so refresh policy with live data or at least on day change.
  - The code is shown to staff even when not required (legacy does this).
  - Staff check-in never needs the code (py:857, patient only).

### 1.2 Find a patient (lookup)
- **Roles:** staff, admin.
- **API:** `GET /api/lookup?q=<term>` (py:886).
  - Errors: 400 "Missing field: q." when blank (legacy input is `required`), and the 200-character limit.
- **Matching:**
  - `results`: today's appointments only, ANY status (booked, checked_in, called, in_consultation, completed, skipped, cancelled). Matches LIKE on patient name, username or phone, or an EXACT token string (a token search returns one row per doctor that has that token). Ordered by doctor name, then token. LIMIT 50.
  - `patients`: active patient accounts, LIKE on name, username or phone. Token is not matched here. LIMIT 20. `phone` is the guardian's phone for family members.
- **Response shapes:**
  ```
  results:  { id, token, status, day, patient_name, phone (patient's own, may be null), doctor (name), doctor_id }[]
  patients: { id, username, name, phone (COALESCE(guardian.phone, own)), guardian (guardian name | null) }[]
  ```
  Results have NO `patient_id`, `eta`, `ahead`, `turn_missed`, `can_skip` or `checked_in_at`. For late or grace details, fetch `GET /api/queue?doctor_id=<row.doctor_id>` and find the entry by `id`.
- **Legacy display** (html:550):
  - On success, message "`{results.length}` on today's list, `{patients.length}` patient accounts."
  - Results table: Token | Patient | Phone | Doctor | Status (STATUS label) | buttons. "Check in" shows only when status is `booked` or `skipped`. "Open queue" shows on every row.
  - Empty results: "Nobody on today's list matches."
  - The "Patient accounts" table shows only if any: Name | Username | Phone | Family of | buttons.
    - "Token with the walk-in doctor" on every row.
    - "Reset password" only when `guardian` is null.
  - Errors appear in the lookup message line.
- **Live refresh:** the legacy results are static (not polled). After a check-in from a row, legacy updates that row's status cell to "Checked in" and removes the button (html:557).
  - React: take the row status from the server reply, or re-run the last search. Never patch the row optimistically.

### 1.3 Appointment found dialog (Figma 4-2227)
- There is no legacy equivalent: legacy acts straight from the row.
- React opens it from a result row and shows only server data:
  - From the lookup row: token, patient_name, phone, doctor, status.
  - From that doctor's `GET /api/queue` entry: `ahead`, `eta` (estimate), `turn_missed`, `can_skip`, `checked_in_at`, `skip_reason`, `priority`/`emergency`.
- Omit the Figma fields with no backend data: age, sex, UHID, appointment code "AP-…", room, and the "identity confirmed" ticks.
- Actions in the dialog:
  - Check in (1.4), only for `booked` or `skipped`.
  - Open queue (1.7).
  - Cancel visit: optional. It is the same rule as the queue monitor (WAITING only, reason optional).
- **Late / missed copy before check-in:**
  - `status==="booked" && turn_missed && !can_skip`: "Late, within grace period: checking in keeps their place."
  - `status==="booked" && turn_missed && can_skip`: "Grace period over: checking in now keeps their place unless the doctor's desk has skipped them." The server keeps the place for any `booked` visit.
  - `status==="skipped"`: "Skipped (reason). Checking in puts them at the END of the queue." Offer a separate, clearly labelled policy-exception action "Reinsert next" (1.10).

### 1.4 Check in (booked or late patient)
- **Roles:** staff, admin (also patient, not in scope).
- **API:** `POST /api/checkin {appointment_id}` (py:850). There is no `version` field and it is not version-checked.
- **Server rules, in order:**
  - 404 "Appointment not found." (staff may act on any appointment)
  - 409 "Check-in opens on the day of the appointment." (any day other than today: past missed visits can never be modified)
  - 409 "This appointment was cancelled. Book again if you still need it."
  - Staff skip the self check-in window and code (py:857).
  - `booked` → `checked_in`, `checked_in_at=now`, position UNCHANGED. Event `checked_in`. A late patient (turn_missed, in or past grace) keeps their place; `due_at` stays but `turn_missed` becomes false because status is no longer booked.
  - `skipped` → `checked_in`, `due_at=NULL`, position = `end_position` (end of queue). Event `reinserted` with detail "late check-in, end of queue". This appears in overview exceptions.
  - 409 "This consultation is already complete."
  - 409 "This appointment is already checked in." (also returned for `called` and `in_consultation`)
- **Response:** `AppointmentView` (§4). It does not say whether the patient went to the end. The UI must remember the status it had before (lookup row or queue entry) to word the result:
  - Was `booked`: "Checked in. They keep their place: `ahead` ahead, expected around `eta` (estimate)."
  - Was `skipped`: "Checked in. They were skipped earlier, so they have rejoined at the END of the queue: `ahead` ahead."
- **Legacy:** message "Checked in." (lookup) or a silent queue reload (queue panel). Errors go in the message line.
- **React:**
  - "Patient checked in" dialog (4-2134) shows token (`tokenText`), patient_name, `doctor.department · doctor.name`, status, `ahead`, eta, `checked_in_at`, and the "rejoined at end" or "kept place" line above.
  - Omit age, sex, room, session name, the "Estimated wait 104–120 min" range, and the SMS / tracking-link sentence: no such SMS is sent on check-in.
  - The dialog may list `notifications` from the reply, which are real rows.
  - "Print token" uses the same slip as 1.6.
  - Refresh the queue afterwards: the reply is not a queue_state and the version has changed.

### 1.5 Walk-in registration (new patient)
- **Roles:** staff, admin.
- **API:** `POST /api/staff/walkin {name, phone?, lang?, doctor_id}` (py:902).
- **Doctor choice (legacy html:529, 537):** a select of `ctx.doctors.filter(x => x.holds_opd && x.status !== "unavailable")`, labelled `"Name (Department)"`.
  - React: Department → Doctor with the same filter, from `/api/departments` (today) or overview doctors.
  - Do NOT filter on `bookable`/`full`: staff bookings go through with a warning (py:759).
  - It is allowed to show "full" as a hint.
  - With no eligible doctor, the select is empty. The server then answers 400 "Missing field: doctor_id.", so disable submit and explain instead.
- **Fields:**
  - Name (required), Phone "Phone (for alerts)" (optional, placeholder "+91 98765 43210"), Alert language (LANGS en/hi, default en), Doctor.
  - Figma's Age, Gender, Reason for visit and "Patient identifier" have no backend: omit them. Mobile is NOT required by the server.
- **Server rules:**
  - Name is required: "Missing field: name."
  - Phone: `\+?[0-9 ]{7,16}`, otherwise 400 "Phone numbers may contain digits, spaces and a leading +."
  - lang: an invalid value silently becomes `en`. lang applies only when a NEW account is created.
  - **Account match:** if phone is given and an active, non-family patient exists with the same name (case-insensitive) and the same phone, that account is reused. Otherwise a new account is created: username `walkin-<8 hex>`, unusable password, channel `sms` if phone else `none`. Without a phone a new account is ALWAYS created.
  - Then `create_booking(by_staff=True, checked_in=True)` (py:739) for today:
    - 404 "Doctor not found."
    - 409 "`{doctor}` does not hold OPD on `{day}`. Choose another date or doctor." (inactive, non-working weekday or leave)
    - 409 "`{doctor}` is not available today. Choose another doctor or date." (effective status unavailable)
    - 409 "OPD has closed for today (closes HH:MM). Choose another date." (now ≥ the doctor's or hospital opd_end)
  - **Existing non-cancelled visit** with this doctor today: returns `{existing: true, ...AppointmentView}` with NO `warning` key.
    - If its status is `booked` or `skipped`, walkin then calls checkin. A skipped visit goes to the END of the queue, and the reply shows the post-check-in view.
    - If it is `checked_in`, `called`, `in_consultation` or `completed`, nothing changes and the reply shows that status.
  - A cancelled visit for this doctor today is reused (same row, new token, `existing: false`).
  - **Capacity** is a warning, not a refusal: `warning` = "`{doctor}` is fully booked on `{day}` (`{max}` patients)." or "`{doctor}`'s queue on `{day}` already runs to closing time (HH:MM). Choose another date or doctor." Otherwise `warning: null`.
  - The new visit gets the next token and the end position, status `checked_in`, `checked_in_at=now`. Event `booked` with "token N, walk-in at the desk". `promised_at` is set to the first ETA.
- **Response:** `WalkinResult = AppointmentView & { existing: boolean; warning?: string | null; username: string }`.
- **Legacy success text** (`walkinText`, html:545): "`{existing ? "Already booked:" : "Token"}` `{token}` with `{doctor.name}`, checked in. App username: `{username}` (reset the password below if they want to use the app).`{warning ? " Note: " + warning : ""}`". Then the form resets and screens refresh.
  - For `completed`/`called` the legacy text is wrong. React must show the real `status`.
- **React** "Appointment token issued" dialog (4-4219, titled "Patient checked in"):
  - Show token, patient_name, department · doctor, status, `ahead`, eta (estimate), username plus how to give app access (Reset password), and the warning as a caution Callout.
  - When `existing`: "They already had a visit with this doctor today (token N)." If it is now checked_in, say where they are from `ahead`.
  - Do not claim an SMS was sent. Omit the Figma room, session and wait range.

### 1.6 Token print preview (4-4481 / 4-4490)
- There is no legacy equivalent.
- `window.print()` of a slip containing only server fields from the reply: `tokenText(token)`, patient_name, doctor.name, doctor.department, day (`longDate`), `checked_in_at` time, optional "Expected around `{clock(eta)}` (estimate, may change)".
- Omit "Riverside Hospital", UHID, room, session, and "Track your turn using the SMS link" (no tracking link exists).
- Use print CSS so only the slip prints.

### 1.7 Open that doctor's queue in Queue monitor
- Legacy (html:558): sets the doctor picker to `doctor_id`, loads the queue and scrolls to it.
- React: navigate to `/app/queue-monitor?doctor=<doctor_id>` (or route state). Queue monitor must honour that preselection.

### 1.8 Walk-in token for an existing account
- **Roles:** staff, admin.
- **API:** `POST /api/staff/walkin {patient_id, doctor_id}`.
  - 404 "Patient not found." if the account is not an active patient.
  - Family-member accounts ARE allowed: the alerts go to the guardian.
  - Otherwise the same booking rules, existing-visit behaviour and warning as 1.5. name, phone and lang are ignored.
- Legacy (html:559) uses the doctor currently chosen in the walk-in form ("Token with the walk-in doctor"), and the message is `walkinText` in the lookup line.
- React: let staff choose the department and doctor (same filter as 1.5) in the dialog, or reuse the walk-in form's choice, labelled. Show the same token-issued dialog.

### 1.9 Reset a patient's app password
- **Roles:** staff, admin.
- **API:** `POST /api/staff/patient-password {patient_id, password}` (py:925).
  - 404 "Patient not found."
  - 409 "Family members sign in through their guardian's account."
  - 400 "Missing field: password."
  - 400 "Password must be at least 8 characters."
- **Effect:** the patient's sessions are all signed out. Event `patient_password_reset`.
- **Response:** `{ok: true, username}`.
- **Legacy** (html:562): `prompt("New password for this patient (at least 8 characters). Tell it to them privately.")`. Empty or cancel aborts. Success message: "Password set. They sign in as `{username}`." The button is hidden for family members.
- **React:** a Dialog with a password field (`type="password"`, label, autocomplete="new-password"), the same copy, and the server error shown in the dialog.

### 1.10 Late patients at the desk (product decision A/B; C is out of scope here)
- A. Late within grace (`status==="booked" && turn_missed && !can_skip`): Check in, keeps place (1.4).
- B. Skipped (`status==="skipped"`, today):
  - Check in puts them at the END (server). Say so before the click and after it.
  - "Reinsert next" = `POST /api/queue/action {action:"reinsert_front", appointment_id, reason, version}`.
    - Staff and admin only. The reason is REQUIRED: 400 "Give a reason for this exception."
    - 409 "Only a skipped patient can be reinserted."
    - Label it a policy exception. Legacy prompt: "Reason for putting this patient next (policy exception, required)".
  - This needs the queue `version`, so it goes through `useQueue(doctorId).act` for that doctor.
  - Server effect: status `checked_in`, `checked_in_at=now`, `due_at=NULL`, position = `front_position` (min waiting position − 1).
    - They are still behind the current called/in-consultation patient and behind any emergency or priority-category patient: `order()` sorts by status, then −priority, then position (eng:19).
    - Wording: "next among routine patients". Figma's "Reinsert 021 after next" is NOT what the server does: use "Reinsert next".
- Never reschedule: there is no `/api/reschedule` at the desk (it is patient-only anyway, py:815).

### 1.11 Session visibility card (selected doctor)
- **Source:** the overview doctor row (`GET /api/admin/overview`, §4): `status` (effective), `break_until`, `holds_opd`, `waiting` (booked + checked_in), `current_token`/`current_status`, `clears_at`, `opd_start`/`opd_end`, `congestion`.
- Show `clears_at` as "Queue clears around HH:MM (estimate)". Omit Figma's "96–112 min estimated wait for a new walk-in" and "Room 104".
- Don't use `/api/departments`' `waiting` for this card. It counts `ahead != null`, which includes the called and in-consultation patient (py:714), so it differs from overview's `waiting`.
- `holds_opd` false: "No OPD today" (legacy html:510).

### 1.12 Recent check-ins
- There is NO endpoint listing today's check-ins across doctors.
  - `/api/lookup` needs a non-empty `q`. Do not abuse `q=%`.
  - Walk-in versus appointment is not exposed. It exists only in event detail, and `/api/admin/events` is admin-only.
- Data that exists: `GET /api/queue?doctor_id=` entries with `checked_in_at` (kept after call or complete; cleared only by not_present) plus token, patient_name and status.
- **Options:**
  - (a) Selected doctor only, from the `useQueue(doctorId)` already on the page. This is the lazy, correct choice.
  - (b) One `/api/queue` per overview doctor that holds OPD.
- Either way, sort by `checked_in_at` descending and omit the Figma "Counter 02", the "Walk-in / Appointment / Follow-up" kind and "View registration log". Lead decides; default is (a), labelled with the doctor's name.

### 1.13 Patient alert delivery log
- **Roles:** staff, admin.
- **API:** `GET /api/admin/notifications` (py:1161): the last 200 across all days, newest first. Recipient and body are NOT exposed.
- **Legacy panel** "Patient alerts" (html:578), caption "Failed alerts never hold up the queue. Patients also see their status in the app."
  - Columns: Created (`created_at` "YYYY-MM-DD HH:MM") | Patient | Doctor | Token | Alert (ALERT label) | Channel (uppercase) | Status (SENT label; pill tone failed=urgent, pending=caution, else success; text not colour-only) | Tries (`attempts`) | Detail.
  - Empty: "No alerts sent yet."
  - Staff polls it with the other panels.
- **Labels (copy from html:116):**
  - ALERT: arrival "Your turn is near", eta_change "Time changed", called "Called in", skipped "Missed turn", doctor_unavailable "Doctor unavailable", doctor_leave "Doctor on leave", transferred "Moved to another doctor", cancelled "Cancelled by the desk", reset_code "Password reset code".
  - SENT: pending "sending", sent "sent", delivered "delivered", unconfirmed "sent, delivery not confirmed", failed "failed".
- The overview also gives `failed_alerts` (count today). Legacy shows "`{n}` failed alerts today · updated HH:MM".

---

## 2. Queue monitor workflows

### 2.1 Session cards (all doctors)
- **Roles:** staff, admin.
- **API:** `GET /api/admin/overview` (py:1106): every ACTIVE doctor, including those with no OPD today.
- **Legacy** "Workload today" table (html:508):
  - Columns: Doctor | Department | Status (`holds_opd ? DOCSTATUS[status] : "no OPD today"`) | Waiting | Current (`"{token} ({status lower})"` or –) | Avg consult `{avg_minutes} min` | OPD hours `{opd_start}–{opd_end}` | Queue clears `hhmm(clears_at)` | Done / skipped | Load (congestion pill: normal=success, busy=caution, over capacity=urgent).
  - Info line "`{failed_alerts}` failed alerts today · updated `hhmm(updated_at)`".
- **Congestion** is the server's: "over capacity" when clears_at > the doctor's close; "busy" when waiting ≥ 8; else "normal". A no-OPD doctor has `clears_at` null, so it shows normal or busy.
- **Next call ETA:** the overview does NOT provide it. Omit it on the cards. Only the SELECTED doctor's queue has ETAs: the eta of the first entry in server order with status booked/checked_in (lowest `ahead` among WAITING). Show it only there, and only if non-null. Fetching `/api/queue` per card is allowed but not required.
- A break or delay shows "back HH:MM" from `break_until` (present.ts `doctorStatus` pattern). Figma "+15 min delay" = break_until − updated_at, display arithmetic only. "Room" has no backend: omit.

### 2.2 Selected doctor's live queue
- **API:** `GET /api/queue?doctor_id=` via `useQueue(doctorId)`. `QueueState` is already typed.
- **Legacy info line** (html:405): "`{name}` · `{status}` (break/delayed: '`{on break|delayed}` until HH:MM'; no OPD: 'no OPD today') · OPD `{opd_start}–{opd_end}` · usual consult `{avg_minutes}` min · updated HH:MM".
- **Legacy table** (html:433):
  - Columns: Order (`ahead+1` or –) | Token | Patient | Status pill + flags + `(skip_reason)` | ETA (`hhmm(eta)`; "unavailable" when `ahead != null` and no eta; blank otherwise) | Actions.
  - Flags: Emergency, or the priority label; turn_missed shows "Grace over" (can_skip) or "Turn missed, in grace".
  - Empty: "No appointments in this queue today."
  - With no doctors: "No doctors have been added yet. An administrator adds them under Doctors and departments."
- The legacy table shows ALL entries, including completed, skipped and cancelled, sorted by server rank (inactive ones last, by token) (py:375).
- Status labels (html:114): Booked, Checked in, Called, In consultation, Completed, Skipped, Cancelled.
- **Action reply handling** (legacy `run`, html:442):
  - A reply with `message` shows it as success. call_next shows "Called token N." (composed in the client from `called`).
  - Errors show in the message line.
  - The queue always reloads afterwards.
  - React: useQueue already sets the reply or refreshes on failure and opens FailureDialog.

### 2.3 Action matrix (who / when / API / server rules)

All `/api/queue/action` calls send `{action, ..., version: queue.version}`. They are only for today: otherwise 404 "No such appointment in today's queue.".

Common errors:
- 400 "Unknown action: X."
- 403 "You do not have permission for this action on this queue." (role not in QUEUE_ACTIONS)
- 409 "The queue changed since you loaded it. It has been refreshed; try again."

Reply = `QueueState` (+extras).

| UI action | Legacy shows button when (html:416-430) | Roles (server) | Body | Server refusals | Notes |
|---|---|---|---|---|---|
| Call next | doctor or staff (NOT admin) | doctor, staff | `{action:"call_next", doctor_id}` | 409 "Finish the current patient before calling the next one." · 409 "No patients are waiting." | 200 `{called: token}`. When only not-checked-in patients are waiting: 200 `{called:null, message:"Nobody waiting has checked in yet."}` and the head's grace starts (`turn_missed` event). Passed-over booked patients get `due_at` (grace starts). Patient alert "called". |
| Check in | desk and status ∈ {booked, skipped} | staff, admin | `POST /api/checkin {appointment_id}` | see 1.4 | Skipped means END of queue: say so. Returns AppointmentView, so refresh. |
| Not here | (doctor or staff, NOT admin) and status ∈ {called, checked_in} | doctor, staff | `{action:"not_present", appointment_id, reason?}` | 409 "Only a called or checked-in patient can be marked as not here." | Called → booked, grace starts (`due_at` = turn_cutoff). Checked_in → booked, `due_at` null (simply not arrived). Keeps place. Prompt: "Not at the door? They lose check-in and keep their place. Note (optional):". Reuse NotHereDialog. |
| Skip | (doctor or staff, NOT admin) and `can_skip` | doctor, staff | `{action:"skip", appointment_id, reason?}` | 409 "This patient cannot be skipped yet: their grace period has not run out." | Empty reason is stored as "no-show". Patient alert "skipped". Prompt: "Reason for skipping (leave empty for no-show)". Reuse NoShowDialog. |
| Emergency | desk and WAITING and `!emergency` | staff, admin | `{action:"emergency", appointment_id, reason}` | 409 "Only a waiting patient can be given emergency priority." · 400 "Give a reason for emergency priority." | Required reason. Sets priority 2, label "emergency". Prompt: "Reason for emergency priority (required)". The SHARED dialog is reused by the Emergency milestone. |
| Priority category | desk and WAITING and `!priority` (null, so hidden for emergency too) | staff, admin | `{action:"priority", appointment_id, category}` | 400 "Category must be one of: A, B, C." · 409 "Only a waiting patient without emergency priority can be given a priority category." | Categories come from policy `priority_categories` (trimmed). No reason field: the server logs the category. Shared dialog. |
| Remove priority | desk and `priority` non-null (any status, incl. emergency) | staff, admin | `{action:"remove_priority", appointment_id, reason}` | 409 "This patient has no priority to remove." · 400 "Give a reason for removing the priority." | Logged as "was `{label}`: `{reason}`". Shared dialog. |
| Move to colleague | desk and WAITING | staff, admin | `{action:"transfer", appointment_id, to_doctor_id}` | 400 "Move patients to another doctor in the same department." · 409 "`{dst}` is not holding OPD now." · 409 "Only a waiting patient can be moved to another doctor." · 409 "This patient already has an appointment record with `{dst}` today." | Colleagues: same `department_id`, other id, `holds_opd`, status ≠ unavailable (html:443). No colleague: "No other doctor in this department is holding OPD now." The patient goes to the END of the destination queue with a new token and keeps status and priority. Alert "transferred". The reply is the SOURCE doctor's queue. |
| Move all waiting | desk (queue controls) | staff, admin | `{action:"transfer_all", doctor_id, to_doctor_id}` | transfer_target errors as above | Moves every WAITING entry (booked + checked_in, incl. turn_missed; NOT skipped, called or in_consultation) in queue order. Reply `{message}` = "Moved N waiting patients to X." + " Kept tokens a, b: they already have a record with X today." when some are kept. N can be 0. Legacy title: "Move everyone waiting for `{name}` to:". Add a confirmation in React; legacy had none beyond the picker. |
| Cancel | desk and WAITING | staff, admin | `POST /api/cancel {appointment_id, reason?}` | 409 "Only an upcoming appointment that has not been called can be cancelled." · 404 "Appointment not found." | Prompt "Cancel this appointment? The patient is told. Reason (optional):". Cancel in the prompt aborts; an empty reason is OK. Patient alert "cancelled". Reply is AppointmentView, so refresh. Skipped visits cannot be cancelled. |
| Reinsert next | desk and status = skipped | staff, admin | `{action:"reinsert_front", appointment_id, reason}` | 409 "Only a skipped patient can be reinserted." · 400 "Give a reason for this exception." | Policy exception, required reason, see 1.10. |
| Doctor status | all desk roles incl. admin | doctor, staff, admin (any doctor) | `POST /api/doctor/status {doctor_id, status, minutes?}` | 400 "Status must be available, break, delayed or unavailable." · 400 "Length must be 1 to 240 minutes." · 400 "Missing field: minutes." · 404 "Doctor not found." | No version. Reply QueueState. Legacy buttons: Available (disabled if available), Break 15 min, Running 10 min late, Unavailable (disabled if unavailable). React: break or running late for N min (1–240). Unavailable lasts only today, clears all waiting ETAs (null), and queues a "doctor_unavailable" alert to every waiting patient: confirm before sending. Reuse PauseDialog / AvailabilityDialog. |

Start and Complete are doctor-only: never show them on staff screens.

### 2.4 Needs attention panel
- **Sources:**
  - `overview.exceptions` (today, newest first, LIMIT 20). Fields: `{at, action, detail, doctor (name|null), token (number|null)}`. They have NO doctor_id, appointment_id or actor.
    - Actions: skip, emergency, reinsert_front, reinserted, doctor_delayed, doctor_unavailable, doctor_break, priority, remove_priority, not_present, transferred_out, cancelled.
    - Legacy shows them in a `<details>` "Today's exceptions": Time | Doctor | Token | What (`action` with _ → space) | Detail. Empty: "No exceptions yet today."
  - `overview.failed_alerts`.
  - The selected queue's late patients: `isLate` = status skipped, or `turn_missed`.
- **Skipped & late dialog** (4-2152): list those entries with Check in (skipped means end of queue), Reinsert next (reason) and Skip (when can_skip, not admin).
  - Omit "Called 10:02 AM": there is no called time in the API.
  - Omit "N patients notified" from the Figma delay row: not provided.
  - Generalise the existing `SkippedLateDialog`. Do not copy it.

### 2.5 Full queue dialog (4-3874)
- Generalise `FullQueueDialog` with staff actions.
- The header counts (waiting / checked in / not arrived) are a display count of server entries.
- Omit Room.

### 2.6 Live refresh
- **Legacy:** SSE `/api/stream` triggers a refresh 300 ms after each message. There is a 5 s timer while the stream is down, and a forced refresh every 30 s (html:145-158).
- The legacy check "another desk's change appears without waiting for the timer" (test_ui.js:97) must hold.
- React: `useLive`/`useQueue` already do this. Overview, notifications, policy and the departments list should also use `useLive`.
- The selected doctor and any open dialog must survive refreshes.

---

## 3. Shared-component requirements
- Emergency (reason required), Priority category (from policy) and Remove priority (reason required) dialogs go in a shared place, e.g. `features/queue/priorityDialogs.tsx`. The Emergency milestone reuses them.
- Move consultation dialogs that staff also need out of `features/consultation`, and update imports. That covers SkippedLateDialog, FullQueueDialog, NotHereDialog, NoShowDialog and FailureDialog.
- Extend `useQueue`:
  - `QueueAction` must add `emergency | priority | remove_priority | reinsert_front | transfer | transfer_all`.
  - The `act` body must accept `to_doctor_id` and `category`.
  - Add `checkin(appointment_id)` and `cancel(appointment_id, reason?)`. They return AppointmentView, so call `refresh()` after them.
  - `act` already sends `doctor_id` (ignored by the server for per-appointment actions) and `version`.

---

## 4. Response types for api/types.ts (copied from server.py)

```ts
/** appointment_view() py:826 — reply of /api/checkin, /api/cancel, /api/staff/walkin, /api/book */
interface AppointmentView extends QueueEntry {
  doctor: QueueState["doctor"];
  day: string;
  updated_at: string;
  arrival_alert: boolean;
  notifications: { purpose: string; channel: "sms" | "email"; status: NotifStatus; created_at: string; updated_at: string }[]; // last 3
  patient_id: number;
  checkin_opens_at: string | null;   // only while status booked and in the future
  checkin_code_required: boolean;
}
/** POST /api/staff/walkin py:922 */
interface WalkinResult extends AppointmentView { existing: boolean; warning?: string | null; username: string } // warning absent when existing
/** GET /api/lookup py:891 */
interface LookupResult { id: number; token: number; status: ApptStatus; day: string; patient_name: string; phone: string | null; doctor: string; doctor_id: number }
interface LookupPatient { id: number; username: string; name: string; phone: string | null; guardian: string | null }
interface Lookup { results: LookupResult[]; patients: LookupPatient[] }
/** POST /api/staff/patient-password */
interface PasswordSet { ok: true; username: string }
/** GET /api/admin/overview py:1120 */
interface OverviewDoctor extends Omit<QueueState["doctor"], never> {
  waiting: number; current_token: number | null; current_status: "called" | "in_consultation" | null;
  avg_minutes: number; clears_at: string | null; congestion: "normal" | "busy" | "over capacity";
  completed: number; skipped: number; emergencies: number;
}
interface OverviewException { at: string; action: string; detail: string | null; doctor: string | null; token: number | null }
interface Overview { doctors: OverviewDoctor[]; exceptions: OverviewException[]; failed_alerts: number; updated_at: string; opd_end: string }
/** GET /api/admin/notifications py:1163 */
type NotifStatus = "pending" | "sent" | "delivered" | "unconfirmed" | "failed";
interface NotificationRow { id: number; purpose: string; channel: "sms" | "email"; status: NotifStatus; attempts: number;
  created_at: string; updated_at: string; detail: string | null; patient: string; token: number | null; doctor: string | null }
/** GET /api/admin/policy py:1343 — every value a string */
interface Policy { opd_start: string; opd_end: string; grace_minutes: string; alert_minutes: string; eta_change_minutes: string;
  notify_retries: string; checkin_minutes: string; require_checkin_code: "0" | "1"; booking_days_ahead: string;
  max_active_bookings: string; block_after_close: string; priority_categories: string; retention_days: string;
  checkin_code: string; display_key: string }
/** GET /api/departments py:719 — full doctor row (extend the existing Departments type) */
type DeptDoctor = QueueState["doctor"] & { waiting: number /* ahead!=null, incl. current */; clears_at: string | null; bookable: boolean; full: boolean };
/** queue action extras */
// call_next: { called: number | null; message?: string } & QueueState ; transfer_all: { message: string } & QueueState
```
In QueueEntry, `priority` is `priority_label`, which is "emergency" for emergency patients (py:1047). Every timestamp is a local ISO string without a zone (`YYYY-MM-DDTHH:MM:SS`).

---

## 5. Where the brief or Figma disagrees with the code

1. **Walk-in reply** (brief §4 "returns token, username, warning, existing"): `warning` is absent when `existing` is true. An existing visit may be returned as `called`, `in_consultation` or `completed`, unchanged, so it is not always "checked in". A skipped existing visit is silently checked in at the END of the queue, and the reply does not reveal that it was skipped.
2. **Version** (brief §1 "Every queue action sends the version"): only `/api/queue/action` checks `version`. `/api/checkin`, `/api/cancel` and `/api/doctor/status` ignore it.
3. **Admin queue actions** (task text: Queue monitor "every legacy staff queue action: call next…"): admin is refused call_next, skip and not_present (403 "You do not have permission for this action on this queue."). Legacy hides them for admin. The React UI must hide them for admin.
4. **Next call ETA on session cards:** `/api/admin/overview` does not supply one, so omit it on cards. It exists only in a doctor's `/api/queue`.
5. **Overview exceptions** have no `doctor_id`, `appointment_id` or actor, only the doctor's name and token. "Needs attention" items cannot deep-link by id. Display them as text, or match the selected doctor by name (names are not unique-constrained).
6. **Waiting-room display link:** `/app/display` does not exist in routes.tsx yet (it falls to `*` and redirects Home). Link to the legacy `/?display=KEY` this milestone.
7. **Figma "Reinsert 021 after next"** (4-2152): the server puts the patient at the FRONT of the waiting patients, still behind the current patient, emergencies and priority categories. Label it "Reinsert next".
8. **Recent check-ins:** no endpoint exists. Walk-in versus appointment, "Counter" and the registration log are not available (see 1.12).
9. **Lookup** returns no `patient_id`, ETA or grace fields, and includes cancelled and completed visits. Use `/api/queue?doctor_id` for late or grace detail.
10. **`/api/departments` `waiting`** counts the current called and in-consultation patient. `/api/admin/overview` `waiting` does not. Use overview for desk cards.
11. **Walk-in `lang`** is ignored when an existing account is matched (same name and phone) or `patient_id` is sent.
12. **Figma copy** "An SMS with the token and tracking link has been sent" (4-2134, 4-4219) and "Track your turn using the SMS link" (4-4490): the server sends no token SMS and has no tracking link. The only messages are the regular alerts in `notifications`. Omit this copy.
13. **Figma fields with no backend:** age, gender, UHID, appointment code, reason for visit, room, session name, hospital name/location, "Counter 02", wait ranges ("96–112 min", "104–120 min"), "Called 10:02 AM", "N patients notified". Omit them all, each with a code comment.
14. **Mobile number** is marked required (*) in Figma 02. The server makes phone optional: no phone means alerts are off (channel none) and a new account is always created.

---

## 6. Acceptance checklist

**Front desk (/app/front-desk)**

1. Staff and admin reach /app/front-desk and /app/queue-monitor; other roles cannot. The NotMigrated placeholders for these two routes are gone. /app/emergency and /app/admin/* are unchanged.
2. The front desk shows today's check-in code from `GET /api/admin/policy` with "required" or "not required" wording from `require_checkin_code`, plus a link that opens the waiting-room display (`/?display=<display_key>`) in a new tab.
3. A lookup by name, phone, username or token calls `GET /api/lookup?q=`. It lists today's visits (Token, Patient, Phone, Doctor, Status) and patient accounts (Name, Username, Phone, Family of), and shows "Nobody on today's list matches." when there are no visits. A blank search shows the server's or required-field message.
4. Opening a visit shows the Appointment found dialog with only server data. Late-within-grace, grace-over and skipped states come from that doctor's `/api/queue` entry and are worded per 1.3.
5. "Check in" shows only for `booked` or `skipped` visits. After check-in, the Patient checked in dialog shows the server's token, status, `ahead` and ETA (as an estimate). A booked or late patient is told they kept their place. A skipped patient is told, before AND after, that they rejoined at the END of the queue.
6. Check-in errors (already checked in, completed, cancelled, not today) are shown verbatim, and the screen re-reads server state.
7. "Open queue" goes to /app/queue-monitor with that doctor preselected.
8. Walk-in form:
   - Fields: Name (required), Phone for alerts (optional), Alert language (English / Hindi), Department → Doctor.
   - Only doctors with `holds_opd && status !== "unavailable"` are offered, and full doctors are not hidden.
   - It submits `POST /api/staff/walkin`.
   - With no eligible doctor, submit is disabled with an explanation.
9. The token-issued dialog shows the server's token, patient name, doctor and department, status, `ahead`/ETA, username, and the capacity `warning` (caution). When `existing` is true it says they already had a visit today and shows its real status. It never claims an SMS was sent.
10. "Print token" opens a preview and calls `window.print()`. The slip contains only server-returned fields: token, patient, doctor, department, date, check-in time, optional ETA estimate. There is no hospital name, UHID, room or tracking link.
11. "Walk-in token" for an existing account (including family members) sends `{patient_id, doctor_id}` with an explicitly chosen doctor and shows the same dialog.
12. "Reset password" is hidden for family members. It opens a dialog with a labelled password field and sends `POST /api/staff/patient-password`. Success shows "Password set. They sign in as `<username>`." The 8-character and other server errors show in the dialog.
13. The session card for the selected doctor shows server status (with "back HH:MM" for break or delay, "No OPD today" when `!holds_opd`), overview `waiting`, the current token and `clears_at` as an estimate. It shows no wait range and no room.
14. Recent check-ins list today's entries with `checked_in_at`, newest first, from `/api/queue` data. There is no counter or visit kind.
15. A patient alert log (`GET /api/admin/notifications`) is on the staff screens with legacy labels, text status (not colour-only), attempts and detail, and "No alerts sent yet." when empty.

**Queue monitor (/app/queue-monitor)**

16. The queue monitor shows one session card per doctor in `GET /api/admin/overview`: status or "No OPD today", waiting, current token, clears_at, congestion (text plus tone). Next-call ETA appears only where a server ETA exists, from the selected doctor's queue. The failed-alerts count and the last update time are visible.
17. Selecting a card loads `useQueue(doctorId)`. The table shows server order (`ahead+1`), token, name, status and flags (Emergency, category, "Turn missed, in grace" or "Grace over", skip reason), and the ETA (or "unavailable" when `ahead != null` and eta is null).
18. The actions match the §2.3 matrix exactly, including role and visibility conditions. Admin never sees Call next, Not here or Skip. Start and Complete never appear.
19. Every `/api/queue/action` sends the current `version`. A 409 "The queue changed…" shows the message and the refreshed queue.
20. Emergency and Remove priority cannot submit without a reason. Priority offers exactly the policy categories. These three dialogs live in a shared module that the Emergency milestone can import.
21. Move to colleague offers only same-department doctors that hold OPD and are not unavailable (from live data), or shows "No other doctor in this department is holding OPD now.". Move all waiting asks for confirmation and shows the server's `message` (moved and kept tokens).
22. Cancel asks for confirmation with an optional reason and says the patient is told. It is offered only for booked or checked_in visits.
23. Reinsert next is offered only for skipped patients. It is labelled a policy exception, requires a written reason, and is staff and admin only. Check in for a skipped patient says "end of queue".
24. Doctor status offers Available, Break N min and Running late N min (1–240), and Unavailable with a confirmation that waiting patients are alerted. The current status option is disabled, and the reply updates the screen.
25. The Needs attention panel shows overview exceptions (time, doctor, token, action, detail; "No exceptions yet today." when empty), failed alerts, and the selected queue's skipped and late patients. "Review" opens the shared Skipped & late dialog with the allowed actions. There is no invented "called at" time and no "patients notified" count.
26. A full-queue dialog is available and reuses the generalised consultation component.
27. The queue monitor has an "Open waiting room display" link (same URL as item 2).
28. Every server refusal is shown verbatim (FailureDialog or inline message). The UI never reorders, recomputes ETAs or decides `can_skip` itself.

**Both screens**

29. Live updates: a change made by another desk (e.g. a walk-in posted via the API) appears within about 1.5 s without waiting for the timer. Polling covers the stream being down. The selected doctor and open dialogs survive refreshes.
30. Responsive and accessible:
    - Responsive: at <768 px there is no sideways scroll (legacy check "mobile (staff/admin)").
    - Every field is labelled, dialogs use `Dialog`, and panels are named regions.
    - No colour-only status, and buttons are real buttons.
31. The React browser suite gains role and label-based checks porting test_ui.js:84-109:
    - walk-in gets a token
    - not here keeps the place, grace starts ("Turn missed" / late)
    - check in again
    - priority category shown
    - live update from another desk
    - move to a colleague (the patient leaves the queue)
    - reset a patient's password
    - the display link opens a board with tokens and no names
    - plus a skipped patient checks in at the end, and reinsert-next requires a reason.
32. `npm run build` is clean, the legacy suite (36 checks) and the backend suites still pass, and app/index.html, app/server.py and app/engine.py are unchanged.
