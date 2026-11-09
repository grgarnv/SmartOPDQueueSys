import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, onUnauthorized } from "../api/client";
import type { Health, Role, User } from "../api/types";
import { closeStream } from "../lib/useLive";

interface Session {
  /** undefined while the first /api/me is in flight; null when signed out */
  me: User | null | undefined;
  demo: boolean;
  /** shown on the sign-in page, e.g. after the session expired */
  notice: string;
  signedIn: (u: User) => void;
  signOut: (notice?: string) => Promise<void>;
  updateMe: (patch: Partial<User>) => void;
}

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<User | null>();
  const [demo, setDemo] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api<Health>("/api/health").then((h) => setDemo(h.demo)).catch(() => {});
    api<User>("/api/me").then(setMe, () => setMe(null));
  }, []);

  const end = useCallback((text = "") => {
    closeStream();
    setNotice(text);
    setMe(null);
  }, []);

  // A 401 while signed in means the session ended (expired, password changed elsewhere, account disabled).
  useEffect(() => {
    onUnauthorized(me ? () => end("Your session ended. Please sign in again.") : null);
    return () => onUnauthorized(null);
  }, [me, end]);

  const signedIn = useCallback((u: User) => { setNotice(""); setMe(u); }, []);
  const signOut = useCallback(async (text?: string) => {
    await api("/api/logout", {}).catch(() => {});
    end(text);
  }, [end]);
  const updateMe = useCallback((patch: Partial<User>) => setMe((m) => (m ? { ...m, ...patch } : m)), []);

  return <Ctx.Provider value={{ me, demo, notice, signedIn, signOut, updateMe }}>{children}</Ctx.Provider>;
}

export function useSession() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

/** Signed-in user; only for components rendered inside RequireRole. */
export function useMe(): User {
  const { me } = useSession();
  if (!me) throw new Error("useMe without a signed-in user");
  return me;
}

/** Where each role lands after signing in. */
export const HOME: Record<Role, string> = {
  doctor: "/consultation",
  staff: "/front-desk",
  admin: "/admin",
  patient: "/patient",
  tester: "/simulations",
};
