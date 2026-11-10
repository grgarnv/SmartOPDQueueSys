import type { ReactNode } from "react";
import type { QueueEntry, QueueState } from "../../api/types";
import { Button, EmptyState, Overline, Status } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import { entryDetail, isCurrent, isWaiting } from "../queue/present";
import s from "./consultation.module.css";

// The left card of frame 01 in its states: active consultation (4:1303), urgent consultation (4:4343),
// patient called (4:1131), ready for the next patient (4:952), queue paused (4:1466).
// Which state shows is read straight from the server: the entry that is called / in consultation, else the
// doctor's status, else the first waiting entry in the server's order (late patients are listed separately,
// exactly as in the Up next table).
// Not shown because the backend does not store them: age, sex, UHID, chief complaint, allergies, visit type,
// last visit, patient history, call time and consultation timer.

type Props = {
  q: QueueState;
  busy: boolean;
  completedToday: number;
  onCall: () => void;
  onStart: (e: QueueEntry) => void;
  onComplete: (e: QueueEntry) => void;
  onNotHere: (e: QueueEntry) => void;
  onNoShow: (e: QueueEntry) => void;
  onResume: () => void;
};

export function PatientCard(p: Props) {
  const { q } = p;
  const current = q.entries.find(isCurrent);
  if (current?.status === "in_consultation") return current.emergency ? <Urgent {...p} e={current} /> : <Active {...p} e={current} />;
  if (current?.status === "called") return <Called {...p} e={current} />;
  if (!q.doctor.holds_opd) return <Card tone="neutral" overline="NO OPD TODAY"><EmptyState title="No OPD session today.">This is not one of your OPD days, or you are on leave. Patients cannot book you for today.</EmptyState></Card>;
  if (q.doctor.status === "break" || q.doctor.status === "unavailable") return <Paused {...p} />;
  return <Ready {...p} />;
}

function Card({ tone, overline, aside, children }: { tone: "teal" | "blue" | "amber" | "red" | "neutral"; overline: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className={`${s.card} ${s[tone]}`} aria-label={overline.charAt(0) + overline.slice(1).toLowerCase()}>
      <div className={s.cardHead}><p className={s.cardOverline}>{overline}</p>{aside}</div>
      {children}
    </section>
  );
}

function Who({ e, tone, labelled }: { e: QueueEntry; tone: "teal" | "blue"; labelled?: boolean }) {
  return (
    <div className={s.who}>
      <div className={`${s.tokenBox} ${s[tone]}`}>
        {labelled && <span className={s.tokenLabel}>TOKEN</span>}
        <span className={s.tokenNum}>{tokenText(e.token)}</span>
      </div>
      <div className={s.whoText}>
        <p className={s.patient}>{e.patient_name}</p>
        <p className={s.patientSub}>{entryDetail(e)}</p>
      </div>
    </div>
  );
}

function Facts({ e }: { e: QueueEntry }) {
  return (
    <dl className={s.facts}>
      <div><dt>CHECKED IN</dt><dd>{e.checked_in_at ? clock(e.checked_in_at) : "Not checked in"}</dd></div>
      <div><dt>PRIORITY</dt><dd>{e.emergency ? "Emergency" : e.priority ?? "Routine"}</dd></div>
    </dl>
  );
}

function Active({ e, busy, onComplete }: Props & { e: QueueEntry }) {
  return (
    <Card tone="teal" overline="ACTIVE CONSULTATION" aside={<Status tone="info">In progress</Status>}>
      <Who e={e} tone="teal" labelled />
      <hr className={s.rule} />
      <Facts e={e} />
      <div className={s.cardActions}>
        <Button block disabled={busy} onClick={() => onComplete(e)}>Complete consultation</Button>
      </div>
    </Card>
  );
}

