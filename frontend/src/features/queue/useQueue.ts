import { useState } from "react";
import { ApiError, api, qs } from "../../api/client";
import type { AppointmentView, DoctorStatus, QueueState } from "../../api/types";
import { useLive } from "../../lib/useLive";

export type QueueAction = "call_next" | "start" | "complete" | "skip" | "not_present"
  | "emergency" | "priority" | "remove_priority" | "reinsert_front" | "transfer" | "transfer_all";
export type Failure = { message: string; status: number };
export type ActionBody = { appointment_id?: number; reason?: string; category?: string; to_doctor_id?: number };

/**
 * A doctor's live queue (GET /api/queue) and the actions on it. Every action sends the `version` of the
 * queue it was taken from (the server refuses a stale one with 409) and the screen then shows the queue_state
 * the server replies with, so the UI never guesses the result. Doctors pass no id (the server uses their own);
 * staff screens must pass one (the server answers 400 without it).
 */
export function useQueue(doctorId?: number) {
  const q = useLive(() => api<QueueState>("/api/queue" + (doctorId ? "?" + qs({ doctor_id: doctorId }) : "")), [doctorId]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  /** One change at a time; `show` puts the reply on screen. */
  async function send<T>(request: () => Promise<T>, show: (r: T) => void) {
    if (busy) return null;
    setBusy(true);
    try {
      const reply = await request();
      show(reply);
      return reply;
    } catch (e) {
      const err = e as ApiError;
      if (err.status !== 401) setFailure({ message: err.message, status: err.status });
      q.refresh();  // show what the server has now (e.g. after a 409 the queue had changed)
      return null;
    } finally {
      setBusy(false);
    }
  }

  const act = (action: QueueAction, body: ActionBody = {}) =>
    send(() => api<QueueState>("/api/queue/action", { action, doctor_id: doctorId, ...body, version: q.data?.version }), q.set);

  const setStatus = (status: DoctorStatus, minutes?: number) =>
    send(() => api<QueueState>("/api/doctor/status", { doctor_id: doctorId, status, minutes }), q.set);

  // Check-in and cancel are not version-checked by the server and reply with the appointment, not the queue,
  // so the queue is read again afterwards.
  const checkIn = (appointment_id: number) =>
    send(() => api<AppointmentView>("/api/checkin", { appointment_id }), () => q.refresh());
  const cancel = (appointment_id: number, reason?: string) =>
    send(() => api<AppointmentView>("/api/cancel", { appointment_id, reason }), () => q.refresh());

  return { queue: q.data, error: q.error, refresh: q.refresh, busy, act, setStatus, checkIn, cancel, failure, clearFailure: () => setFailure(null) };
}

export type QueueHandle = ReturnType<typeof useQueue>;
