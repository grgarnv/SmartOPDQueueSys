import { useState } from "react";
import { api } from "../../api/client";
import type { AppointmentView, ApptStatus, LookupPatient, LookupVisit, Overview, WalkIn } from "../../api/types";
import { Dialog } from "../../design/Dialog";
import { Button, Callout, ErrorState, LoadingState, Message, TextButton, TextField } from "../../design/ui";
import { ALERT_LABEL, CHANNELS, SENT_LABEL, STATUS_LABEL, clock, longDate, tokenText } from "../../lib/format";
import { useFormAction } from "../../lib/useFormAction";
import { ReinsertNextDialog } from "../queue/dialogs";
import { useQueue } from "../queue/useQueue";
import { DoctorPicker } from "./DoctorPicker";
import s from "./frontDesk.module.css";

// Front desk dialogs: Appointment found (4:2227), Patient checked in / Appointment token issued (4:2134 = 4:4219),
// Token print preview (4:4481 = 4:4490), plus walk-in token for an account and the desk password reset (legacy
// workflows with no Figma frame). Everything shown comes from the server's replies.
// Left out everywhere (not stored): age, gender, UHID, appointment code, room, session, hospital name, wait ranges,
// and the "SMS with the token and tracking link" line (no such SMS or link exists).

export type Issued = { r: AppointmentView | WalkIn; was?: ApptStatus };

/** Opened from a lookup visit. Reads that doctor's live queue for the grace / skipped details and the version. */
export function AppointmentFoundDialog({ row, onClose, onCheckedIn, onReinserted }: {
  row: LookupVisit; onClose: () => void; onCheckedIn: (i: Issued) => void; onReinserted: (text: string) => void;
}) {
  const qh = useQueue(row.doctor_id);
  const e = qh.queue?.entries.find((x) => x.id === row.id);
  const [reinsert, setReinsert] = useState(false);
  const status = e?.status ?? row.status;
  const late = status === "booked" && e?.turn_missed;
  const canCheckIn = status === "booked" || status === "skipped";

  const state = status === "skipped" ? { tone: s.boxAmber, title: "Skipped at their turn", line: `Skipped · ${e?.skip_reason || "no-show"}` }
    : late ? { tone: s.boxAmber, title: e?.can_skip ? "Turn passed · grace period over" : "Turn passed · grace period running", line: "Not checked in yet" }
    : status === "booked" ? { tone: s.boxTeal, title: "✓  Booked for today", line: e?.eta ? `Expected around ${clock(e.eta)} (estimate)` : "Not checked in yet" }
    : { tone: s.boxNeutral, title: `Already ${STATUS_LABEL[status].toLowerCase()}`, line: "Nothing to do here: the queue monitor has the rest." };

  const checkIn = async () => {
    const r = await qh.checkIn(row.id);
    if (r) onCheckedIn({ r, was: status });
  };

  return (
    <>
      <Dialog open onClose={onClose} size="wide" title="Appointment found" description="Confirm patient identity and appointment before check-in."
        footer={<>
          <Button kind="secondary" className={s.cancelBtn} onClick={onClose}>Cancel</Button>
          <span className={s.footRight}>
            {status === "skipped" && <TextButton danger onClick={() => setReinsert(true)} disabled={qh.busy || !e}>Reinsert next… (policy exception)</TextButton>}
            {canCheckIn && (
              <Button className={s.primaryBtn} onClick={checkIn} disabled={qh.busy || !qh.queue}>
                {status === "skipped" ? "Check in · rejoin at end" : late ? "Check in · keeps their place" : "Check in & issue token"}
              </Button>
            )}
          </span>
        </>}>
        <div className={s.found}>
          <div>
            <p className={s.foundName}>{row.patient_name}</p>
            <p className={s.foundSub}>Token {tokenText(row.token)}{row.phone ? ` · Mobile ending ${row.phone.replace(/\s/g, "").slice(-4)}` : ""}</p>
          </div>
          {!qh.queue && qh.error ? (
            <ErrorState title={`Couldn’t read ${row.doctor}’s queue`} action={<Button kind="secondary" onClick={qh.refresh}>Try again</Button>}>
              {qh.error} Check-in waits until the queue can be read.
            </ErrorState>
          ) : !qh.queue ? <LoadingState title="Reading the queue…" rows={1} /> : (
            <div className={`${s.box} ${state.tone}`}>
              <p className={s.boxTitle}>{state.title}</p>
              <p className={s.boxLine}>Today · {row.doctor} · {state.line}</p>
            </div>
          )}
          {status === "skipped" && (
            <Callout><strong>Checking in puts {row.patient_name} at the end of {row.doctor}’s queue.</strong> The visit stays on record. Putting them next instead is a policy exception that needs a written reason.</Callout>
          )}
          {late && <Callout tone="info"><strong>Late, within the rules:</strong> checking in now keeps their original place in the queue.</Callout>}
          {qh.failure && <Callout tone="urgent">{qh.failure.message}</Callout>}
          <p className={s.instruction}>Confirm the name and mobile number with the patient before checking in.</p>
        </div>
      </Dialog>
      <ReinsertNextDialog e={reinsert && e ? e : null} busy={qh.busy} onClose={() => setReinsert(false)}
        onConfirm={async (reason) => {
          const r = e && await qh.act("reinsert_front", { appointment_id: e.id, reason });
          setReinsert(false);
          if (r) onReinserted(`✓  ${row.patient_name} reinserted next among routine patients · Token ${tokenText(row.token)} · policy exception logged`);
        }} />
    </>
  );
}

