import { useState } from "react";
import { ApiError, api, qs } from "../../api/client";
import type { DoctorStatus, QueueState } from "../../api/types";
import { useLive } from "../../lib/useLive";

export type QueueAction = "call_next" | "start" | "complete" | "skip" | "not_present";
export type Failure = { message: string; status: number };

/**
 * A doctor's live queue (GET /api/queue) and the doctor actions on it. Every action sends the `version` of the
 * queue it was taken from (the server refuses a stale one with 409) and the screen then shows the queue_state
 * the server replies with, so the UI never guesses the result. Staff screens will pass a doctorId.
 */
export function useQueue(doctorId?: number) {
  const q = useLive(() => api<QueueState>("/api/queue" + (doctorId ? "?" + qs({ doctor_id: doctorId }) : "")), [doctorId]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  async function send(request: () => Promise<QueueState>) {
    if (busy) return null;  // one change at a time from this screen
    setBusy(true);
    try {
      const reply = await request();
      q.set(reply);
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

  const act = (action: QueueAction, body: { appointment_id?: number; reason?: string } = {}) =>
    send(() => api<QueueState>("/api/queue/action", { action, doctor_id: doctorId, ...body, version: q.data?.version }));

  const setStatus = (status: DoctorStatus, minutes?: number) =>
    send(() => api<QueueState>("/api/doctor/status", { doctor_id: doctorId, status, minutes }));

  return { queue: q.data, error: q.error, refresh: q.refresh, busy, act, setStatus, failure, clearFailure: () => setFailure(null) };
}