function Urgent({ e, busy, onComplete }: Props & { e: QueueEntry }) {
  return (
    <Card tone="red" overline="URGENT CONSULTATION">
      <div className={s.urgentWho}>
        <span className={s.urgentToken}>{tokenText(e.token)}</span>
        <div className={s.whoText}>
          <p className={s.urgentName}>{e.patient_name}</p>
          <p className={s.patientSub}>{e.checked_in_at ? `Checked in at ${clock(e.checked_in_at)}` : "Not checked in"}</p>
        </div>
      </div>
      <hr className={s.rule} />
      <p className={s.urgentTitle}>Emergency priority</p>
      <p className={s.urgentNote}>Ranked above every other patient in your queue.</p>
      <div className={s.cardActions}>
        <Button block disabled={busy} onClick={() => onComplete(e)}>Complete urgent consultation</Button>
      </div>
    </Card>
  );
}

function Called({ e, busy, onStart, onNotHere, onNoShow }: Props & { e: QueueEntry }) {
  return (
    <Card tone="blue" overline="PATIENT CALLED" aside={<Status tone="info">Awaiting arrival</Status>}>
      <Who e={e} tone="blue" />
      <hr className={s.rule} />
      <p className={s.calledTitle}>Token {tokenText(e.token)} has been called.</p>
      <p className={s.body}>The waiting room display is updated. Start only after confirming the patient’s identity.</p>
      <div className={s.cardActions}>
        <div className={s.split}>
          <Button disabled={busy} onClick={() => onStart(e)}>Start consultation</Button>
          {e.can_skip
            ? <Button kind="secondary" disabled={busy} onClick={() => onNoShow(e)}>Skip / no-show</Button>
            : <Button kind="secondary" disabled={busy} onClick={() => onNotHere(e)}>Not here</Button>}
        </div>
        <p className={s.caption}>{e.can_skip ? "Skipping never deletes the patient’s visit."
          : "Not here keeps their place and starts their grace period. Skipping never deletes the visit."}</p>
      </div>
    </Card>
  );
}

function Ready({ q, busy, completedToday, onCall }: Props) {
  const next = q.entries.find(isWaiting);  // entries arrive in the server's queue order
  return (
    <Card tone="teal" overline="READY FOR THE NEXT PATIENT">
      <p className={s.cardTitle}>A little less waiting.</p>
      <p className={s.body}>{completedToday ? "The previous consultation is complete. " : ""}Call the next checked-in patient when you’re ready.</p>
      <hr className={s.rule} />
      {next ? (
        <div className={s.nextBlock}>
          <Overline>NEXT IN QUEUE</Overline>
          <div className={s.who}>
            <div className={`${s.tokenBox} ${next.emergency ? s.red : s.teal}`}><span className={s.tokenNum}>{tokenText(next.token)}</span></div>
            <div className={s.whoText}><p className={s.nextName}>{next.patient_name}</p></div>
          </div>
          <p className={s.nextDetail}>{entryDetail(next)}</p>
        </div>
      ) : (
        <EmptyState title="All caught up." foot="Queue remains open">No patients are waiting. New check-ins will appear here automatically.</EmptyState>
      )}
      {next && (
        <div className={s.cardActions}>
          <Button block disabled={busy} onClick={onCall}>Call next patient</Button>
          <p className={s.caption}>Calls the token on the display and notifies the patient.</p>
        </div>
      )}
    </Card>
  );
}

function Paused({ q, busy, onResume }: Props) {
  const unavailable = q.doctor.status === "unavailable";
  return (
    <Card tone="amber" overline={unavailable ? "UNAVAILABLE TODAY" : "QUEUE PAUSED"}>
      <div className={s.pauseMark} aria-hidden="true">Ⅱ</div>
      <p className={`${s.cardTitle} ${s.pauseTitle}`}>{unavailable ? "You’re marked unavailable." : "Take the time you need."}</p>
      <p className={s.body}>{unavailable
        ? "Patients see no time for your queue until you are available again. This resets at the start of the next OPD day."
        : "Your queue order is saved. Waiting patients’ estimated times now start from your return."}</p>
      {!unavailable && (
        <div className={s.returnBox}>
          <p className={s.returnTitle}>Expected return · {clock(q.doctor.break_until)}</p>
          <p className={s.returnSub}>On a break</p>
        </div>
      )}
      <div className={s.cardActions}>
        <Button block disabled={busy} onClick={onResume}>{unavailable ? "Mark available" : "Resume queue"}</Button>
        <p className={s.caption}>ETAs will recalculate when you resume.</p>
      </div>
    </Card>
  );
}