/** 4:2134 / 4:4219 · the token the server issued, with where the patient now is in the queue. */
export function TokenIssuedDialog({ issued, onClose, onPrint }: { issued: Issued | null; onClose: () => void; onPrint: () => void }) {
  const r = issued?.r;
  const w = r && "username" in r ? r : null;
  const note = r?.notifications[0];
  const where = !r ? "" : r.ahead == null ? `Status: ${STATUS_LABEL[r.status]}`
    : `${r.ahead} ahead in the queue${issued?.was === "skipped" ? " · rejoined at the end of the queue" : issued?.was === "booked" ? " · kept their place" : ""}`;
  // A walk-in that matches a visit already called, in consultation or completed changes nothing (server): say so.
  const checkedIn = r?.status === "checked_in";
  return (
    <Dialog open={!!r} onClose={onClose} size="xs" title={checkedIn ? "Patient checked in" : "Already on today’s list"}
      description={checkedIn ? "The visit is saved and the live queue is updated." : `Nothing was changed: this visit is ${r ? STATUS_LABEL[r.status].toLowerCase() : ""}.`}
      footer={<div className={s.issuedFoot}>
        <Button kind="secondary" onClick={onClose}>Done</Button>
        {(checkedIn || r?.status === "booked") && <Button onClick={onPrint}>Print token</Button>}
      </div>}>
      {r && (
        <div className={s.issued}>
          <div className={s.tokenBox}>
            <p className={s.tokenLabel}>YOUR TOKEN</p>
            <p className={s.tokenBig}>{tokenText(r.token)}</p>
            <p className={s.tokenName}>{r.patient_name}</p>
          </div>
          <div>
            <p className={s.issuedDoc}>{r.doctor.department} · {r.doctor.name}</p>
            <p className={s.issuedWhere}>{where}</p>
          </div>
          <p className={s.issuedEta}>{r.eta && r.ahead != null ? `Expected around ${clock(r.eta)} · estimate, may change` : r.ahead != null ? "No expected time yet: the doctor is not available" : STATUS_LABEL[r.status]}</p>
          {w?.existing && <Callout tone="info">They already had a visit with {r.doctor.name} today (token {tokenText(r.token)}). It is now {STATUS_LABEL[r.status].toLowerCase()}.
            {checkedIn && <> If they had been skipped, they have rejoined at the end of the queue.</>}</Callout>}
          {w?.warning && <Callout>{w.warning}</Callout>}
          {(note || w) && (
            <div className={s.issuedSmall}>
              {note && <p>Latest alert: {ALERT_LABEL[note.purpose] ?? note.purpose} · {CHANNELS[note.channel] ?? note.channel} {SENT_LABEL[note.status] ?? note.status}</p>}
              {w && <p>App username: <strong>{w.username}</strong>. To use the app, the desk can set a password from Find a patient (family members sign in through their guardian).</p>}
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

/** 4:4481 / 4:4490 · print preview; only the slip prints (see @media print in frontDesk.module.css). */
export function TokenSlipDialog({ r, onClose }: { r: AppointmentView | null; onClose: () => void }) {
  return (
    <Dialog open={!!r} onClose={onClose} title="Token print preview"
      footer={<div className={s.issuedFoot}><Button kind="secondary" onClick={onClose}>Done</Button><Button onClick={() => window.print()}>Print</Button></div>}>
      {r && (
        <div className={s.slip} data-print-slip>
          <p className={s.slipDept}>{r.doctor.department}</p>
          <p className={s.slipToken}>{tokenText(r.token)}</p>
          <p className={s.slipName}>{r.patient_name}</p>
          <p className={s.slipLines}>
            {r.doctor.name}<br />
            OPD {clock(r.doctor.opd_start)}–{clock(r.doctor.opd_end)} · {longDate(r.day)}<br />
            {r.checked_in_at && <>Checked in {clock(r.checked_in_at)}<br /></>}
            {r.eta && r.ahead != null && <>Expected around {clock(r.eta)} (estimate, may change)</>}
          </p>
          <p className={s.slipNote}>Keep this token. Watch the waiting-room screen for your number; times are estimates. Priority cases may change the order.</p>
        </div>
      )}
    </Dialog>
  );
}

/** Legacy "Token with the walk-in doctor" for an existing account (family members too: alerts go to the guardian). */
export function GiveTokenDialog({ patient, o, start, onClose, onIssued }: {
  patient: LookupPatient | null; o?: Overview; start?: number; onClose: () => void; onIssued: (r: WalkIn) => void;
}) {
  const [doctorId, setDoctorId] = useState<number | undefined>(start);
  const { onSubmit, msg, busy, setMsg } = useFormAction(
    () => api<WalkIn>("/api/staff/walkin", { patient_id: patient!.id, doctor_id: doctorId }),
    { ok: "", after: (r) => { close(); onIssued(r); } },
  );
  const close = () => { setMsg(null); onClose(); };
  return (
    <Dialog open={!!patient} onClose={close} title={patient ? `Walk-in token for ${patient.name}` : ""}
      description={`${patient?.guardian ? `Family member of ${patient.guardian}: alerts go to the guardian. ` : ""}They are checked in with the doctor you choose.`}
      onSubmit={onSubmit} footer={<><Button kind="secondary" className={s.cancelBtn} onClick={close}>Cancel</Button>
        <Button type="submit" className={s.primaryBtn} disabled={busy || !doctorId}>Give token &amp; check in</Button></>}>
      <SkippedWarning />
      <DoctorPicker o={o} doctorId={doctorId} onChange={setDoctorId} />
      <Message msg={msg?.ok ? null : msg} />
    </Dialog>
  );
}

/** Walk-in paths check in an existing booked or skipped visit (server): a skipped one goes to the END of the queue. */
export function SkippedWarning() {
  return (
    <Callout>If they already have a skipped visit with this doctor today, this checks them in at the <strong>end of the queue</strong>.
      To keep the visit in view first, use Check in (or Reinsert next, a policy exception) from today’s visits instead.</Callout>
  );
}

/** Desk password reset (legacy prompt): the patient's other sessions are signed out. Hidden for family members. */
export function PatientPasswordDialog({ patient, onClose }: { patient: LookupPatient | null; onClose: () => void }) {
  const { onSubmit, msg, busy, setMsg } = useFormAction(
    (f) => api<{ ok: true; username: string }>("/api/staff/patient-password", { patient_id: patient!.id, password: f.password }),
    { ok: (r) => `Password set. They sign in as ${r.username}.`, after: (_, form) => form.reset() },
  );
  const close = () => { setMsg(null); onClose(); };
  return (
    <Dialog open={!!patient} onClose={close} title={patient ? `Reset password for ${patient.name}` : ""}
      description="Tell them the new password privately. They are signed out everywhere else."
      onSubmit={onSubmit} footer={<><Button kind="secondary" className={s.cancelBtn} onClick={close}>{msg?.ok ? "Done" : "Cancel"}</Button>
        <Button type="submit" className={s.primaryBtn} disabled={busy}>Set password</Button></>}>
      <TextField label="New password for this patient" name="password" type="password" autoComplete="new-password" required hint="At least 8 characters" />
      <Message msg={msg} />
    </Dialog>
  );
}

