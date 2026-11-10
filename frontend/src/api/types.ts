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

/** appointment_view() in server.py: the reply of /api/checkin and /api/cancel, spread into the walk-in reply */
export interface AppointmentView extends QueueEntry {
  doctor: QueueState["doctor"];
  day: string;
  updated_at: string;
  arrival_alert: boolean;
  patient_id: number;
  /** the last 3 alerts for this visit */
  notifications: { purpose: string; channel: Channel; status: string; created_at: string; updated_at: string }[];
  checkin_opens_at: string | null;
  checkin_code_required: boolean;
}

/** POST /api/staff/walkin. `existing`: they already had a visit with this doctor today (then no `warning`). */
export interface WalkIn extends AppointmentView {
  existing: boolean;
  /** capacity problem: staff bookings go through with this note */
  warning?: string | null;
  username: string;
}

/** GET /api/lookup?q= : today's visits (any status) and patient accounts */
export interface LookupVisit { id: number; token: number; status: ApptStatus; day: string; patient_name: string; phone: string | null; doctor: string; doctor_id: number }
export interface LookupPatient { id: number; username: string; name: string; phone: string | null; guardian: string | null }
export interface Lookup { results: LookupVisit[]; patients: LookupPatient[] }

export type Congestion = "normal" | "busy" | "over capacity";

/** One doctor in GET /api/admin/overview. `waiting` = booked + checked_in (late ones included), not the current patient. */
export type OverviewDoctor = QueueState["doctor"] & {
  waiting: number; current_token: number | null; current_status: ApptStatus | null; avg_minutes: number;
  clears_at: string | null; congestion: Congestion; completed: number; skipped: number; emergencies: number;
};
export interface OverviewException { at: string; action: string; detail: string | null; doctor: string | null; token: number | null }
/** GET /api/admin/overview (staff, admin): every active doctor today */
export interface Overview { doctors: OverviewDoctor[]; exceptions: OverviewException[]; failed_alerts: number; updated_at: string; opd_end: string }

/** GET /api/admin/policy (staff, admin). Every value is a string. */
export interface Policy {
  [key: string]: string;
  priority_categories: string; require_checkin_code: string; checkin_code: string; display_key: string;
}

/** GET /api/admin/notifications: the last 200 alerts, newest first (recipient and text are not exposed) */
export interface AlertRow {
  id: number; purpose: string; channel: Channel; status: string; attempts: number; created_at: string; updated_at: string;
  detail: string | null; patient: string; token: number | null; doctor: string | null;
}
