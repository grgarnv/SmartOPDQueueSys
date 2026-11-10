import type { Congestion, Overview, OverviewDoctor, Policy, QueueEntry, QueueState, Role } from "../../api/types";
import type { Tone } from "../../design/ui";
import { clock, minutesBetween } from "../../lib/format";

// Display only: every value here is read from the server's queue_state. Queue order, who is next, ETAs,
// grace periods and whether a patient can be skipped are all decided by app/server.py and app/engine.py.

export const isCurrent = (e: QueueEntry) => e.status === "called" || e.status === "in_consultation";
/** Waiting in order, not late (server: status booked/checked_in, turn not missed) */
export const isWaiting = (e: QueueEntry) => (e.status === "booked" || e.status === "checked_in") && !e.turn_missed;
/** "Skipped / late": skipped, or booked with a missed turn and a grace period running */
export const isLate = (e: QueueEntry) => e.status === "skipped" || e.turn_missed;
/** The server's WAITING (engine.py): booked or checked in, late ones included */
export const inQueue = (e: QueueEntry) => e.status === "booked" || e.status === "checked_in";

/** Doctor is on a break, or unavailable: Figma shows waiting ETAs as "On hold" (frame 12). */
export const onHold = (q: QueueState) => q.doctor.status === "break" || q.doctor.status === "unavailable";

export function entryStatus(e: QueueEntry): { tone: Tone; label: string } {
  if (e.status === "skipped") return { tone: "caution", label: "Skipped" };
  if (e.status === "completed") return { tone: "neutral", label: "Completed" };
  if (e.status === "cancelled") return { tone: "neutral", label: "Cancelled" };
  if (e.turn_missed) return { tone: "caution", label: e.can_skip ? "Grace over" : "Late" };
  if (e.emergency) return { tone: "urgent", label: "Emergency" };
  if (e.status === "called") return { tone: "info", label: "Called" };
  if (e.status === "in_consultation") return { tone: "info", label: "In consultation" };
  if (e.priority) return { tone: "caution", label: e.priority };
  if (e.status === "checked_in") return { tone: "success", label: "Checked in" };
  return { tone: "neutral", label: "Not arrived" };
}

/** Second line under a patient's name: what the server knows about this visit (no age/sex: not stored). */
export function entryDetail(e: QueueEntry) {
  if (e.status === "skipped") return `Skipped · ${e.skip_reason || "no-show"}`;
  if (e.turn_missed) return e.can_skip ? "Turn missed · grace period over" : "Turn missed · grace period running";
  const kind = e.emergency ? "Emergency priority" : e.priority ? `Priority · ${e.priority}` : "Routine visit";
  return e.checked_in_at ? `${kind} · Checked in at ${clock(e.checked_in_at)}` : `${kind} · Not checked in yet`;
}

/** Short second line for queue rows (Figma rows keep it to one line). */
export function rowDetail(e: QueueEntry) {
  if (e.status === "skipped") return e.skip_reason || "no-show";
  if (e.turn_missed) return e.can_skip ? "Grace period over" : "Grace period running";
  if (e.emergency) return "Emergency priority";
  if (e.priority) return e.priority;
  return e.checked_in_at ? `Checked in ${clock(e.checked_in_at)}` : "Not checked in";
}

export function etaText(e: QueueEntry, q: QueueState) {
  if (onHold(q) && isWaiting(e)) return "On hold";
  if (!e.eta) return e.ahead == null ? "–" : "Pending";
  const m = minutesBetween(q.updated_at, e.eta);
  return m <= 0 ? "Next" : `~${m} min`;
}

type DoctorRow = QueueState["doctor"];

/** A doctor's status as a pill, from a queue_state doctor or an overview row (same fields). */
export function statusOf(d: DoctorRow, updatedAt: string, inConsultation: boolean): { tone: Tone; label: string; short: string } {
  if (!d.holds_opd) return { tone: "neutral", label: "No OPD today", short: "No OPD today" };
  if (d.status === "break") return { tone: "caution", label: `On a break · back ${clock(d.break_until)}`, short: "On a break" };
  if (d.status === "delayed") {
    const m = Math.max(0, minutesBetween(updatedAt, d.break_until!));
    return { tone: "urgent", label: `Delayed · ${m} min`, short: "Running late" };
  }
  if (d.status === "unavailable") return { tone: "urgent", label: "Unavailable today", short: "Unavailable" };
  if (inConsultation) return { tone: "info", label: "In consultation", short: "Available" };
  return { tone: "success", label: "Available", short: "Available" };
}

export const doctorStatus = (q: QueueState) => statusOf(q.doctor, q.updated_at, q.entries.some((e) => e.status === "in_consultation"));

/** The server's load level (overview): text plus tone, never colour alone. */
export const congestionTone: Record<Congestion, Tone> = { normal: "success", busy: "caution", "over capacity": "urgent" };

/** Doctors a walk-in can be booked with today: holding OPD and not unavailable (create_booking's rules). */
export const openDoctors = (o?: Overview) => (o?.doctors ?? []).filter((d) => d.holds_opd && d.status !== "unavailable");

/** Colleagues a waiting patient can move to: same department, holding OPD, not unavailable (server transfer_target). */
export const colleaguesOf = (o: Overview | undefined, d: { id: number; department_id: number }): OverviewDoctor[] =>
  openDoctors(o).filter((x) => x.department_id === d.department_id && x.id !== d.id);

/** Hospital priority categories from policy (the server accepts exactly these). */
export const categoriesOf = (p?: Policy) => (p?.priority_categories ?? "").split(",").map((c) => c.trim()).filter(Boolean);

/**
 * Which desk actions to offer on a queue entry, with the legacy rules (app/index.html loadQueue). The server
 * still decides; this only avoids offering what it would refuse. Admin cannot call, skip or mark not here.
 */
export function staffActions(e: QueueEntry, role: Role) {
  const caller = role === "staff";  // QUEUE_ACTIONS: call_next/skip/not_present are doctor + staff only
  const waiting = inQueue(e);
  return {
    checkIn: e.status === "booked" || e.status === "skipped",
    notHere: caller && (e.status === "called" || e.status === "checked_in"),
    skip: caller && e.can_skip,
    emergency: waiting && !e.emergency,
    priority: waiting && !e.priority,
    removePriority: !!e.priority,
    move: waiting,
    cancel: waiting,
    reinsert: e.status === "skipped",
  };
}
