import type { FormEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import type { DoctorStatus, OverviewDoctor, QueueEntry, QueueState, Role } from "../../api/types";
import { Dialog } from "../../design/Dialog";
import type { ButtonKind } from "../../design/ui";
import { Button, Callout, EmptyState, SelectField, TextField } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import type { Failure } from "./useQueue";
import { entryDetail, inQueue, isLate, isWaiting, staffActions } from "./present";
import { QueueTable } from "./QueueTable";
import s from "./queue.module.css";

// Queue dialogs shared by the doctor's Consultation screen, the desk's Queue monitor and Front desk, and the
// Emergency screen. Each one only collects what the server needs; the server decides and its reply is shown.

const field = (e: FormEvent<HTMLFormElement>, name: string) => String(new FormData(e.currentTarget).get(name) ?? "");
const footer = (cancel: () => void, primary: string, busy?: boolean, kind: ButtonKind = "primary", disabled = false) => (
  <><Button kind="secondary" className={s.cancelBtn} onClick={cancel}>Cancel</Button>
    <Button type="submit" kind={kind} className={s.primaryBtn} disabled={busy || disabled}>{primary}</Button></>
);
const notice = (title: ReactNode, sub?: ReactNode) => <><strong>{title}</strong>{sub && <><br /><span className={s.calloutSub}>{sub}</span></>}</>;

/** 4:2080 · "Mark token 025 as no-show?" → action "skip" (only offered when the server says can_skip). */
export function NoShowDialog({ e, busy, onClose, onConfirm }: { e: QueueEntry | null; busy: boolean; onClose: () => void; onConfirm: (reason: string) => void }) {
  return (
    <Dialog open={!!e} onClose={onClose} title={e ? `Mark token ${tokenText(e.token)} as no-show?` : ""}
      description={e && (e.status === "called" ? `${e.patient_name} has not arrived after the call.` : `${e.patient_name}’s grace period has run out.`)}
      onSubmit={(ev) => onConfirm(field(ev, "reason"))} footer={footer(onClose, "Mark as no-show", busy)}>
      <SelectField label="Reason *" name="reason" required defaultValue="Patient not present">
        <option>Patient not present</option>
        <option>Left before being seen</option>
      </SelectField>
      <Callout>{notice("The visit stays in Skipped / late.", "The front desk can reinsert the patient once they arrive.")}</Callout>
    </Dialog>
  );
}

/** Same layout as the no-show dialog, for "not_present": the patient keeps their place and the grace period starts. */
export function NotHereDialog({ e, busy, onClose, onConfirm }: { e: QueueEntry | null; busy: boolean; onClose: () => void; onConfirm: (note: string) => void }) {
  return (
    <Dialog open={!!e} onClose={onClose} title={e ? `Mark token ${tokenText(e.token)} as not here?` : ""}
      description={e && `${e.patient_name} keeps their place in the queue.`}
      onSubmit={(ev) => onConfirm(field(ev, "note"))} footer={footer(onClose, "Mark not here", busy)}>
      <TextField label="Note (optional)" name="note" />
      <Callout>{notice("Check-in is cleared.",
        e?.status === "called" ? "Their grace period starts now. Once it runs out you can mark them as a no-show." : "They wait again until they check in.")}</Callout>
    </Dialog>
  );
}

// the server accepts 1–240 minutes for a break or delay
const DURATIONS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240];

/** 4:2063 · "Pause the queue?" → doctor status "break" for the chosen minutes. (No reason: the server stores none.) */
export function PauseDialog({ open, q, busy, onClose, onConfirm }: { open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onConfirm: (minutes: number) => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Pause the queue?" description="New patient calls will stop. Queue order is preserved."
      onSubmit={(ev) => onConfirm(Number(field(ev, "minutes")))} footer={footer(onClose, "Pause queue", busy)}>
      <SelectField label="Expected return" name="minutes" defaultValue="15">
        {DURATIONS.map((m) => <option key={m} value={m}>In {m} minutes{q ? ` · around ${clock(addMinutes(q.updated_at, m))}` : ""}</option>)}
      </SelectField>
      <p className={s.dialogTick}>✓&nbsp;&nbsp;Waiting patients’ estimated times move to after your return</p>
    </Dialog>
  );
}

