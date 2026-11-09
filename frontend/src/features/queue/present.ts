import type { QueueEntry, QueueState } from "../../api/types";
import type { Tone } from "../../design/ui";
import { clock, minutesBetween } from "../../lib/format";

// Display only: every value here is read from the server's queue_state. Queue order, who is next, ETAs,
// grace periods and whether a patient can be skipped are all decided by app/server.py and app/engine.py.

export const isCurrent = (e: QueueEntry) => e.status === "called" || e.status === "in_consultation";
/** Waiting in order, not late (server: status booked/checked_in, turn not missed) */
export const isWaiting = (e: QueueEntry) => (e.status === "booked" || e.status === "checked_in") && !e.turn_missed;
/** "Skipped / late": skipped, or booked with a missed turn and a grace period running */
export const isLate = (e: QueueEntry) => e.status === "skipped" || e.turn_missed;

/** Doctor is on a break, or unavailable: Figma shows waiting ETAs as "On hold" (frame 12). */
export const onHold = (q: QueueState) => q.doctor.status === "break" || q.doctor.status === "unavailable";

export function entryStatus(e: QueueEntry): { tone: Tone; label: string } {
  if (e.status === "skipped") return { tone: "caution", label: "Skipped" };
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
  if (!e.eta) return "Pending";
  const m = minutesBetween(q.updated_at, e.eta);
  return m <= 0 ? "Next" : `~${m} min`;
}

export function doctorStatus(q: QueueState): { tone: Tone; label: string; short: string } {
  const d = q.doctor;
  if (!d.holds_opd) return { tone: "neutral", label: "No OPD today", short: "No OPD today" };
  if (d.status === "break") return { tone: "caution", label: `On a break · back ${clock(d.break_until)}`, short: "On a break" };
  if (d.status === "delayed") {
    const m = Math.max(0, minutesBetween(q.updated_at, d.break_until!));
    return { tone: "urgent", label: `Delayed · ${m} min`, short: "Running late" };
  }
  if (d.status === "unavailable") return { tone: "urgent", label: "Unavailable today", short: "Unavailable" };
  if (q.entries.some((e) => e.status === "in_consultation")) return { tone: "info", label: "In consultation", short: "Available" };
  return { tone: "success", label: "Available", short: "Available" };
}
