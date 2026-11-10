import type { ReactNode } from "react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { Overview, OverviewDoctor, Policy } from "../../api/types";
import { useMe } from "../../auth/session";
import { Dialog } from "../../design/Dialog";
import type { Tone } from "../../design/ui";
import { Button, EmptyState, ErrorState, LoadingState, PageHeader, Panel, SelectField, Status, Table, TextButton } from "../../design/ui";
import { actionText, clock, hhmm, tokenText } from "../../lib/format";
import { useFlash } from "../../lib/useFormAction";
import { useStreamLive } from "../../lib/useLive";
import { QueueTable } from "../queue/QueueTable";
import { SessionFacts } from "../queue/SessionFacts";
import type { StaffOpen } from "../queue/StaffQueueDialogs";
import { StaffQueueDialogs } from "../queue/StaffQueueDialogs";
import { DisplayLink } from "../queue/DisplayLink";
import { categoriesOf, doctorStatus, inQueue, isCurrent, isLate, openDoctors } from "../queue/present";
import { useOverview, usePolicy } from "../queue/useDesk";
import { useQueue } from "../queue/useQueue";
import s from "./queueMonitor.module.css";

// Queue monitor: Figma frame 04 (2:33), dialogs Full queue 4:3874 and Skipped & late 4:2152.
// Left out (no backend data): Room, the "Morning session" filter (one OPD session a day), per-doctor
// next-call times on cards other than the selected one (the overview has none), "N patients notified".
export function QueueMonitorPage() {
  const ov = useOverview();
  const pol = usePolicy();
  const [params, setParams] = useSearchParams();
  const o = ov.data;
  const asked = Number(params.get("doctor")) || undefined;
  const selected = o && (o.doctors.find((d) => d.id === asked) ?? openDoctors(o)[0] ?? o.doctors[0]);

  const header = (
    <PageHeader title="Every queue. One clear picture." sub={`Live OPD flow across departments · Last updated ${o ? clock(o.updated_at) : "–"}`}>
      <DisplayLink p={pol.data} error={pol.error} className={s.display} />
    </PageHeader>
  );
  if (!o) {
    return <div className={s.page}>{header}{ov.error
      ? <ErrorState title="Couldn’t load today’s queues" action={<Button kind="secondary" onClick={ov.refresh}>Try again</Button>}>{ov.error}</ErrorState>
      : <LoadingState title="Loading today’s queues…" />}</div>;
  }
  if (!selected) {
    return <div className={s.page}>{header}<EmptyState title="No doctors yet.">No doctors have been added yet. An administrator adds them under Doctors and departments.</EmptyState></div>;
  }
  return <Monitor header={header} o={o} doctor={selected} policy={pol.data}
    select={(id) => setParams({ doctor: String(id) }, { replace: true })} />;
}

