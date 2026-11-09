import type { Role } from "../api/types";

/** "2026-11-09T10:32:05" (server local time) → "10:32" */
export const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "–");

/** Today's date in local time, as YYYY-MM-DD */
export const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

export const ROLE_LABEL: Record<Role, string> = {
  patient: "Patient", doctor: "Doctor", staff: "Front-desk staff", admin: "Administrator", tester: "Developer / tester",
};

// ponytail: Hindi only for now, mirrors LANGS in app/server.py; add a language there and here
export const LANGS: Record<string, string> = { en: "English", hi: "हिन्दी (Hindi)" };

export const CHANNELS = { sms: "SMS", email: "Email", none: "No alerts, app only" } as const;
