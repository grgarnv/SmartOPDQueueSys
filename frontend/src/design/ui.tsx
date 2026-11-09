import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useId } from "react";
import s from "./ui.module.css";
import plusIcon from "./icons/plus.svg";

const cx = (...c: (string | false | undefined | null)[]) => c.filter(Boolean).join(" ");

export type ButtonKind = "primary" | "secondary" | "danger";

/** Class list for a Button, for links that must look like one (<a className={buttonClass("secondary")}>). */
export const buttonClass = (kind: ButtonKind = "primary", block = false) => cx(s.btn, s[kind], block && s.block);

export function Button({ kind = "primary", block, className, type = "button", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { kind?: ButtonKind; block?: boolean }) {
  return <button type={type} className={cx(buttonClass(kind, block), className)} {...rest} />;
}

export function TextButton({ danger, className, type = "button", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { danger?: boolean }) {
  return <button type={type} className={cx(s.link, danger && s.dangerText, className)} {...rest} />;
}

export type Tone = "success" | "info" | "caution" | "urgent" | "neutral";

/** Status pill. Text always states the meaning; colour only reinforces it ("never colour alone"). */
export function Status({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cx(s.status, s[tone])}>{children}</span>;
}

type FieldProps = { label: ReactNode; hint?: ReactNode };

export function TextField({ label, hint, className, ...input }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className={cx(s.field, className)}>
      <label className={s.fieldLabel} htmlFor={id}>{label}</label>
      <input id={id} className={s.control} aria-describedby={hint ? id + "h" : undefined} {...input} />
      {hint && <span id={id + "h"} className={s.fieldHint}>{hint}</span>}
    </div>
  );
}

export function SelectField({ label, hint, className, children, ...select }: FieldProps & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className={cx(s.field, className)}>
      <label className={s.fieldLabel} htmlFor={id}>{label}</label>
      <select id={id} className={s.control} aria-describedby={hint ? id + "h" : undefined} {...select}>{children}</select>
      {hint && <span id={id + "h"} className={s.fieldHint}>{hint}</span>}
    </div>
  );
}

export function Panel({ title, sub, aside, children, className, ...rest }:
  { title?: ReactNode; sub?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string } & Omit<HTMLAttributes<HTMLElement>, "title">) {
  const id = useId();
  return (
    <section className={cx(s.panel, className)} aria-labelledby={title ? id : undefined} {...rest}>
      {title && (
        <div className={s.panelHead}>
          <div><h2 id={id} className={s.panelTitle}>{title}</h2>{sub && <p className={s.panelSub}>{sub}</p>}</div>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

/** Empty / loading / inline-failure states (frame 07 §06). */
export function EmptyState({ title, children, foot }: { title: ReactNode; children?: ReactNode; foot?: ReactNode }) {
  return (
    <div className={cx(s.state, s.stateEmpty)}>
      <p className={s.stateTitle}>{title}</p>
      {children && <p className={s.stateBody}>{children}</p>}
      {foot && <p className={s.stateFoot}>{foot}</p>}
    </div>
  );
}

export function LoadingState({ title = "Loading…", rows = 3 }: { title?: ReactNode; rows?: number }) {
  return (
    <div className={cx(s.state, s.stateLoading)} role="status" aria-live="polite">
      <p className={s.stateTitle}>{title}</p>
      <div className={s.skeleton} aria-hidden="true">{Array.from({ length: rows * 2 }, (_, i) => <span key={i} />)}</div>
    </div>
  );
}

export function ErrorState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={cx(s.state, s.stateError)} role="alert">
      <p className={s.stateTitle}>{title}</p>
      {children && <p className={s.stateBody}>{children}</p>}
      {action && <div style={{ marginTop: "var(--s4)" }}>{action}</div>}
    </div>
  );
}

export function Callout({ tone = "caution", children }: { tone?: Exclude<Tone, "neutral">; children: ReactNode }) {
  return <div className={cx(s.callout, s[tone])} role="status">{children}</div>;
}

/** One-line result of a form or action, announced to screen readers. */
export function Message({ msg }: { msg: { text: string; ok: boolean } | null }) {
  return <p className={cx(s.msg, msg && (msg.ok ? s.msgOk : s.msgErr))} role="status">{msg?.text}</p>;
}

export function Brand() {
  return (
    <span className={s.brand}>
      <span className={s.mark}><img src={plusIcon} width={20} height={20} alt="" /></span>
      <span className={s.wordmark}>SmartOPD</span>
    </span>
  );
}

export function Overline({ children }: { children: ReactNode }) {
  return <p className={s.overline}>{children}</p>;
}
