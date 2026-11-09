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

/** "2026-11-09T10:45:00" or "10:45" → "10:45 AM" (Figma uses 12-hour times) */
export function clock(t?: string | null) {
  if (!t) return "–";
  const [h, m] = (t.length > 5 ? t.slice(11, 16) : t).split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

/** "2026-11-09" → "Mon, 09 Nov 2026" */
export function longDate(day: string) {
  const d = new Date(day + "T12:00:00");
  return `${d.toLocaleDateString("en-GB", { weekday: "short" })}, ${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}`;
}

/** Whole minutes from one server timestamp to another (both server local time, so no clock skew). */
export const minutesBetween = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / 60000);

/** Three-digit token as on the display: 7 → "007" */
export const tokenText = (n: number) => String(n).padStart(3, "0");
