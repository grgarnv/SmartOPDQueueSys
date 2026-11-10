import type { OverviewDoctor } from "../../api/types";
import { Status } from "../../design/ui";
import { clock, tokenText } from "../../lib/format";
import { statusOf } from "./present";
import s from "./queue.module.css";

/**
 * One doctor's session at a glance, from an overview row: status pill, waiting count and the server's estimates.
 * Used by the Front desk session card (2:25) and the Queue monitor cards (2:33). Room is not stored: left out.
 * Figma's wait ranges ("96–112 min") would need a client-side simulation, so the server's `clears_at` is shown;
 * the current token (front desk card; the monitor cards show it in their footer); a next-call time is shown only when the caller has it from that doctor's queue (`next`).
 */
export function SessionFacts({ d, updatedAt, next, card }: { d: OverviewDoctor; updatedAt: string; next?: string | null; card?: boolean }) {
  const st = statusOf(d, updatedAt, d.current_status === "in_consultation");
  return (
    <>
      <span className={card ? s.factDoctor : s.factSub}>{d.name}{card ? "" : ` · OPD ${clock(d.opd_start)}–${clock(d.opd_end)}`}</span>
      {card && <span className={s.factHours}>OPD {clock(d.opd_start)}–{clock(d.opd_end)}</span>}
      <span className={s.factStatus}><Status tone={st.tone}>{st.label}</Status></span>
      {!card && d.current_token != null && (
        <span className={s.factNow}>Now {tokenText(d.current_token)} ({d.current_status === "called" ? "called" : "in consultation"})</span>
      )}
      {!card && <span className={s.factRule} />}
      <span className={card ? s.factsCard : s.facts}>
        <span className={s.fact}><span className={s.factBig}>{d.waiting}</span><span className={s.factLabel}>waiting</span></span>
        <span className={s.fact}>
          <span className={s.factMid}>{next ?? (d.clears_at ? clock(d.clears_at) : "–")}</span>
          <span className={s.factLabel}>{next ? "next call" : d.clears_at ? (card ? "queue clears" : "queue clears around (estimate)") : "no estimate yet"}</span>
        </span>
      </span>
    </>
  );
}
