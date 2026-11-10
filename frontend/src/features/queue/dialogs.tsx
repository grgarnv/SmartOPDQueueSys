import type { FormEvent } from "react";
import { useState } from "react";
import type { DoctorStatus, QueueEntry, QueueState } from "../../api/types";
import { Dialog } from "../../design/Dialog";
import { Button, Callout, EmptyState, SelectField, TextField } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import type { Failure } from "../queue/useQueue";
import { isLate, isWaiting } from "../queue/present";
import { QueueTable } from "./QueueTable";
import s from "./consultation.module.css";

const field = (e: FormEvent<HTMLFormElement>, name: string) => String(new FormData(e.currentTarget).get(name) ?? "");
const footer = (cancel: () => void, primary: string, busy?: boolean) => (
  <><Button kind="secondary" className={s.cancelBtn} onClick={cancel}>Cancel</Button>
    <Button type="submit" className={s.primaryBtn} disabled={busy}>{primary}</Button></>
);

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
      <Callout><strong>The visit stays in Skipped / late.</strong><br /><span className={s.calloutSub}>The front desk can reinsert the patient once they arrive.</span></Callout>
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
      <Callout><strong>Check-in is cleared.</strong><br /><span className={s.calloutSub}>
        {e?.status === "called" ? "Their grace period starts now. Once it runs out you can mark them as a no-show." : "They wait again until they check in."}</span></Callout>
    </Dialog>
  );
}

const DURATIONS = [10, 15, 20, 30, 45, 60];

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

/** Availability menu (2:350 → 4:2171) with the delay fields from 4:2184. One status at a time, as the server keeps. */
export function AvailabilityDialog({ open, q, busy, onClose, onConfirm }: {
  open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onConfirm: (status: DoctorStatus, minutes?: number) => void;
}) {
  const [choice, setChoice] = useState<DoctorStatus>("available");
  const options: [DoctorStatus, string, string][] = [
    ["available", "Available", "Seeing patients as usual."],
    ["delayed", "Running late", "Queue order is preserved. Waiting estimates adjust."],
    ["break", "On a break", "No new calls. Estimates start from your return."],
    ["unavailable", "Unavailable today", "Patients see no time for your queue. Resets at the next OPD day."],
  ];
  return (
    <Dialog open={open} onClose={onClose} title="Your availability" description={q && `Now: ${statusNow(q)}`}
      onSubmit={(ev) => onConfirm(choice, choice === "delayed" || choice === "break" ? Number(field(ev, "minutes")) : undefined)}
      footer={footer(onClose, choice === "delayed" ? "Update & notify" : "Update availability", busy)}>
      <fieldset className={s.choices}>
        <legend className={s.srOnly}>Availability</legend>
        {options.map(([v, label, hint]) => (
          <label key={v} className={`${s.choice} ${choice === v ? s.chosen : ""}`}>
            <input type="radio" name="status" value={v} checked={choice === v} onChange={() => setChoice(v)} />
            <span><span className={s.choiceLabel}>{label}</span><span className={s.choiceHint}>{hint}</span></span>
          </label>
        ))}
      </fieldset>
      {(choice === "delayed" || choice === "break") && (
        <SelectField label={choice === "delayed" ? "Delay duration" : "Expected return"} name="minutes" defaultValue="15" key={choice}>
          {DURATIONS.map((m) => <option key={m} value={m}>{m} minutes</option>)}
        </SelectField>
      )}
    </Dialog>
  );
}

/** 4:2152 · Skipped & late patients. Doctors can skip a late patient once the server allows it; reinserting is a front-desk action. */
export function SkippedLateDialog({ open, q, busy, onClose, onNoShow }: { open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onNoShow: (e: QueueEntry) => void }) {
  const rows = q ? q.entries.filter(isLate) : [];
  return (
    <Dialog open={open} onClose={onClose} size="md" title="Skipped & late patients" description="No visit is deleted. The front desk reinserts a patient once they arrive."
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
              {e.status !== "skipped" && e.can_skip && <Button kind="secondary" disabled={busy} onClick={() => onNoShow(e)}>Skip / no-show</Button>}
            </li>
          ))}
        </ul>
      ) : <EmptyState title="Nobody skipped or late.">Patients who miss their turn appear here, and stay on record.</EmptyState>}
    </Dialog>
  );
}

/** "View all N patients": the whole waiting list with the per-patient actions a doctor has (not here, no-show). */
export function FullQueueDialog({ open, q, busy, onClose, onNotHere, onNoShow }: {
  open: boolean; q?: QueueState; busy: boolean; onClose: () => void; onNotHere: (e: QueueEntry) => void; onNoShow: (e: QueueEntry) => void;
}) {
  const rows = q ? q.entries.filter((e) => isWaiting(e) || (isLate(e) && e.status !== "skipped")) : [];
  return (
    <Dialog open={open} onClose={onClose} size="lg" title={q ? `${q.doctor.department} · Full queue` : "Full queue"}
      description={`${rows.length} waiting · Ordered by clinical priority, then check-in`}
      footer={<Button kind="secondary" className={s.cancelBtn} onClick={onClose}>Close</Button>}>
      {q && rows.length ? (
        <div className={s.dialogTable}>
          <QueueTable q={q} rows={rows} label="Full queue" actions={(e) =>
            e.can_skip ? <Button kind="secondary" disabled={busy} onClick={() => onNoShow(e)}>No-show</Button>
              : e.status === "checked_in" ? <Button kind="secondary" disabled={busy} onClick={() => onNotHere(e)}>Not here</Button> : null} />
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

function addMinutes(iso: string, m: number) {
  const d = new Date(Date.parse(iso) + m * 60000);
  return `${iso.slice(0, 11)}${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function statusNow(q: QueueState) {
  const d = q.doctor;
  return d.status === "break" ? `on a break until ${clock(d.break_until)}` : d.status === "delayed" ? `running late until ${clock(d.break_until)}`
    : d.status === "unavailable" ? "unavailable today" : "available";
}
