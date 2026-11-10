import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import type { Role } from "../api/types";
import { LoadingState } from "../design/ui";
import { HOME, useSession } from "./session";

/** Convenience only: the server checks the role on every API call. */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me } = useSession();
  const location = useLocation();
  if (me === undefined) return <div style={{ padding: "var(--s6)" }}><LoadingState title="Signing you in…" rows={2} /></div>;
  if (!me) return <Navigate to="/login" replace state={{ from: location }} />;
  if (!roles.includes(me.role)) return <Navigate to={HOME[me.role]} replace />;
  return children;
}
