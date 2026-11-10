import { useState } from "react";
import { Dialog } from "../../design/Dialog";
import { Button, ErrorState, EmptyState, LoadingState, SelectField, Status, TextField } from "../../design/ui";
import s from "./Specimen.module.css";

// Internal reference page laid out like Figma frame "07 · SmartOPD design system" (2:41), so the shared
// components can be screenshot-compared with the design. Static text only; no API calls.
const swatches = [
  ["Text / primary", "--ink", "#182D31"], ["Text / secondary", "--muted", "#637478"], ["Action / success", "--teal", "#086B5D"],
  ["In consultation", "--blue", "#38638B"], ["Delay / caution", "--amber", "#8B5B15"], ["Urgency / danger", "--red", "#AF3541"],
];

export function Specimen() {
  const [open, setOpen] = useState(false);
  return (
    <main className={s.frame}>
      <h1 className={s.h1}>SmartOPD / Foundations</h1>
      <p className={s.lede}>A calm operational language. Built for decisions, not decoration.</p>

      <h2 className={s.h2}>01  Semantic colour</h2>
      <div className={s.swatches}>
        {swatches.map(([name, v, hex]) => (
          <div key={v}><div className={s.swatch} style={{ background: `var(${v})` }} /><p className={s.swName}>{name}</p><p className={s.swHex}>{hex}</p></div>
        ))}
      </div>

      <h2 className={s.h2}>02  Typography</h2>
      <div className={s.type}>
        <span className={s.display}>Inter · Clear decisions</span>
        <span className={s.section}>Section title / 18 semibold</span>
        <span className={s.small}>Body / 14 regular · Label / 13 medium · Caption / 12</span>
      </div>

      <h2 className={s.h2}>03  Buttons · 44 px target · explicit action labels</h2>
      <div className={s.row}>
        <Button>Continue</Button><Button kind="secondary">Continue</Button><Button kind="danger">Continue</Button><Button disabled>Continue</Button>
        <Button kind="secondary" onClick={() => setOpen(true)}>Open dialog</Button>
      </div>
      <p className={s.caption}>Primary: one per decision region. Destructive actions always require confirmation.</p>

      <h2 className={s.h2}>04  Status language · never colour alone</h2>
      <div className={s.row}>
        <Status tone="success">Available</Status><Status tone="info">In consultation</Status><Status tone="caution">On break</Status>
        <Status tone="urgent">Delayed</Status><Status tone="success">Checked in</Status><Status tone="urgent">Emergency</Status><Status>Not arrived</Status>
      </div>
      <p className={s.caption}>States use text and semantic meaning; urgency is reserved for clinical and operational risk.</p>

      <h2 className={s.h2}>05  Form components</h2>
      <div className={s.input}><TextField label="Mobile number *" defaultValue="+91  98765 43210" /></div>

      <h2 className={s.h2}>06  System feedback &amp; edge states</h2>
      <div className={s.states}>
        <EmptyState title="All caught up." foot="Queue remains open">No patients are waiting. New check-ins will appear here automatically.</EmptyState>
        <LoadingState title="Refreshing live queue…" />
        <ErrorState title="Couldn’t call the patient" action={<Button kind="secondary" block>Refresh &amp; retry</Button>}>
          No queue change was saved. Refresh before retrying; duplicate calls are prevented.
        </ErrorState>
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} title="Pause the queue?" description="New patient calls will stop. Queue order is preserved."
        onSubmit={() => setOpen(false)}
        footer={<><Button kind="secondary" onClick={() => setOpen(false)} style={{ width: 112 }}>Cancel</Button><Button type="submit" style={{ width: 240 }}>Pause queue</Button></>}>
        <SelectField label="Reason" defaultValue="break"><option value="break">Scheduled break</option></SelectField>
        <TextField label="Expected return" defaultValue="Today, 10:45 AM" />
      </Dialog>
    </main>
  );
}
