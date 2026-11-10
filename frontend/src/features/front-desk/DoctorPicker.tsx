import { useState } from "react";
import type { Overview } from "../../api/types";
import { SelectField } from "../../design/ui";
import { clock } from "../../lib/format";
import { openDoctors } from "../queue/present";
import s from "./frontDesk.module.css";

/**
 * Department → doctor, offering only doctors holding OPD today and not unavailable (the server's booking rules).
 * Capacity is not filtered: a desk booking for a full doctor goes through with a warning. ("Morning" session in
 * Figma: there is one OPD session a day, so it is not shown.)
 */
export function DoctorPicker({ o, doctorId, onChange }: { o?: Overview; doctorId?: number; onChange: (id?: number) => void }) {
  const open = openDoctors(o);
  const [dept, setDept] = useState(() => open.find((d) => d.id === doctorId)?.department ?? "");
  const departments = [...new Set(open.map((d) => d.department))].sort();
  const doctors = open.filter((d) => d.department === dept);
  if (o && !open.length) return <p className={s.none} role="status">No doctor is holding OPD now, so a walk-in cannot be booked. An administrator manages OPD days and leave.</p>;
  return (
    <div className={s.pair}>
      <SelectField label="Department *" name="department" required value={dept}
        onChange={(e) => { setDept(e.target.value); const only = open.filter((d) => d.department === e.target.value); onChange(only.length === 1 ? only[0].id : undefined); }}>
        <option value="" disabled>Choose a department</option>
        {departments.map((d) => <option key={d}>{d}</option>)}
      </SelectField>
      <SelectField label="Doctor *" name="doctor_id" required value={doctorId ?? ""} disabled={!dept}
        onChange={(e) => onChange(Number(e.target.value) || undefined)}>
        <option value="" disabled>Choose a doctor</option>
        {doctors.map((d) => <option key={d.id} value={d.id}>{d.name} · OPD {clock(d.opd_start)}–{clock(d.opd_end)}</option>)}
      </SelectField>
    </div>
  );
}
