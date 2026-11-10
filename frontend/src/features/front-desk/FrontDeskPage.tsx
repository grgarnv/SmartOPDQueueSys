import { useRef, useState } from "react";
import { Link } from "react-router";
import { api, qs } from "../../api/client";
import type { Lookup, LookupPatient, LookupVisit, Overview, OverviewDoctor, WalkIn } from "../../api/types";
import { Dialog } from "../../design/Dialog";
import { Button, EmptyState, ErrorState, LoadingState, Message, PageHeader, Panel, SelectField, Status, Table, TextField, buttonClass } from "../../design/ui";
import { LANGS, STATUS_LABEL, clock, tokenText } from "../../lib/format";
import { useFlash, useFormAction } from "../../lib/useFormAction";
import { useLive } from "../../lib/useLive";
import { SessionFacts } from "../queue/SessionFacts";
import { DisplayLink } from "../queue/DisplayLink";
import { entryStatus, openDoctors, statusOf } from "../queue/present";
import { useOverview, usePolicy } from "../queue/useDesk";
import { useQueue } from "../queue/useQueue";
import { AlertLog } from "./AlertLog";
import { DoctorPicker } from "./DoctorPicker";
import type { Issued } from "./dialogs";
import { AppointmentFoundDialog, GiveTokenDialog, PatientPasswordDialog, TokenIssuedDialog, TokenSlipDialog } from "./dialogs";
import s from "./frontDesk.module.css";

