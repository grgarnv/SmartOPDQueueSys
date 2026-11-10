import { api } from "../../api/client";
import type { AlertRow, Overview, Policy } from "../../api/types";
import { useLive } from "../../lib/useLive";

// Live desk data (staff, admin). Kept live like the queue, so a doctor's status, today's check-in code and
// alert deliveries never go stale on an open screen.
export const useOverview = () => useLive(() => api<Overview>("/api/admin/overview"));
export const usePolicy = () => useLive(() => api<Policy>("/api/admin/policy"));
export const useAlerts = () => useLive(() => api<{ notifications: AlertRow[] }>("/api/admin/notifications"));