function Monitor({ header, o, doctor, policy, select }: { header: ReactNode; o: Overview; doctor: OverviewDoctor; policy?: Policy; select: (id: number) => void }) {
  const me = useMe();
  const live = useStreamLive();
  const qh = useQueue(doctor.id);
  const q = qh.queue;
  const [dept, setDept] = useState("");
  const [open, setOpen] = useState<StaffOpen>(null);
  const [exceptions, setExceptions] = useState(false);
  const [msg, say] = useFlash();

  const departments = [...new Set(o.doctors.map((d) => d.department))].sort();
  const cards = o.doctors.filter((d) => !dept || d.department === dept);
  const holding = openDoctors(o).length;
  const waiting = q ? q.entries.filter(inQueue) : [];
  const late = q ? q.entries.filter(isLate) : [];
  const current = q?.entries.find(isCurrent);
  // next call: the first waiting patient in the server's order, at the server's ETA (selected doctor only).
  // Shown as a clock time: the row wording ("Next", "~8 min") reads wrongly as a card value.
  const head = waiting[0];
  const next = head?.eta ? clock(head.eta) : null;
  const items = attention(o, doctor, late.length, () => setOpen({ kind: "late" }));

  return (
    <div className={s.page}>
      {header}

      <section className={s.filters} aria-label="Monitoring filters">
        <SelectField label="Department" hideLabel className={s.deptFilter} value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All departments</option>
          {departments.map((d) => <option key={d}>{d}</option>)}
        </SelectField>
        <p className={s.count}>{holding} {holding === 1 ? "doctor" : "doctors"} holding OPD · {o.failed_alerts} failed {o.failed_alerts === 1 ? "alert" : "alerts"} today</p>
        <Status tone={live ? "success" : "caution"}>●&nbsp;&nbsp;{live ? "Live updates" : "Reconnecting…"}</Status>
      </section>

      <section className={s.cards} aria-label="Sessions">
        {cards.map((d) => {
          const foot = footnote(d);
          return (
            <button key={d.id} type="button" className={`${s.card} ${d.id === doctor.id ? s.selected : ""}`} aria-pressed={d.id === doctor.id} onClick={() => select(d.id)}>
              <span className={s.cardDept}>{d.department}</span>
              <SessionFacts d={d} updatedAt={o.updated_at} next={d.id === doctor.id ? next : undefined} card />
              <span className={`${s.cardFoot} ${s[foot.tone]}`}>{foot.text}</span>
              <span className={s.cardMore}>
                {d.current_token != null && `Now ${tokenText(d.current_token)} · `}{d.completed} done · {d.skipped} skipped · avg {d.avg_minutes} min
              </span>
            </button>
          );
        })}
      </section>

      <div className={s.row}>
        <Panel className={s.live} title={`${doctor.department} · Live queue`}
          sub={q ? `${q.doctor.name} · ${doctorStatus(q).label} · OPD ${clock(q.doctor.opd_start)}–${clock(q.doctor.opd_end)}${current ? ` · Now ${tokenText(current.token)} (${current.status === "called" ? "called" : "in consultation"})` : ""}` : doctor.name}
          aside={<Status>{waiting.length} waiting</Status>}>
          <div className={s.controls}>
            {me.role === "staff" && (
              <Button disabled={qh.busy || !q} onClick={async () => {
                const r = await qh.act("call_next");
                if (r) say({ text: r.called ? `Called token ${tokenText(r.called)}. The display and the patient are notified.` : r.message ?? "", ok: true });
              }}>Call next patient</Button>
            )}
            <Button kind="secondary" disabled={!q} onClick={() => setOpen({ kind: "availability" })}>Doctor status…</Button>
            <Button kind="secondary" disabled={!q} onClick={() => setOpen({ kind: "moveAll" })}>Move all waiting…</Button>
          </div>
          {!q ? (qh.error
            ? <ErrorState title="Couldn’t load this queue" action={<Button kind="secondary" onClick={qh.refresh}>Try again</Button>}>{qh.error}</ErrorState>
            : <LoadingState rows={4} />)
            : waiting.length ? (
              <QueueTable q={q} rows={waiting.slice(0, 4)} desk label="Live queue"
                actions={(e) => <Button kind="secondary" disabled={qh.busy} onClick={() => setOpen({ kind: "actions", id: e.id })} aria-label={`Actions for token ${tokenText(e.token)}`}>Actions</Button>} />
            ) : <EmptyState title="All caught up.">No patients are waiting for {doctor.name}.</EmptyState>}
          <TextButton className={s.more} onClick={() => setOpen({ kind: "all" })} disabled={!q}>View complete queue ({q?.entries.length ?? 0}) →</TextButton>
        </Panel>

        <Panel className={s.attention} title="Needs attention" aside={<Status tone={items.length ? "caution" : "neutral"}>{items.length}</Status>}>
          <ul className={s.items}>
            {items.map((it, i) => (
              <li key={i}>
                <p className={`${s.itemTitle} ${s[it.tone]}`}>{it.title}</p>
                <p className={s.itemSub}>{it.sub}</p>
                {it.action}
              </li>
            ))}
            <li>
              <p className={s.itemTitle}>Today’s exceptions</p>
              <p className={s.itemSub}>{o.exceptions.length ? `Latest: ${actionText(o.exceptions[0].action)}${o.exceptions[0].doctor ? ` · ${o.exceptions[0].doctor}` : ""} at ${clock(o.exceptions[0].at)}` : "No exceptions yet today."}</p>
              <TextButton className={s.more} onClick={() => setExceptions(true)}>View today’s exceptions ({o.exceptions.length}) →</TextButton>
            </li>
          </ul>
          <div className={s.notes}>
            <p className={s.noteMain}>Times are estimates, not promises.</p>
            <p className={s.noteSub}>Priority cases may change queue order.</p>
          </div>
        </Panel>
      </div>

      <p className={msg ? (msg.ok ? s.feedback : s.feedbackErr) : s.foot} role="status">
        {msg ? msg.text : "Public displays show tokens only. Patient names are visible only in staff workspaces."}
      </p>

      <StaffQueueDialogs qh={qh} open={open} setOpen={setOpen} say={say} overview={o} categories={categoriesOf(policy)} result={msg?.text} />
      <Dialog open={exceptions} onClose={() => setExceptions(false)} size="lg" title="Today’s exceptions" description="Skips, priorities, reinsertions, moves, cancellations and doctor status changes, newest first (last 20)."
        footer={<><span /><Button kind="secondary" onClick={() => setExceptions(false)}>Close</Button></>}>
        {o.exceptions.length ? (
          <Table label="Today’s exceptions" columns={["Time", "Doctor", "Token", "What", "Detail"]}
            rows={o.exceptions.map((x, i) => ({ key: i, cells: [hhmm(x.at), x.doctor ?? "–", x.token != null ? tokenText(x.token) : "–", actionText(x.action), x.detail ?? ""] }))} />
        ) : <EmptyState title="No exceptions yet today." />}
      </Dialog>
    </div>
  );
}