// Front desk: Figma frame 02 (2:25) and its result states 21 (4:3942, registration saved) and 22 (4:4081,
// appointment checked in). Left out (not stored by the server): age, gender, reason for visit, UHID, room,
// "Morning" session, counter, visit kind (walk-in / appointment / follow-up), wait ranges, the ⌘K hint (no such
// shortcut) and the 3-step wizard row (the server registers and checks in in one step).
export function FrontDeskPage() {
  const ov = useOverview();
  const pol = usePolicy();
  const o = ov.data;
  const [doctorId, setDoctorId] = useState<number>();
  const chosen = openDoctors(o).find((d) => d.id === doctorId);
  const [msg, say] = useFlash();
  const [issued, setIssued] = useState<Issued | null>(null);
  const [slip, setSlip] = useState<Issued["r"] | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const walkin = useFormAction(
    (f) => api<WalkIn>("/api/staff/walkin", { name: f.name, phone: f.phone, lang: f.lang, doctor_id: chosen?.id }),
    { ok: "", after: (r, form) => { form.reset(); issue({ r }); } },
  );
  const issue = (i: Issued) => {
    setIssued(i);
    const { r, was } = i;
    const tok = `Token ${tokenText(r.token)}`;
    say({ ok: true, text: "existing" in r && !r.existing ? `✓  ${r.patient_name} registered and checked in · ${tok}`
      : r.status !== "checked_in" ? `✓  ${r.patient_name} already had a visit with ${r.doctor.name} today · ${tok} · ${STATUS_LABEL[r.status].toLowerCase()} · nothing changed`
      : "existing" in r ? `✓  ${r.patient_name} already had a visit with ${r.doctor.name} today · now checked in · ${tok} · if they had been skipped, they rejoined at the end of the queue`
      : `✓  ${r.patient_name} checked in${was === "skipped" ? " · rejoined at the end of the queue" : was === "booked" ? " · kept their place" : ""} · ${tok}` });
  };
  const p = pol.data;

  return (
    <div className={s.page}>
      <PageHeader title="A smooth start to every visit." sub={<>
        <span>Register, verify and check patients in without losing sight of the queue.</span>
        {p ? <span className={s.code}>Check-in code today <strong>{p.checkin_code}</strong> · {p.require_checkin_code === "1" ? "patients need it to check themselves in" : "not required at the moment"}</span>
          : pol.error && <span className={s.code}>Couldn’t read today’s check-in code: {pol.error}</span>}
      </>}>
        <DisplayLink p={p} error={pol.error} />
        <Button className={s.newPatient} onClick={() => { const f = formRef.current?.elements.namedItem("name") as HTMLInputElement | null; f?.focus(); f?.scrollIntoView({ block: "center" }); }}>
          +&nbsp;&nbsp;New patient
        </Button>
      </PageHeader>

      <LookupPanel o={o} walkinDoctor={chosen?.id} onIssued={(r) => issue({ r })} onCheckedIn={issue} say={say} />

      <div className={s.grid}>
        <Panel className={s.walkin} title="Walk-in registration" aside={<Status tone="info">Walk-in</Status>}>
          <form ref={formRef} onSubmit={walkin.onSubmit} className={s.form}>
            <div className={s.pair}>
              <TextField label="Full name *" name="name" required maxLength={200} autoComplete="off" />
              <TextField label="Phone for alerts (optional)" name="phone" type="tel" placeholder="+91 98765 43210" autoComplete="off"
                hint="Without a phone the patient gets no SMS alerts." />
              <SelectField label="Alert language" name="lang" defaultValue="en">
                {Object.entries(LANGS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </SelectField>
              {/* Figma "Patient identifier": the server creates the app username (walkin-…) and returns it */}
              <TextField label="App username" disabled placeholder="Created when you save" />
            </div>
            <hr className={s.rule} />
            <h3 className={s.subhead}>Visit details</h3>
            {o ? <DoctorPicker o={o} doctorId={chosen?.id} onChange={setDoctorId} />
              : ov.error ? <ErrorState title="Couldn’t load today’s doctors" action={<Button kind="secondary" onClick={ov.refresh}>Try again</Button>}>
                  {ov.error} A walk-in needs a doctor, so saving waits until the list loads.</ErrorState>
              : <LoadingState title="Loading today’s doctors…" rows={1} />}
            {chosen && o && <QueueLine d={chosen} updatedAt={o.updated_at} />}
            <p className={s.skipNote}>If name and phone match a patient skipped by this doctor today, saving checks them in at the end of the queue.</p>
            <Message msg={walkin.msg?.ok ? null : walkin.msg} />
            <div className={s.formFoot}>
              <span className={s.required}>Required fields are marked *</span>
              <Button type="submit" className={s.save} disabled={walkin.busy || !chosen}>Save &amp; check in</Button>
            </div>
          </form>
        </Panel>

        <div className={s.side}>
          {chosen && o ? <DoctorSide d={chosen} o={o} /> : (
            <>
              <Panel className={s.session} title="Session">
                <EmptyState title="Choose a doctor">Their queue status appears here when you choose a doctor for the walk-in.</EmptyState>
              </Panel>
              <Panel className={s.recent} title="Recent check-ins">
                <EmptyState title="No doctor chosen.">Check-ins for the chosen doctor appear here, newest first.</EmptyState>
              </Panel>
            </>
          )}
        </div>
      </div>

      {/* result line of states 21 / 22 (4:3942, 4:4081) sits right under the panels, above the alert log */}
      <p className={msg ? (msg.ok ? s.result : s.resultErr) : s.foot} role="status">
        {msg ? msg.text : "Patient information is visible only to authorized staff. Confirm identity before creating a record."}
      </p>

      <AlertLog />

      <TokenIssuedDialog issued={issued} onClose={() => setIssued(null)} onPrint={() => { setSlip(issued?.r ?? null); setIssued(null); }} />
      <TokenSlipDialog r={slip} onClose={() => setSlip(null)} />
    </div>
  );
}

/** "● Queue open · 12 waiting · queue clears around 11:40 AM" under the doctor choice (no wait range: not computed here). */
function QueueLine({ d, updatedAt }: { d: OverviewDoctor; updatedAt: string }) {
  const st = statusOf(d, updatedAt, d.current_status === "in_consultation");
  return (
    <p className={`${s.queueLine} ${s[st.tone]}`}>
      <span aria-hidden="true">●&nbsp;&nbsp;</span>{st.label} · {d.waiting} waiting{d.clears_at ? ` · queue clears around ${clock(d.clears_at)} (estimate)` : ""}
    </p>
  );
}

/** Session visibility (2:25 right column) and recent check-ins for the doctor chosen in the walk-in form. */
function DoctorSide({ d, o }: { d: OverviewDoctor; o: Overview }) {
  const { queue: q, error, refresh } = useQueue(d.id);
  const [all, setAll] = useState(false);
  // No endpoint lists check-ins across doctors; this doctor's queue has each visit's checked_in_at.
  const checked = (q?.entries ?? []).filter((e) => e.checked_in_at).sort((a, b) => b.checked_in_at!.localeCompare(a.checked_in_at!));
  const list = (rows: typeof checked) => (
    <ul className={s.checkins}>
      {rows.map((e) => (
        <li key={e.id}>
          <span className={s.ciToken}>{tokenText(e.token)}</span>
          <span className={s.ciText}><span className={s.ciName}>{e.patient_name}</span><span className={s.ciSub}>{clock(e.checked_in_at)} · {entryStatus(e).label}</span></span>
          {e.status === "checked_in" && <span className={s.tick} aria-hidden="true">✓</span>}
        </li>
      ))}
    </ul>
  );
  return (
    <>
      <Panel className={s.session} title={d.department}>
        <SessionFacts d={d} updatedAt={o.updated_at} />
        <p className={s.estNote}>Estimates may change for priority cases.</p>
      </Panel>
      <Panel className={s.recent} title="Recent check-ins" sub={`Today · ${d.name}`}>
        {!q ? (error ? <ErrorState title="Couldn’t load this doctor’s check-ins" action={<Button kind="secondary" onClick={refresh}>Try again</Button>}>{error}</ErrorState>
          : <LoadingState rows={2} />) : checked.length ? list(checked.slice(0, 3)) : <EmptyState title="No check-ins yet today." />}
        {checked.length > 3 && <button type="button" className={s.textLink} onClick={() => setAll(true)}>View all {checked.length} check-ins today →</button>}
      </Panel>
      <Dialog open={all} onClose={() => setAll(false)} size="md" title={`Check-ins today · ${d.name}`} description="Newest first."
        footer={<><span /><Button kind="secondary" onClick={() => setAll(false)}>Close</Button></>}>
        {list(checked)}
      </Dialog>
    </>
  );
}

/** "Find a patient or appointment": GET /api/lookup, kept live so statuses follow the queue. */
function LookupPanel({ o, walkinDoctor, onIssued, onCheckedIn, say }: {
  o?: Overview; walkinDoctor?: number; onIssued: (r: WalkIn) => void; onCheckedIn: (i: Issued) => void; say: (m: { text: string; ok: boolean }) => void;
}) {
  const [term, setTerm] = useState("");
  const look = useLive(() => (term ? api<Lookup>("/api/lookup?" + qs({ q: term })) : Promise.resolve(null)), [term]);
  const [found, setFound] = useState<LookupVisit | null>(null);
  const [give, setGive] = useState<LookupPatient | null>(null);
  const [pw, setPw] = useState<LookupPatient | null>(null);
  const r = look.data;
  return (
    <Panel className={s.lookup} aria-label="Find a patient or appointment">
      <form className={s.search} onSubmit={(e) => { e.preventDefault(); setTerm(String(new FormData(e.currentTarget).get("q") ?? "").trim()); look.refresh(); }}>
        <TextField label="Find a patient or appointment" name="q" type="search" required maxLength={200} autoComplete="off" placeholder="Search by name, phone, username or token" />
        <Button type="submit" kind="secondary" className={s.find}>Find appointment</Button>
      </form>
      {term && (look.error && !r ? <Message msg={{ text: look.error, ok: false }} /> : !r ? <LoadingState title="Searching…" rows={2} /> : (
        <div className={s.results}>
          <Message msg={{ text: `${r.results.length} on today’s list, ${r.patients.length} patient accounts.`, ok: true }} />
          <h3 className={s.listHead}>TODAY’S VISITS ({r.results.length})</h3>
          {r.results.length ? (
            <Table label="Today’s visits" columns={["Token", "Patient", "Phone", "Doctor", "Status", ""]}
              rows={r.results.map((v) => ({ key: v.id, cells: [
                <span className={s.tok}>{tokenText(v.token)}</span>, <span className={s.name}>{v.patient_name}</span>, v.phone ?? "–", v.doctor,
                <Status tone={v.status === "skipped" ? "caution" : v.status === "checked_in" ? "success" : "neutral"}>{STATUS_LABEL[v.status]}</Status>,
                <span className={s.rowActions}>
                  <Button kind="secondary" onClick={() => setFound(v)} aria-label={`${v.status === "booked" || v.status === "skipped" ? "Check in" : "Details for"} ${v.patient_name}, token ${tokenText(v.token)}`}>
                    {v.status === "skipped" ? "Check in · end of queue…" : v.status === "booked" ? "Check in…" : "Details"}
                  </Button>
                  <Link className={buttonClass("secondary")} to={`/queue-monitor?doctor=${v.doctor_id}`} aria-label={`Open queue: ${v.doctor}, token ${tokenText(v.token)}`}>Open queue</Link>
                </span>,
              ] }))} />
          ) : <p className={s.none}>Nobody on today’s list matches.</p>}
          {r.patients.length > 0 && <>
            <h3 className={s.listHead}>PATIENT ACCOUNTS ({r.patients.length})</h3>
            <Table label="Patient accounts" columns={["Name", "Username", "Phone", "Family of", ""]}
              rows={r.patients.map((a) => ({ key: a.id, cells: [
                <span className={s.name}>{a.name}</span>, a.username, a.phone ?? "–", a.guardian ?? "–",
                <span className={s.rowActions}>
                  <Button kind="secondary" onClick={() => setGive(a)} aria-label={`Walk-in token for ${a.name}`}>Walk-in token…</Button>
                  {/* the server refuses a reset for family members: they sign in through their guardian */}
                  {!a.guardian && <Button kind="secondary" onClick={() => setPw(a)} aria-label={`Reset password for ${a.name}`}>Reset password…</Button>}
                </span>,
              ] }))} />
          </>}
        </div>
      ))}
      {found && <AppointmentFoundDialog row={found} onClose={() => setFound(null)}
        onCheckedIn={(i) => { setFound(null); onCheckedIn(i); }} onReinserted={(text) => { setFound(null); say({ text, ok: true }); }} />}
      <GiveTokenDialog key={give?.id} patient={give} o={o} start={walkinDoctor} onClose={() => setGive(null)} onIssued={onIssued} />
      <PatientPasswordDialog patient={pw} onClose={() => setPw(null)} />
    </Panel>
  );
}
