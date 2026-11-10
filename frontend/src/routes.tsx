import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router";
import type { Role } from "./api/types";
import { LoginPage } from "./auth/LoginPage";
import { RequireRole } from "./auth/RequireRole";
import { HOME, useSession } from "./auth/session";
import { LoadingState } from "./design/ui";
import { ConsultationPage } from "./features/consultation/ConsultationPage";
import { Specimen } from "./features/design-system/Specimen";
import { FrontDeskPage } from "./features/front-desk/FrontDeskPage";
import { NotMigrated } from "./features/pending/NotMigrated";
import { QueueMonitorPage } from "./features/queue-monitor/QueueMonitorPage";
import { AppShell } from "./layout/AppShell";

// Route table from docs/FRONTEND_MIGRATION.md §2.3. Doctor, staff and admin screens sit in the app shell
// (Figma sidebar + bar); patient and tester screens have their own layouts and come later.
const deskScreens: { path: string; roles: Role[]; title: string; element?: ReactNode }[] = [
  { path: "/front-desk", roles: ["staff", "admin"], title: "Front desk", element: <FrontDeskPage /> },
  { path: "/emergency", roles: ["staff", "admin"], title: "Emergency priority" },
  { path: "/queue-monitor", roles: ["staff", "admin"], title: "Queue monitor", element: <QueueMonitorPage /> },
  { path: "/admin/*", roles: ["admin"], title: "Administration" },
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
      <Route element={<RequireRole roles={["doctor", "staff", "admin"]}><AppShell /></RequireRole>}>
        <Route path="/consultation" element={<RequireRole roles={["doctor"]}><ConsultationPage /></RequireRole>} />
        {deskScreens.map(({ path, roles, title, element }) => (
          <Route key={path} path={path} element={<RequireRole roles={roles}>{element ?? <NotMigrated screen={title} />}</RequireRole>} />
        ))}
      </Route>
      <Route path="/patient" element={<RequireRole roles={["patient"]}><NotMigrated screen="Your appointments" bare /></RequireRole>} />
      <Route path="/simulations" element={<RequireRole roles={["tester"]}><NotMigrated screen="Simulations" bare /></RequireRole>} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
