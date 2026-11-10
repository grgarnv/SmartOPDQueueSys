import type { FormEvent } from "react";
import { useState } from "react";
import { api } from "../api/client";
import type { Ok, User } from "../api/types";
import { Dialog } from "../design/Dialog";
import { Button, Message, TextField } from "../design/ui";
import { useFormAction } from "../lib/useFormAction";
import { useSession } from "./session";
import s from "./auth.module.css";

export function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { onSubmit, msg, busy, setMsg } = useFormAction(
    (f) => api<Ok>("/api/password", { current: f.current, new: f.new }),
    { ok: "Password changed. Your other sessions were signed out.", after: (_, form) => setTimeout(() => { form.reset(); close(); }, 1200) },
  );
  const close = () => { setMsg(null); onClose(); };
  return (
    <Dialog open={open} onClose={close} title="Change password" onSubmit={onSubmit}
      footer={<><Button kind="secondary" onClick={close}>Cancel</Button><Button type="submit" disabled={busy} className={s.wide}>Save password</Button></>}>
      <div className={s.pair}>
        <TextField label="Current password" name="current" type="password" autoComplete="current-password" required />
        <TextField label="New password" name="new" type="password" minLength={8} autoComplete="new-password" required hint="At least 8 characters" />
      </div>
      <Message msg={msg} />
    </Dialog>
  );
}

export function ForgotPasswordDialog({ open, onClose, username }: { open: boolean; onClose: () => void; username: string }) {
  const { signedIn } = useSession();
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const close = () => { setMsg(null); onClose(); };

  // One form, two steps: "Send code" (needs only the username) and "Set password" (needs the code too).
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    const sending = ((e.nativeEvent as SubmitEvent).submitter as HTMLElement | null)?.dataset.send !== undefined;
    try {
      if (sending) {
        if (!f.username?.trim()) return setMsg({ text: "Enter your username first.", ok: false });
        setMsg({ text: (await api<Ok>("/api/password/forgot", { username: f.username })).message ?? "", ok: true });
      } else {
        signedIn(await api<User>("/api/password/reset", { username: f.username, code: f.code, new: f.new }));
        close();
      }
    } catch (err) {
      setMsg({ text: (err as Error).message, ok: false });
    }
  };

  return (
    <Dialog open={open} onClose={close} title="Forgot password" onSubmit={submit}
      description="We send a 6-digit code to the phone or email on your account. No alerts set up? Ask at the OPD desk to reset it."
      footer={<><Button kind="secondary" onClick={close}>Cancel</Button><Button type="submit" className={s.wide}>Set password</Button></>}>
      <div className={s.inline}>
        <TextField label="Username" name="username" autoComplete="username" defaultValue={username} key={String(open)} required />
        <Button kind="secondary" type="submit" formNoValidate data-send="">Send code</Button>
      </div>
      <div className={s.pair}>
        <TextField label="Code" name="code" inputMode="numeric" autoComplete="one-time-code" required />
        <TextField label="New password" name="new" type="password" minLength={8} autoComplete="new-password" required hint="At least 8 characters" />
      </div>
      <Message msg={msg} />
    </Dialog>
  );
}
