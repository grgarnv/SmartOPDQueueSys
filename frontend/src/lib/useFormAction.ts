import type { FormEvent } from "react";
import { useState } from "react";

type Msg = { text: string; ok: boolean } | null;

/**
 * Submit a form to the API and show one result line: the legacy bindForm() as a hook.
 * `send` receives the form's fields; its error message (from the server) is shown as-is.
 */
export function useFormAction<T>(
  send: (fields: Record<string, string>, form: HTMLFormElement) => Promise<T>,
  { ok = "Saved.", after }: { ok?: string | ((r: T) => string); after?: (r: T, form: HTMLFormElement) => void } = {},
) {
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fields = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, String(v)]));
    setBusy(true);
    try {
      const r = await send(fields, form);
      setMsg({ text: typeof ok === "function" ? ok(r) : ok, ok: true });
      after?.(r, form);
    } catch (err) {
      setMsg({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  };
  return { onSubmit, msg, busy, setMsg };
}
