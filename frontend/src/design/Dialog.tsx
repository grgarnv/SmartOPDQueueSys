import type { FormEvent, ReactNode } from "react";
import { useEffect, useId, useRef } from "react";
import s from "./Dialog.module.css";

/**
 * Modal dialog from the Figma dialog frames (4:2063, 4:2200, 4:2337): 12 radius, 28 inset, 23 semibold title,
 * 13 muted description, 44 px close button, full-width divider above a Cancel-left / primary-right footer.
 * Native <dialog> gives focus trapping, Escape and the inert background for free.
 * With onSubmit, body and footer are one <form>, so Enter submits and `required` fields are checked.
 */
export function Dialog({ open, onClose, title, description, size = "sm", onSubmit, footer, children }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  size?: "sm" | "lg";
  onSubmit?: (e: FormEvent<HTMLFormElement>) => void;
  footer?: ReactNode;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const content = (
    <>
      {children && <div className={s.body}>{children}</div>}
      {footer && <div className={s.footer}>{footer}</div>}
    </>
  );
  return (
    <dialog ref={ref} className={`${s.dialog} ${s[size]}`} aria-labelledby={titleId} onClose={onClose}
      onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <header className={s.head}>
        <h2 id={titleId} className={s.title}>{title}</h2>
        {description && <p className={s.description}>{description}</p>}
        <button type="button" className={s.close} onClick={onClose} aria-label="Close">×</button>
      </header>
      {onSubmit ? <form onSubmit={(e) => { e.preventDefault(); onSubmit(e); }}>{content}</form> : content}
    </dialog>
  );
}
