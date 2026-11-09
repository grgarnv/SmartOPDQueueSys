import { Navigate, Route, Routes } from "react-router";
import type { Role } from "./api/types";
import { LoginPage } from "./auth/LoginPage";
import { RequireRole } from "./auth/RequireRole";
import { HOME, useSession } from "./auth/session";
import { LoadingState } from "./design/ui";
import { Specimen } from "./features/design-system/Specimen";
import { NotMigrated } from "./features/pending/NotMigrated";

// Route table from docs/FRONTEND_MIGRATION.md §2.3. Screens still in the legacy UI render <NotMigrated>.
const screens: { path: string; roles: Role[]; title: string }[] = [
  { path: "/consultation", roles: ["doctor"], title: "Consultation" },
  { path: "/front-desk", roles: ["staff", "admin"], title: "Front desk" },
  { path: "/emergency", roles: ["staff", "admin"], title: "Emergency priority" },
  { path: "/queue-monitor", roles: ["staff", "admin"], title: "Queue monitor" },
  { path: "/admin/*", roles: ["admin"], title: "Administration" },
  { path: "/patient", roles: ["patient"], title: "Your appointments" },
  { path: "/simulations", roles: ["tester"], title: "Simulations" },
];

function Home() {
  const { me } = useSession();
  if (me === undefined) return <div style={{ padding: "var(--s6)" }}><LoadingState title="Signing you in…" rows={2} /></div>;
  return <Navigate to={me ? HOME[me.role] : "/login"} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/design-system" element={<Specimen />} />
      {screens.map(({ path, roles, title }) => (
        <Route key={path} path={path} element={<RequireRole roles={roles}><NotMigrated screen={title} /></RequireRole>} />
      ))}
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
