import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Departments, DoctorStatus, QueueEntry, QueueState } from "../../api/types";
import { useMe } from "../../auth/session";
import { Button, EmptyState, ErrorState, LoadingState, PageHeader, Status, TextButton } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import { useLive, useStreamLive } from "../../lib/useLive";
import { doctorStatus, isLate, isWaiting } from "../queue/present";
import { useQueue } from "../queue/useQueue";
import { PatientCard } from "./PatientCard";
import { QueueTable } from "../queue/QueueTable";
import { AvailabilityDialog, FailureDialog, FullQueueDialog, NoShowDialog, NotHereDialog, PauseDialog, SkippedLateDialog } from "../queue/dialogs";
import s from "./consultation.module.css";

// Doctor Consultation workspace: Figma frame 01 (2:21) and its state frames 09–20, 24–26.
type Open = { kind: "noShow" | "notHere"; e: QueueEntry } | { kind: "pause" | "availability" | "late" | "all" } | null;

export function ConsultationPage() {
  const me = useMe();
  const { queue: q, error, refresh, busy, act, setStatus, failure, clearFailure } = useQueue();
  // "Queue clears around" is the server's own estimate (clears_at in /api/departments), not computed here.
  const deps = useLive(() => api<Departments>("/api/departments"));
  const clears = deps.data?.departments.flatMap((d) => d.doctors).find((d) => d.id === me.doctor_id)?.clears_at;
  const live = useStreamLive();
  const [open, setOpen] = useState<Open>(null);
  const [tab, setTab] = useState<"waiting" | "late">("waiting");
  const [feedback, setFeedback] = useState("");
  useEffect(() => { if (!feedback) return; const t = setTimeout(() => setFeedback(""), 12000); return () => clearTimeout(t); }, [feedback]);

  if (!q) {
    return error
      ? <ErrorState title="Couldn’t load your queue" action={<Button kind="secondary" onClick={refresh}>Refresh &amp; retry</Button>}>{error}</ErrorState>
      : <LoadingState title="Loading your queue…" />;
  }

  const close = () => setOpen(null);
  /** Run an action, then describe what the server says happened (its reply is already on screen). */
  const run = async (send: () => Promise<QueueState | null>, say: (r: QueueState) => string) => {
    const r = await send();
    close();
    if (r) { setFeedback(say(r)); deps.refresh(); }
  };
  const tokenOf = (r: QueueState, id: number) => tokenText(r.entries.find((x) => x.id === id)?.token ?? 0);
  const status = (st: DoctorStatus, minutes?: number) => run(() => setStatus(st, minutes), (r) =>
    st === "break" ? `Queue paused until ${clock(r.doctor.break_until)}. Waiting estimates updated.`
      : st === "delayed" ? `Running late until ${clock(r.doctor.break_until)} · Waiting estimates adjusted · Patients whose time moves are alerted.`
      : st === "unavailable" ? "Marked unavailable for today." : "You’re available. Estimates recalculated.");

  const entries = q.entries.filter((e) => e.status !== "cancelled");
  const waiting = entries.filter(isWaiting);
  const late = entries.filter(isLate);
  const seen = entries.filter((e) => e.status === "completed").length;
  const checkedIn = waiting.filter((e) => e.status === "checked_in").length;
  const ds = doctorStatus(q);
  const rows = tab === "waiting" ? waiting : late;

  return (
    <div className={s.page}>
      <PageHeader title="Your OPD, at a glance."
        sub={<>{q.doctor.department}&nbsp;&nbsp;/&nbsp;&nbsp;{q.doctor.name}&nbsp;&nbsp;/&nbsp;&nbsp;OPD {clock(q.doctor.opd_start)} – {clock(q.doctor.opd_end)}</>}>
        <Button kind="secondary" className={s.availability} onClick={() => setOpen({ kind: "availability" })} aria-label={`Availability: ${ds.label}. Change`}>
          <span className={`${s.dot} ${s[ds.tone]}`} aria-hidden="true">{ds.tone === "urgent" ? "!" : "●"}</span>{ds.label}<span className={s.chev} aria-hidden="true">⌄</span>
        </Button>
      </PageHeader>

      <section className={s.pulse} aria-label="Session pulse">
        <Metric label="Seen today" value={seen} note={`of ${entries.length} registered`} />
        <Metric label="Waiting" value={waiting.length} note={`${checkedIn} checked in`} />
        <Metric label="Skipped / late" value={late.length} note={<TextButton className={s.metricLink} onClick={() => setOpen({ kind: "late" })}>Review patients →</TextButton>} />
        <Metric label="Queue clears around" value={clears ? clock(clears) : "–"} note="Estimates update live" small />
      </section>

      <div className={s.cards}>
        <PatientCard q={q} busy={busy} completedToday={seen}
          onCall={() => run(() => act("call_next"), (r) => r.called ? `Token ${tokenText(r.called)} called · The display and the patient are notified.` : r.message ?? "")}
          onStart={(e) => run(() => act("start", { appointment_id: e.id }), (r) => `Consultation started · Token ${tokenOf(r, e.id)}.`)}
          onComplete={(e) => run(() => act("complete", { appointment_id: e.id }), (r) => `Token ${tokenOf(r, e.id)} complete.`)}
          onNotHere={(e) => setOpen({ kind: "notHere", e })}
          onNoShow={(e) => setOpen({ kind: "noShow", e })}
          onResume={() => status("available")} />

        <section className={s.upnext} aria-labelledby="upnext-title">
          <div className={s.upHead}>
            <div><h2 id="upnext-title" className={s.upTitle}>Up next</h2><p className={s.upSub}>Ordered by clinical priority, then check-in</p></div>
            <Status>{waiting.length} waiting</Status>
          </div>
          <div className={s.tabs} role="tablist" aria-label="Queue">
            <button type="button" role="tab" aria-selected={tab === "waiting"} onClick={() => setTab("waiting")}>Waiting&nbsp;&nbsp;{waiting.length}</button>
            <button type="button" role="tab" aria-selected={tab === "late"} onClick={() => setTab("late")}>Skipped / late&nbsp;&nbsp;{late.length}</button>
          </div>
          <div className={s.upBody} role="tabpanel">
            {rows.length
              ? <QueueTable q={q} rows={rows.slice(0, 5)} highlightFirst={tab === "waiting"} label={tab === "waiting" ? "Waiting patients" : "Skipped and late patients"} />
              : tab === "waiting"
                ? <EmptyState title="All caught up." foot="Queue remains open">No patients are waiting. New check-ins will appear here automatically.</EmptyState>
                : <EmptyState title="Nobody skipped or late.">Patients who miss their turn appear here, and stay on record.</EmptyState>}
          </div>
          <div className={s.upFoot}>
            {rows.length > 0
              ? <TextButton className={s.smallLink} onClick={() => setOpen({ kind: tab === "waiting" ? "all" : "late" })}>View all {rows.length} {rows.length === 1 ? "patient" : "patients"} →</TextButton>
              : <span />}
            <span className={s.avg}>{q.avg_minutes} min average consultation</span>
          </div>
        </section>
      </div>

      <section className={s.controls} aria-label="Session controls">
        {q.doctor.status === "break"
          ? <Button kind="secondary" disabled={busy} onClick={() => status("available")}>Resume queue</Button>
          : <Button kind="secondary" disabled={busy || !q.doctor.holds_opd} onClick={() => setOpen({ kind: "pause" })}>Ⅱ&nbsp;&nbsp;Pause queue</Button>}
        <p className={s.session}>OPD session {clock(q.doctor.opd_start)} – {clock(q.doctor.opd_end)}</p>
      </section>

      <p className={feedback ? s.feedback : s.liveLine} role="status">
        {feedback ? feedback : `Live updates ${live ? "on" : "reconnecting"} · Last updated ${clock(q.updated_at)}`}
      </p>

      <NoShowDialog e={open?.kind === "noShow" ? open.e : null} busy={busy} onClose={close}
        onConfirm={(reason) => open?.kind === "noShow" && run(() => act("skip", { appointment_id: open.e.id, reason }),
          () => `Token ${tokenText(open.e.token)} marked as no-show · The visit is saved in Skipped / late.`)} />
      <NotHereDialog e={open?.kind === "notHere" ? open.e : null} busy={busy} onClose={close}
        onConfirm={(note) => open?.kind === "notHere" && run(() => act("not_present", { appointment_id: open.e.id, reason: note }),
          () => `Token ${tokenText(open.e.token)} marked not here · They keep their place.`)} />
      <PauseDialog open={open?.kind === "pause"} q={q} busy={busy} onClose={close} onConfirm={(m) => status("break", m)} />
      <AvailabilityDialog open={open?.kind === "availability"} q={q} busy={busy} onClose={close} onConfirm={status} />
      <SkippedLateDialog open={open?.kind === "late"} q={q} busy={busy} onClose={close} onNoShow={(e) => setOpen({ kind: "noShow", e })} />
      <FullQueueDialog open={open?.kind === "all"} q={q} busy={busy} onClose={close}
        onNotHere={(e) => setOpen({ kind: "notHere", e })} onNoShow={(e) => setOpen({ kind: "noShow", e })} />
      <FailureDialog failure={failure} onClose={clearFailure} onRefresh={refresh} />
    </div>
  );
}

function Metric({ label, value, note, small }: { label: string; value: string | number; note: ReactNode; small?: boolean }) {
  return (
    <div className={s.metric}>
      <p className={s.metricLabel}>{label}</p>
      <div className={s.metricRow}>
        <p className={small ? s.metricValueSm : s.metricValue}>{value}</p>
        <div className={s.metricNote}>{note}</div>
      </div>
    </div>
  );
}
