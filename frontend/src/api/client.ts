/**
 * The one way the UI talks to app/server.py. Same contract as the legacy api() in app/index.html:
 * GET without a body, POST with a JSON body; the server's {error} message is shown as-is;
 * a 401 while signed in ends the session in the UI.
 */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

let unauthorized: (() => void) | null = null;

/** The session provider registers this while someone is signed in. */
export function onUnauthorized(fn: (() => void) | null) {
  unauthorized = fn;
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check the connection and try again.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && unauthorized) {
    unauthorized();
    throw new ApiError("Please sign in.", 401);
  }
  if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status}). Try again.`, res.status);
  return data as T;
}

/** Query string from an object, skipping empty values. */
export const qs = (params: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, String(v)])).toString();