/** Card footnote, in the order the Figma cards use (break, delay), then the server's load level. */
function footnote(d: OverviewDoctor): { tone: Tone; text: string } {
  if (!d.holds_opd) return { tone: "neutral", text: "No OPD today" };
  if (d.status === "break") return { tone: "caution", text: `Resumes ${clock(d.break_until)}` };
  if (d.status === "delayed") return { tone: "urgent", text: `Running late until ${clock(d.break_until)}` };
  if (d.status === "unavailable") return { tone: "urgent", text: "Unavailable today" };
  if (d.congestion === "over capacity") return { tone: "urgent", text: `Over capacity · runs past ${clock(d.opd_end)}` };
  if (d.congestion === "busy") return { tone: "caution", text: "Busy" };
  return { tone: "success", text: "Normal load" };
}

type Item = { tone: Tone; title: string; sub: string; action?: ReactNode };

/** "Needs attention" items, all from server data: doctor status and load, the selected queue's late patients, failed alerts. */
function attention(o: Overview, selected: OverviewDoctor, late: number, review: () => void): Item[] {
  const items: Item[] = [];
  for (const d of o.doctors) {
    if (!d.holds_opd) continue;
    if (d.status === "delayed") items.push({ tone: "urgent", title: `${d.department} · ${d.name} running late until ${clock(d.break_until)}`, sub: "Waiting estimates include the delay." });
    else if (d.status === "break") items.push({ tone: "caution", title: `${d.name} on a break · back ${clock(d.break_until)}`, sub: "Calls wait until then; estimates start from the return." });
    else if (d.status === "unavailable") items.push({ tone: "urgent", title: `${d.name} unavailable today`, sub: "Waiting patients see no time for this queue. Move them to a colleague if needed." });
    else if (d.congestion === "over capacity") items.push({ tone: "urgent", title: `${d.name}’s queue runs past ${clock(d.opd_end)}`, sub: `Queue clears around ${clock(d.clears_at)} (estimate).` });
  }
  if (late) {
    items.push({ tone: "caution", title: `${late} ${late === 1 ? "patient" : "patients"} missed their turn`, sub: `${selected.department} · ${selected.name} · Confirm arrival before reinserting.`,
      action: <TextButton className={s.more} onClick={review}>Review skipped patients →</TextButton> });
  }
  if (o.failed_alerts) {
    items.push({ tone: "urgent", title: `${o.failed_alerts} patient ${o.failed_alerts === 1 ? "alert" : "alerts"} failed today`, sub: "Patients still see their status in the app.",
      action: <Link className={s.more} to="/front-desk#alerts">See the alert log →</Link> });
  }
  return items;
}
