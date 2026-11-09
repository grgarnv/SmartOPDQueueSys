import type { ReactNode } from "react";
import type { QueueEntry, QueueState } from "../../api/types";
import { Status } from "../../design/ui";
import { tokenText } from "../../lib/format";
import { entryStatus, etaText, rowDetail } from "../queue/present";
import s from "./consultation.module.css";

// Queue rows from "Upcoming queue" (4:1330, 4:3476): token, patient, status, ETA; the first row is highlighted
// (red tint for an emergency). Rows keep the server's order and are keyed by appointment id, so focus and
// open menus survive live refreshes.
export function QueueTable({ q, rows, highlightFirst, actions, label }: {
  q: QueueState; rows: QueueEntry[]; highlightFirst?: boolean; actions?: (e: QueueEntry) => ReactNode; label: string;
}) {
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
