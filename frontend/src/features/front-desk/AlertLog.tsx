import type { Tone } from "../../design/ui";
import { EmptyState, ErrorState, LoadingState, Panel, Status, Table } from "../../design/ui";
import { ALERT_LABEL, SENT_LABEL, tokenText } from "../../lib/format";
import { useAlerts } from "../queue/useDesk";
import s from "./frontDesk.module.css";

const TONE: Record<string, Tone> = { failed: "urgent", pending: "caution", unconfirmed: "neutral" };

/** Patient alert delivery log (legacy "Patient alerts"; no Figma frame): the last 200 alerts, newest first. */
export function AlertLog() {
  const { data, error } = useAlerts();
  const rows = data?.notifications;
  return (
    <Panel id="alerts" className={s.alerts} title="Patient alerts" sub="Failed alerts never hold up the queue. Patients also see their status in the app.">
      {!rows ? (error ? <ErrorState title="Couldn’t load the alert log">{error}</ErrorState> : <LoadingState rows={2} />)
        : rows.length ? (
          <div className={s.scroll}>
            <Table label="Patient alerts" columns={["Created", "Patient", "Doctor", "Token", "Alert", "Channel", "Status", "Tries", "Detail"]}
              rows={rows.map((n) => ({ key: n.id, cells: [
                n.created_at.slice(0, 16).replace("T", " "), n.patient, n.doctor ?? "–", n.token != null ? tokenText(n.token) : "–",
                ALERT_LABEL[n.purpose] ?? n.purpose, n.channel.toUpperCase(),
                <Status tone={TONE[n.status] ?? "success"}>{SENT_LABEL[n.status] ?? n.status}</Status>, n.attempts,
                <span className={s.detail}>{n.detail ?? ""}</span>,
              ] }))} />
          </div>
        ) : <EmptyState title="No alerts sent yet." />}
    </Panel>
  );
}
