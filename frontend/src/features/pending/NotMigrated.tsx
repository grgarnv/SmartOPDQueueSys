import { useState } from "react";
import { api } from "../../api/client";
import type { Health } from "../../api/types";
import { ChangePasswordDialog } from "../../auth/PasswordDialogs";
import { useMe, useSession } from "../../auth/session";
import { Brand, Button, EmptyState, Panel, buttonClass } from "../../design/ui";
import { ROLE_LABEL, hhmm } from "../../lib/format";
import { isLive, useLive } from "../../lib/useLive";
import s from "./NotMigrated.module.css";

/**
 * Stand-in for a screen that has not moved to React yet. Shows only real data (the signed-in account and the
 * server's clock through the live stream) and sends the user to the legacy UI, which still does everything.
 * Removed screen by screen as each one is migrated; the identity bar is replaced by the app shell.
 */
export function NotMigrated({ screen }: { screen: string }) {
  const me = useMe();
  const { signOut } = useSession();
  const [pw, setPw] = useState(false);
  const health = useLive(() => api<Health>("/api/health"));

  return (
    <div className={s.page}>
      <header className={s.bar}>
        <Brand />
        <div className={s.identity}>
          <div>
            <p className={s.name}>{me.name}</p>
            <p className={s.role}>{ROLE_LABEL[me.role]}</p>
          </div>
          <Button kind="secondary" onClick={() => setPw(true)}>Change password</Button>
          <Button kind="secondary" onClick={() => signOut()}>Sign out</Button>
        </div>
      </header>
      <main className={s.main}>
        <h1 className={s.title}>{screen}</h1>
        <Panel>
          <EmptyState title="This screen is still in the current app."
            foot={<a className={buttonClass("secondary")} href="/">Open the current app</a>}>
            {screen} moves to the new interface in a later migration phase. Everything works as before in the current app,
            using the same account and data.
          </EmptyState>
        </Panel>
        <p className={s.live}>
          {health.data ? `Live updates ${isLive() ? "on" : "reconnecting"} · Server time ${hhmm(health.data.time)} · Version ${health.data.version}` : health.error ?? "Connecting…"}
        </p>
      </main>
      <ChangePasswordDialog open={pw} onClose={() => setPw(false)} />
    </div>
  );
}
