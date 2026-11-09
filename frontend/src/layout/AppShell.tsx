import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { api } from "../api/client";
import type { Departments, Health, Role } from "../api/types";
import { ChangePasswordDialog } from "../auth/PasswordDialogs";
import { useMe, useSession } from "../auth/session";
import { Brand, Overline } from "../design/ui";
import { ROLE_LABEL, clock, longDate, today } from "../lib/format";
import { useLastSync, useStreamLive } from "../lib/useLive";
import { ICONS, Icon } from "./Icon";
import s from "./AppShell.module.css";

// Sidebar and application bar from Figma frame 01 (2:22, 2:23). Navigation shows only what the signed-in
// role may use; the server still checks every request.
const NAV: { to: string; label: string; icon: keyof typeof ICONS; roles: Role[] }[] = [
  { to: "/consultation", label: "Consultation", icon: "grid", roles: ["doctor"] },
  { to: "/front-desk", label: "Front desk", icon: "users", roles: ["staff", "admin"] },
  { to: "/emergency", label: "Emergency priority", icon: "shield", roles: ["staff", "admin"] },
  { to: "/queue-monitor", label: "Queue monitor", icon: "pulse", roles: ["staff", "admin"] },
  { to: "/admin", label: "Administration", icon: "settings", roles: ["admin"] },
];

type MyDoctor = { department: string; opd_start: string; opd_end: string } | null;

export function AppShell() {
  const me = useMe();
  const { signOut } = useSession();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [menu, setMenu] = useState(false);
  const [pw, setPw] = useState(false);
  const [version, setVersion] = useState("");
  const [doctor, setDoctor] = useState<MyDoctor>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const items = NAV.filter((n) => n.roles.includes(me.role));
  const section = items.find((n) => location.pathname.startsWith(n.to))?.label;

  useEffect(() => { api<Health>("/api/health").then((h) => setVersion(h.version)).catch(() => {}); }, []);
  useEffect(() => {  // a doctor's department and OPD hours (the shell's "location" block)
    if (me.role !== "doctor") return;
    api<Departments>("/api/departments").then((r) => {
      const d = r.departments.flatMap((dep) => dep.doctors.map((x) => ({ ...x, department: dep.name }))).find((x) => x.id === me.doctor_id);
      setDoctor(d ? { department: d.department, opd_start: d.opd_start, opd_end: d.opd_end } : null);
    }).catch(() => {});
  }, [me.role, me.doctor_id]);
  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {  // close the account menu on outside click or Escape
    if (!menu) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [menu]);

  const roleLine = doctor ? `${doctor.department} · ${ROLE_LABEL[me.role]}` : ROLE_LABEL[me.role];

  return (
    <div className={s.shell}>
      <aside className={`${s.sidebar} ${drawer ? s.open : ""}`} aria-label="Main">
        <div className={s.brand}><Brand /></div>
        <Overline>WORKSPACE</Overline>
        <nav className={s.nav}>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `${s.navItem} ${isActive ? s.active : ""}`} title={n.label}>
              <Icon name={n.icon} /><span className={s.navLabel}>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        {doctor && (
          <div className={s.place}>
            <Overline>YOUR DEPARTMENT</Overline>
            <p className={s.placeName}>{doctor.department}</p>
            <p className={s.placeSub}>OPD {clock(doctor.opd_start)} – {clock(doctor.opd_end)}</p>
          </div>
        )}
        <div className={s.foot}>
          <Connection />
          <p className={s.version}>SmartOPD{version && ` · v${version}`}</p>
        </div>
      </aside>
      {drawer && <div className={s.scrim} onClick={() => setDrawer(false)} aria-hidden="true" />}

      <header className={s.bar}>
        <button type="button" className={s.menuButton} onClick={() => setDrawer(true)} aria-label="Open navigation">
          <span /><span /><span />
        </button>
        <p className={s.crumbs}>
          <span className={s.crumbStrong}>Outpatient department</span>
          {section && <><span aria-hidden="true">/</span><span>{section}</span></>}
        </p>
        <p className={s.date}>{longDate(today())}</p>
        <span className={s.idDivider} aria-hidden="true" />
        <div className={s.account} ref={menuRef}>
          <button type="button" className={s.identity} onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-haspopup="menu">
            <span className={s.idText}>
              <span className={s.idName}>{me.name}</span>
              <span className={s.idRole}>{roleLine}</span>
            </span>
            <Icon name="down" size={16} />
          </button>
          {menu && (
            <div className={s.menu} role="menu">
              <button type="button" role="menuitem" onClick={() => { setMenu(false); setPw(true); }}>Change password</button>
              <button type="button" role="menuitem" onClick={() => signOut()}>Sign out</button>
            </div>
          )}
        </div>
      </header>

      <main className={s.workspace}><Outlet /></main>
      <ChangePasswordDialog open={pw} onClose={() => setPw(false)} />
    </div>
  );
}

/** Connection status (2:104): the live stream's state and when data last arrived. */
function Connection() {
  const live = useStreamLive();
  const last = useLastSync();
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 15000); return () => clearInterval(t); }, []);
  const ago = last ? Math.floor((Date.now() - last) / 60000) : null;
  return (
    <div className={s.connection} role="status">
      <p className={live ? s.connOk : s.connWarn}>●&nbsp;&nbsp;{live ? "Live updates on" : "Reconnecting…"}</p>
      <p className={s.connSub}>{ago === null ? "Waiting for first sync" : ago < 1 ? "Last synced just now" : `Last synced ${ago} min ago`}</p>
    </div>
  );
}
