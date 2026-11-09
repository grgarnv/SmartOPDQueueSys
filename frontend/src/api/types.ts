// Response shapes from app/server.py. Grown screen by screen as each one moves over.

export type Role = "patient" | "doctor" | "staff" | "admin" | "tester";
export type Channel = "sms" | "email" | "none";

/** public_user() in server.py: /api/me, /api/login, /api/register, /api/password/reset */
export interface User {
  id: number;
  username: string;
  role: Role;
  name: string;
  doctor_id: number | null;
  phone: string | null;
  email: string | null;
  channel: Channel;
  lang: string;
  alert_lead: number | null;
  dependants?: { id: number; name: string }[];
}

/** GET /api/health */
export interface Health {
  ok: boolean;
  version: string;
  demo: boolean;
  time: string;
}

export interface Ok {
  ok: true;
  message?: string;
}

export type ApptStatus = "booked" | "checked_in" | "called" | "in_consultation" | "completed" | "skipped" | "cancelled";
export type DoctorStatus = "available" | "break" | "delayed" | "unavailable";

/** One row of queue_state()["entries"] */
export interface QueueEntry {
  id: number;
  token: number;
  patient_name: string;
  status: ApptStatus;
  emergency: boolean;
  /** priority label: "emergency" or a hospital category, null when none */
  priority: string | null;
  checked_in_at: string | null;
  skip_reason: string | null;
  /** booked, their turn came and they were not here: grace period running */
  turn_missed: boolean;
  can_skip: boolean;
  /** place in the server's queue order (0 = next); null when not waiting */
  ahead: number | null;
  eta: string | null;
}

/** GET /api/queue, and the reply to every /api/queue/action and /api/doctor/status */
export interface QueueState {
  doctor: {
    id: number; name: string; department: string; department_id: number;
    status: DoctorStatus; break_until: string | null; holds_opd: boolean; opd_start: string; opd_end: string;
  };
  day: string;
  avg_minutes: number;
  version: number;
  updated_at: string;
  entries: QueueEntry[];
  /** call_next only */
  called?: number | null;
  message?: string;
}

/** GET /api/departments (only the fields the UI reads) */
export interface Departments {
  day: string;
  departments: { id: number; name: string; doctors: { id: number; name: string; clears_at: string | null; waiting: number; opd_start: string; opd_end: string }[] }[];
}
