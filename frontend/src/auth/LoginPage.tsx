import { useState } from "react";
import { Navigate } from "react-router";
import { api } from "../api/client";
import type { User } from "../api/types";
import { Brand, Button, Callout, Message, Panel, SelectField, TextButton, TextField } from "../design/ui";
import { CHANNELS, LANGS } from "../lib/format";
import { useFormAction } from "../lib/useFormAction";
import { ForgotPasswordDialog } from "./PasswordDialogs";
import { HOME, useSession } from "./session";
import s from "./auth.module.css";

// No Figma frame for sign-in: composed from the design system (page header, panels, Input, Button).
export function LoginPage() {
  const { me, demo, notice, signedIn } = useSession();
  const [forgot, setForgot] = useState(false);
  const [username, setUsername] = useState("");

  const login = useFormAction((f) => api<User>("/api/login", { username: f.username, password: f.password }), { ok: "", after: signedIn });
  const register = useFormAction(
    (f) => api<User>("/api/register", { name: f.name, phone: f.phone, email: f.email, channel: f.channel, lang: f.lang, username: f.username, password: f.password }),
    { ok: "", after: signedIn },
  );

  if (me) return <Navigate to={HOME[me.role]} replace />;

  return (
    <div className={s.page}>
      <header className={s.top}><Brand /></header>
      <main className={s.main}>
        <div className={s.intro}>
          <h1 className={s.pageTitle}>Sign in to SmartOPD</h1>
          <p className={s.pageSub}>Outpatient appointments and live queue</p>
        </div>
        {notice && <Callout>{notice}</Callout>}
        <div className={s.grid}>
          <Panel title="Sign in">
            <form className={s.form} onSubmit={login.onSubmit}>
              <TextField label="Username" name="username" autoComplete="username" required onChange={(e) => setUsername(e.target.value)} />
              <TextField label="Password" name="password" type="password" autoComplete="current-password" required />
              <Button type="submit" block disabled={login.busy}>Sign in</Button>
              <Message msg={login.msg} />
            </form>
            <TextButton onClick={() => setForgot(true)}>Forgot password?</TextButton>
            {demo && <p className={s.note}>Demo accounts: patient / patient123, staff / staff123, admin / admin123, tester / tester123, dr.rao / doctor123</p>}
          </Panel>
          <Panel title="New patient? Register" sub="We only ask for what is needed to book and to reach you about your turn.">
            <form className={`${s.form} ${s.cols}`} onSubmit={register.onSubmit}>
              <TextField label="Full name" name="name" autoComplete="name" required className={s.span} />
              <TextField label="Phone" name="phone" type="tel" autoComplete="tel" placeholder="+91 98765 43210" />
              <TextField label="Email" name="email" type="email" autoComplete="email" />
              <SelectField label="Send alerts by" name="channel" defaultValue="sms">
                {Object.entries(CHANNELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </SelectField>
              <SelectField label="Alert language" name="lang" defaultValue="en">
                {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </SelectField>
              <TextField label="Username" name="username" autoComplete="username" required />
              <TextField label="Password" name="password" type="password" minLength={8} autoComplete="new-password" required hint="At least 8 characters" />
              <Button type="submit" block disabled={register.busy} className={s.span}>Register</Button>
              <Message msg={register.msg} />
            </form>
          </Panel>
        </div>
      </main>
      <ForgotPasswordDialog open={forgot} onClose={() => setForgot(false)} username={username} />
    </div>
  );
}
