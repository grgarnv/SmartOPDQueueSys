import type { ReactNode } from "react";
import type { QueueEntry, QueueState } from "../../api/types";
import { Status } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import { entryStatus, etaText, rowDetail } from "./present";
import s from "./queue.module.css";

// Queue rows from "Upcoming queue" (4:1330, 4:3476): token, patient, status, ETA; the first row is highlighted
// (red tint for an emergency). Rows keep the server's order and are keyed by appointment id, so focus and
// open menus survive live refreshes.
// `desk` is the monitor layout (frame 04 live queue 2:33): POS (server ahead + 1) · token and name on one line ·
// ARRIVAL (checked_in_at) · STATUS · EST. WAIT, 54 px rows.
// `dense` is the Full queue dialog (4:3874): no visible header, one line per patient, 48 px pitch; token 80 ·
// name · STATUS at 408 · ETA at 640 (dialog px). An actions column sits between name and status, so the name
// column narrows and status / ETA keep their Figma positions.
export function QueueTable({ q, rows, highlightFirst, actions, label, desk, dense }: {
  q: QueueState; rows: QueueEntry[]; highlightFirst?: boolean; actions?: (e: QueueEntry) => ReactNode; label: string; desk?: boolean; dense?: boolean;
}) {
  if (dense) {
    return (
      <table className={`${s.table} ${s.dense} ${actions ? s.withActions : ""}`} aria-label={label}>
        <thead className={s.srOnly}>
          <tr><th>Token</th><th>Patient</th>{actions && <th>Actions</th>}<th>Status</th><th>ETA</th></tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const st = entryStatus(e);
            return (
              <tr key={e.id}>
                <td className={`${s.tok} ${e.emergency ? s.redText : ""}`}>{tokenText(e.token)}</td>
                <td className={s.denseName}>{e.patient_name}</td>
                {actions && <td className={s.rowActions}>{actions(e)}</td>}
                <td><Status tone={st.tone}>{st.label}</Status></td>
                <td className={s.eta}>{etaText(e, q)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }
  if (desk) {
    return (
      <table className={`${s.table} ${s.desk} ${actions ? s.withActions : ""}`} aria-label={label}>
        <thead>
          <tr><th>POS.</th><th>TOKEN / PATIENT</th><th>ARRIVAL</th><th>STATUS</th><th>EST. WAIT</th>{actions && <th className={s.srOnly}>Actions</th>}</tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const st = entryStatus(e);
            return (
              <tr key={e.id}>
                <td className={s.pos}>{e.ahead == null ? "–" : String(e.ahead + 1).padStart(2, "0")}</td>
                <td className={s.who}>
                  <span className={`${s.deskTok} ${e.emergency ? s.redText : ""}`}>{tokenText(e.token)}</span>
                  <span className={s.deskName}>{e.patient_name}</span>
                  {(e.status === "skipped" || e.turn_missed) && <span className={s.deskSub}>{rowDetail(e)}</span>}
                </td>
                <td className={s.arrival}>{e.checked_in_at ? clock(e.checked_in_at) : "—"}</td>
                <td className={s.deskStatus}><Status tone={st.tone}>{st.label}</Status></td>
                <td className={s.deskEta}>{etaText(e, q)}</td>
                {actions && <td className={s.rowActions}>{actions(e)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }
  return (
    <table className={`${s.table} ${actions ? s.withActions : ""}`} aria-label={label}>
      <thead>
        <tr><th colSpan={2}>TOKEN / PATIENT</th><th>STATUS</th><th>ETA</th>{actions && <th className={s.srOnly}>Actions</th>}</tr>
      </thead>
      <tbody>
        {rows.map((e, i) => {
          const st = entryStatus(e);
          const first = highlightFirst && i === 0;
          return (
            <tr key={e.id} className={first ? (e.emergency ? s.firstUrgent : s.first) : undefined}>
              <td className={`${s.tok} ${e.emergency ? s.redText : first ? s.tealText : ""}`}>{tokenText(e.token)}</td>
              <td>
                <span className={s.rowName}>{e.patient_name}</span>
                <span className={`${s.rowSub} ${e.emergency ? s.redText : ""}`}>{rowDetail(e)}</span>
              </td>
              <td><Status tone={st.tone}>{st.label}</Status></td>
              <td className={s.eta}>{etaText(e, q)}</td>
              {actions && <td className={s.rowActions}>{actions(e)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