/**
 * Availability menu (2:350 → 4:2171) with the delay fields from 4:2184. One status at a time, as the server keeps.
 * The doctor sees it in the second person; the desk passes `doctorName` and sees it in the third person.
 * The current status (available / unavailable) is disabled, as in the legacy desk controls.
 */
export function AvailabilityDialog({ open, q, busy, onClose, onConfirm, doctorName }: {
  open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onConfirm: (status: DoctorStatus, minutes?: number) => void; doctorName?: string;
}) {
  const now = q?.doctor.status;
  const disabled = (v: DoctorStatus) => (v === "available" || v === "unavailable") && v === now;
  const [choice, setChoice] = useState<DoctorStatus>("available");
  useEffect(() => { if (open) setChoice(now === "available" ? "delayed" : "available"); }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps
  const they = !!doctorName;
  const options: [DoctorStatus, string, string][] = [
    ["available", "Available", "Seeing patients as usual."],
    ["delayed", "Running late", "Queue order is preserved. Waiting estimates adjust."],
    ["break", "On a break", they ? "No new calls. Estimates start from their return." : "No new calls. Estimates start from your return."],
    ["unavailable", "Unavailable today", they ? "Patients see no time for this queue. Resets at the next OPD day." : "Patients see no time for your queue. Resets at the next OPD day."],
  ];
  return (
    <Dialog open={open} onClose={onClose} title={they ? `${doctorName}: availability` : "Your availability"} description={q && `Now: ${statusNow(q)}`}
      onSubmit={(ev) => onConfirm(choice, choice === "delayed" || choice === "break" ? Number(field(ev, "minutes")) : undefined)}
      footer={footer(onClose, choice === "delayed" ? "Update & notify" : choice === "unavailable" ? "Mark unavailable" : "Update availability", busy,
        choice === "unavailable" ? "danger" : "primary", disabled(choice))}>
      <fieldset className={s.choices}>
        <legend className={s.srOnly}>Availability</legend>
        {options.map(([v, label, hint]) => (
          <label key={v} className={`${s.choice} ${choice === v ? s.chosen : ""}`}>
            <input type="radio" name="status" value={v} checked={choice === v} disabled={disabled(v)} onChange={() => setChoice(v)} />
            <span><span className={s.choiceLabel}>{label}{disabled(v) ? " (now)" : ""}</span><span className={s.choiceHint}>{hint}</span></span>
          </label>
        ))}
      </fieldset>
      {(choice === "delayed" || choice === "break") && (
        <SelectField label={choice === "delayed" ? "Delay duration" : "Expected return"} name="minutes" defaultValue="15" key={choice}>
          {DURATIONS.map((m) => <option key={m} value={m}>{m} minutes</option>)}
        </SelectField>
      )}
      {choice === "unavailable" && !disabled(choice) && (
        <Callout tone="urgent">{notice("Every waiting patient is sent a “Doctor unavailable” alert.",
          "Their expected times are cleared until the doctor is available again. This lasts for today only.")}</Callout>
      )}
    </Dialog>
  );
}

/**
 * 4:2152 · Skipped & late patients. Doctors can skip a late patient once the server allows it. The desk also
 * checks a patient in (skipped → end of the queue, late → keeps their place) or reinserts a skipped patient next
 * (policy exception). Figma's "Called 10:02 AM", "Patient now present" and "Reinsert 021 after next" are left out:
 * the server has no call time or presence data, and reinsert_front puts the patient next, not after next.
 */
export function SkippedLateDialog({ open, q, busy, onClose, onNoShow, onCheckIn, onReinsert, result }: {
  open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onNoShow?: (e: QueueEntry) => void;
  onCheckIn?: (e: QueueEntry) => void; onReinsert?: (e: QueueEntry) => void; result?: string;
}) {
  const rows = q ? q.entries.filter(isLate) : [];
  const desk = !!onCheckIn;
  return (
    <Dialog open={open} onClose={onClose} size="md" title="Skipped & late patients"
      description={desk ? "Confirm arrival first. No visit is deleted." : "No visit is deleted. The front desk reinserts a patient once they arrive."}
      footer={<Button kind="secondary" className={s.cancelBtn} onClick={onClose}>Close</Button>}>
      {rows.length ? (
        <ul className={s.lateList}>
          {rows.map((e) => (
            <li key={e.id} className={s.lateRow}>
              <span className={s.lateToken}>{tokenText(e.token)}</span>
              <span className={s.lateText}>
                <span className={s.lateName}>{e.patient_name}</span>
                <span className={s.lateSub}>{e.status === "skipped" ? `Skipped · ${e.skip_reason || "no-show"}`
                  : e.can_skip ? "Turn missed · grace period over" : "Turn missed · grace period running"}</span>
              </span>
              <span className={s.lateActions}>
                {onCheckIn && (
                  <Button kind="secondary" disabled={busy} onClick={() => onCheckIn(e)}>{e.status === "skipped" ? "Check in · end of queue" : "Check in · keeps place"}</Button>
                )}
                {onReinsert && e.status === "skipped" && <Button kind="secondary" disabled={busy} onClick={() => onReinsert(e)}>Reinsert next…</Button>}
                {onNoShow && e.status !== "skipped" && e.can_skip && <Button kind="secondary" disabled={busy} onClick={() => onNoShow(e)}>Skip / no-show</Button>}
              </span>
            </li>
          ))}
        </ul>
      ) : <EmptyState title="Nobody skipped or late.">Patients who miss their turn appear here, and stay on record.</EmptyState>}
      {result && <p className={s.lateResult} role="status">✓&nbsp;&nbsp;{result}</p>}
    </Dialog>
  );
}

/**
 * 4:3874 · "View all N patients": the whole list in server order. The doctor sees waiting and late patients with
 * Not here / No-show; the desk passes every entry (`rows`) and its own `actions`. Room is not stored: left out.
 */
export function FullQueueDialog({ open, q, busy, onClose, onNotHere, onNoShow, rows: given, actions }: {
  open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onNotHere?: (e: QueueEntry) => void; onNoShow?: (e: QueueEntry) => void;
  rows?: QueueEntry[]; actions?: (e: QueueEntry) => ReactNode;
}) {
  const rows = given ?? (q ? q.entries.filter((e) => isWaiting(e) || (isLate(e) && e.status !== "skipped")) : []);
  const waiting = rows.filter(inQueue);
  const counts = `${waiting.length} waiting · ${waiting.filter((e) => e.status === "checked_in").length} checked in · ${waiting.filter((e) => e.status === "booked").length} not arrived`;
  return (
    <Dialog open={open} onClose={onClose} size="lg" title={q ? `${q.doctor.department} · Full queue` : "Full queue"} description={counts}
      footer={<><span className={s.dialogTableNote}>Token numbers are assigned at booking; order follows clinical priority, then check-in.</span>
        <Button kind="secondary" className={s.primaryBtn} onClick={onClose}>Close</Button></>}>
      {q && rows.length ? (
        <div className={s.dialogTable}>
          <QueueTable q={q} rows={rows} label="Full queue" dense actions={actions ?? ((e) =>
            e.can_skip && onNoShow ? <Button kind="secondary" disabled={busy} onClick={() => onNoShow(e)}>No-show</Button>
              : e.status === "checked_in" && onNotHere ? <Button kind="secondary" disabled={busy} onClick={() => onNotHere(e)}>Not here</Button> : null)} />
        </div>
      ) : <EmptyState title="All caught up.">No patients are waiting.</EmptyState>}
    </Dialog>
  );
}

/** 4:2200 · "The queue could not be updated": the server refused or could not be reached. Shows its message. */
export function FailureDialog({ failure, onClose, onRefresh }: { failure: Failure | null; onClose: () => void; onRefresh: () => void }) {
  const title = !failure ? "" : failure.status === 0 ? "Connection interrupted" : failure.status === 409 ? "The queue has changed" : "Not allowed";
  return (
    <Dialog open={!!failure} onClose={onClose} title="The queue could not be updated" description="Your last action was not saved. No patient has moved."
      footer={<><Button kind="secondary" className={s.cancelBtn} onClick={onClose}>Cancel</Button>
        <Button className={s.primaryBtn} onClick={() => { onRefresh(); onClose(); }}>Refresh queue</Button></>}>
      <div className={s.failure} role="alert"><p className={s.failureTitle}>{title}</p><p>{failure?.message}</p></div>
    </Dialog>
  );
}

// ---------- desk dialogs (staff, admin). Layout of the reason dialog 4:2080: field, notice, Cancel / primary. ----------

type ReasonProps = { e: QueueEntry | null; busy: boolean; onClose: () => void; onConfirm: (reason: string) => void };

/** One text field and a notice. `required` mirrors the server, which refuses an empty reason for these actions. */
export function ReasonDialog({ e, busy, onClose, onConfirm, title, description, label, required, primary, kind = "primary", children }: ReasonProps & {
  title: string; description?: ReactNode; label: string; required: boolean; primary: string; kind?: ButtonKind; children: ReactNode;
}) {
  return (
    <Dialog open={!!e} onClose={onClose} title={title} description={description}
      onSubmit={(ev) => onConfirm(field(ev, "reason").trim())} footer={footer(onClose, primary, busy, kind)}>
      <TextField label={label} name="reason" required={required} maxLength={200} autoComplete="off" />
      {children}
    </Dialog>
  );
}

/** Emergency priority (staff-controlled; the system never judges urgency). Reference for the Emergency screen: 4:2114. */
export function EmergencyDialog(p: ReasonProps) {
  const e = p.e;
  return (
    <ReasonDialog {...p} title={e ? `Give token ${tokenText(e.token)} emergency priority?` : ""} description={e?.patient_name}
      label="Reason *" required primary="Give emergency priority" kind="danger">
      <Callout tone="urgent">{notice("Goes above every priority category.", "Logged with your name and the reason.")}</Callout>
    </ReasonDialog>
  );
}

/** Undo an emergency or a priority category, with the reason on record. */
export function RemovePriorityDialog(p: ReasonProps) {
  const e = p.e;
  return (
    <ReasonDialog {...p} title={e ? `Remove priority from token ${tokenText(e.token)}?` : ""} description={e?.patient_name}
      label="Reason *" required primary="Remove priority">
      <Callout>{notice(`Was ${e?.priority ?? "priority"}.`, "They go back to their routine place. The reason is kept on record.")}</Callout>
    </ReasonDialog>
  );
}

/** Late patients rule B: a skipped patient normally rejoins at the end; putting them next is a written exception. */
export function ReinsertNextDialog(p: ReasonProps) {
  const e = p.e;
  return (
    <ReasonDialog {...p} title={e ? `Reinsert token ${tokenText(e.token)} next?` : ""} description="Policy exception: staff only, reason required."
      label="Reason for the exception *" required primary="Reinsert next">
      <Callout>{notice("Policy exception.", `${e?.patient_name ?? "They"} goes next among routine patients (still after the current patient, emergencies and priority categories) instead of rejoining at the end. Logged with your name and reason.`)}</Callout>
    </ReasonDialog>
  );
}

/** Cancel a waiting visit at the desk; the patient is told (alert "cancelled"). */
export function CancelVisitDialog(p: ReasonProps) {
  const e = p.e;
  return (
    <ReasonDialog {...p} title={e ? `Cancel token ${tokenText(e.token)}?` : ""} description={e?.patient_name}
      label="Reason (optional)" required={false} primary="Cancel visit" kind="danger">
      <Callout>{notice("The patient is told the visit was cancelled.", "The visit stays on record as cancelled.")}</Callout>
    </ReasonDialog>
  );
}

/** Hospital priority category from policy (ranked after emergencies, before routine patients). */
export function PriorityDialog({ e, categories, busy, onClose, onConfirm }: { e: QueueEntry | null; categories: string[]; busy: boolean; onClose: () => void; onConfirm: (category: string) => void }) {
  return (
    <Dialog open={!!e} onClose={onClose} title={e ? `Priority for token ${tokenText(e.token)}` : ""} description={e?.patient_name}
      onSubmit={(ev) => onConfirm(field(ev, "category"))} footer={footer(onClose, "Set priority", busy, "primary", !categories.length)}>
      <SelectField label="Category *" name="category" required>
        {categories.map((c) => <option key={c}>{c}</option>)}
      </SelectField>
      <Callout>{notice("Ranked after emergencies and before routine patients.", "Logged with your name and the category.")}</Callout>
    </Dialog>
  );
}

/** Move one waiting patient (`e`) or everyone waiting (`all`) to a colleague in the same department holding OPD. */
export function MoveDialog({ e, all, from, colleagues, busy, onClose, onConfirm }: {
  e: QueueEntry | null; all?: boolean; from: string; colleagues: OverviewDoctor[]; busy: boolean; onClose: () => void; onConfirm: (toDoctorId: number) => void;
}) {
  return (
    <Dialog open={!!e || !!all} onClose={onClose} title={all ? `Move everyone waiting for ${from}?` : e ? `Move token ${tokenText(e.token)} to a colleague?` : ""}
      description={all ? "Booked and checked-in patients move in queue order. Called, in-consultation and skipped patients stay." : e?.patient_name}
      onSubmit={(ev) => onConfirm(Number(field(ev, "to")))} footer={footer(onClose, all ? "Move all waiting" : "Move patient", busy, "primary", !colleagues.length)}>
      {colleagues.length ? (
        <>
          <SelectField label="Move to *" name="to" required>
            {colleagues.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.waiting} waiting</option>)}
          </SelectField>
          <Callout tone="info">{notice(all ? "Everyone still waiting moves, in queue order." : "They join the end of the colleague’s queue with a new token.",
            "Each patient keeps their check-in and priority, and is told about the move.")}</Callout>
        </>
      ) : <EmptyState title="No other doctor in this department is holding OPD now." />}
    </Dialog>
  );
}

