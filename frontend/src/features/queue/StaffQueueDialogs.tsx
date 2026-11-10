import type { AppointmentView, DoctorStatus, Overview, QueueEntry, QueueState } from "../../api/types";
import { useMe } from "../../auth/session";
import { Button } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import type { StaffPick } from "./dialogs";
import {
  AvailabilityDialog, CancelVisitDialog, EmergencyDialog, FailureDialog, FullQueueDialog, MoveDialog, NoShowDialog, NotHereDialog,
  PatientActionsDialog, PriorityDialog, ReinsertNextDialog, RemovePriorityDialog, SkippedLateDialog,
} from "./dialogs";
import { colleaguesOf } from "./present";
import type { QueueHandle } from "./useQueue";

export type StaffOpen = { kind: "actions" | StaffPick; id: number } | { kind: "moveAll" | "availability" | "late" | "all" } | null;
type Msg = { text: string; ok: boolean } | null;

/**
 * Every desk action on one doctor's queue (staff, admin), wired to the shared dialogs: the Queue monitor uses it,
 * and the Emergency screen can. Entries are looked up by id in the live queue, so an open dialog follows refreshes.
 * Each action goes through useQueue (with the queue version); the server's reply or refusal is what is shown.
 */
export function StaffQueueDialogs({ qh, open, setOpen, say, overview, categories, result }: {
  qh: QueueHandle; open: StaffOpen; setOpen: (o: StaffOpen) => void; say: (m: Msg) => void;
  overview?: Overview; categories: string[]; result?: string;
}) {
  const me = useMe();
  const q = qh.queue;
  const e = open && "id" in open ? q?.entries.find((x) => x.id === open.id) ?? null : null;
  const is = (k: string) => (open?.kind === k ? e : null);
  const close = () => setOpen(null);
  const tok = (x: QueueEntry) => `Token ${tokenText(x.token)}`;

  /** Run one action and describe what the server says happened; failures open the shared failure dialog. */
  async function run<T>(send: () => Promise<T | null>, text: (r: T) => string, stay?: StaffOpen) {
    const r = await send();
    setOpen(r && stay !== undefined ? stay : null);
    if (r) say({ text: text(r), ok: true });
  }

  const checkIn = (x: QueueEntry, stay?: StaffOpen) => {
    const was = x.status;  // the reply does not say where they went; their status before the check-in does
    run<AppointmentView>(() => qh.checkIn(x.id), (r) => was === "skipped"
      ? `${tok(x)} ${x.patient_name} checked in · rejoined at the end of the queue · ${r.ahead ?? 0} ahead.`
      : `${tok(x)} ${x.patient_name} checked in · keeps their place · ${r.ahead ?? 0} ahead.`, stay);
  };

  const pick = (x: QueueEntry, kind: StaffPick) => kind === "checkIn" ? checkIn(x) : setOpen({ kind, id: x.id });
  const act = (x: QueueEntry | null, send: (x: QueueEntry) => Promise<QueueState | null>, text: (x: QueueEntry, r: QueueState) => string) =>
    x && run<QueueState>(() => send(x), (r) => text(x, r));
  const status = (st: DoctorStatus, minutes?: number) => run<QueueState>(() => qh.setStatus(st, minutes), (r) =>
    st === "break" ? `${r.doctor.name} is on a break until ${clock(r.doctor.break_until)}. Waiting estimates updated.`
      : st === "delayed" ? `${r.doctor.name} is running late until ${clock(r.doctor.break_until)}. Waiting estimates adjusted; patients whose time moves are alerted.`
      : st === "unavailable" ? `${r.doctor.name} is marked unavailable for today. Waiting patients are alerted.` : `${r.doctor.name} is available. Estimates recalculated.`);
  const colleagues = q ? colleaguesOf(overview, q.doctor) : [];
  const nameOf = (id: number) => overview?.doctors.find((d) => d.id === id)?.name ?? "the colleague";

  return (
    <>
      <PatientActionsDialog e={is("actions")} role={me.role} busy={qh.busy} onClose={close} onPick={(k) => e && pick(e, k)} />
      <NotHereDialog e={is("notHere")} busy={qh.busy} onClose={close}
        onConfirm={(note) => act(e, (x) => qh.act("not_present", { appointment_id: x.id, reason: note }), (x) => `${tok(x)} marked not here · They keep their place.`)} />
      <NoShowDialog e={is("noShow")} busy={qh.busy} onClose={close}
        onConfirm={(reason) => act(e, (x) => qh.act("skip", { appointment_id: x.id, reason }), (x) => `${tok(x)} skipped · The visit is kept in Skipped / late.`)} />
      <EmergencyDialog e={is("emergency")} busy={qh.busy} onClose={close}
        onConfirm={(reason) => act(e, (x) => qh.act("emergency", { appointment_id: x.id, reason }), (x) => `${tok(x)} has emergency priority.`)} />
      <PriorityDialog e={is("priority")} categories={categories} busy={qh.busy} onClose={close}
        onConfirm={(category) => act(e, (x) => qh.act("priority", { appointment_id: x.id, category }), (x) => `${tok(x)} has priority: ${category}.`)} />
      <RemovePriorityDialog e={is("removePriority")} busy={qh.busy} onClose={close}
        onConfirm={(reason) => act(e, (x) => qh.act("remove_priority", { appointment_id: x.id, reason }), (x) => `${tok(x)} priority removed.`)} />
      <ReinsertNextDialog e={is("reinsert")} busy={qh.busy} onClose={close}
        onConfirm={(reason) => act(e, (x) => qh.act("reinsert_front", { appointment_id: x.id, reason }),
          (x) => `${tok(x)} reinserted next among routine patients (policy exception, reason logged).`)} />
      <CancelVisitDialog e={is("cancel")} busy={qh.busy} onClose={close}
        onConfirm={(reason) => e && run(() => qh.cancel(e.id, reason), () => `${tok(e)} cancelled · The patient is told.`)} />
      <MoveDialog e={is("move")} from={q?.doctor.name ?? ""} colleagues={colleagues} busy={qh.busy} onClose={close}
        onConfirm={(to) => act(e, (x) => qh.act("transfer", { appointment_id: x.id, to_doctor_id: to }), (x) => `${tok(x)} ${x.patient_name} moved to ${nameOf(to)}.`)} />
      <MoveDialog e={null} all={open?.kind === "moveAll"} from={q?.doctor.name ?? ""} colleagues={colleagues} busy={qh.busy} onClose={close}
        onConfirm={(to) => run<QueueState>(() => qh.act("transfer_all", { to_doctor_id: to }), (r) => r.message ?? "")} />
      <AvailabilityDialog open={open?.kind === "availability"} q={q} doctorName={q?.doctor.name} busy={qh.busy} onClose={close} onConfirm={status} />
      <SkippedLateDialog open={open?.kind === "late"} q={q} busy={qh.busy} onClose={close} result={result}
        onCheckIn={(x) => checkIn(x, { kind: "late" })} onReinsert={(x) => setOpen({ kind: "reinsert", id: x.id })}
        onNoShow={me.role === "staff" ? (x) => setOpen({ kind: "noShow", id: x.id }) : undefined} />
      <FullQueueDialog open={open?.kind === "all"} q={q} rows={q?.entries} busy={qh.busy} onClose={close}
        actions={(x) => <Button kind="secondary" disabled={qh.busy} onClick={() => setOpen({ kind: "actions", id: x.id })} aria-label={`Actions for token ${tokenText(x.token)}`}>Actions</Button>} />
      <FailureDialog failure={qh.failure} onClose={qh.clearFailure} onRefresh={qh.refresh} />
    </>
  );
}
