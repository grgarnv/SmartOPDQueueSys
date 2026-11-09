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