export type StaffPick = "checkIn" | "notHere" | "noShow" | "emergency" | "priority" | "removePriority" | "move" | "cancel" | "reinsert";

/** Every desk action allowed on one patient, as one list (no Figma frame; legacy shows them as row buttons). */
export function PatientActionsDialog({ e, role, busy, onClose, onPick }: {
  e: QueueEntry | null; role: Role; busy: boolean; onClose: () => void; onPick: (kind: StaffPick) => void;
}) {
  const a = e ? staffActions(e, role) : null;
  const late = e?.status === "booked" && e.turn_missed;
  const items: [boolean | undefined, StaffPick, ReactNode][] = [
    [a?.checkIn, "checkIn", e?.status === "skipped" ? "Check in · rejoins at the end of the queue" : late ? "Check in · keeps their place" : "Check in"],
    [a?.reinsert, "reinsert", <span>Reinsert next… <span className={s.exception}>(policy exception, reason required)</span></span>],
    [a?.notHere, "notHere", "Not here…"],
    [a?.skip, "noShow", "Skip / no-show…"],
    [a?.emergency, "emergency", "Emergency priority…"],
    [a?.priority, "priority", "Priority category…"],
    [a?.removePriority, "removePriority", "Remove priority…"],
    [a?.move, "move", "Move to a colleague…"],
    [a?.cancel, "cancel", "Cancel visit…"],
  ];
  const shown = items.filter(([ok]) => ok);
  return (
    <Dialog open={!!e} onClose={onClose} size="md" title={e ? `Token ${tokenText(e.token)} · ${e.patient_name}` : ""} description={e && entryDetail(e)}
      footer={<Button kind="secondary" className={s.cancelBtn} onClick={onClose}>Close</Button>}>
      {shown.length ? (
        <div className={s.actionList}>
          {shown.map(([, kind, label]) => <Button key={kind} kind="secondary" block disabled={busy} onClick={() => onPick(kind)}>{label}</Button>)}
        </div>
      ) : <EmptyState title="Nothing to do from the desk.">This visit is {e?.status.replace("_", " ")}. The doctor’s screen handles the rest.</EmptyState>}
    </Dialog>
  );
}

function addMinutes(iso: string, m: number) {
  const d = new Date(Date.parse(iso) + m * 60000);
  return `${iso.slice(0, 11)}${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function statusNow(q: QueueState) {
  const d = q.doctor;
  return d.status === "break" ? `on a break until ${clock(d.break_until)}` : d.status === "delayed" ? `running late until ${clock(d.break_until)}`
    : d.status === "unavailable" ? "unavailable today" : "available";
}
