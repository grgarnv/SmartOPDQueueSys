import { useCallback, useEffect, useRef, useState } from "react";

/*
 * Live data, same rules as the legacy UI (app/index.html, startPolling/connectStream):
 * one shared EventSource on /api/stream; each change message refetches after a 300 ms debounce;
 * a 5 s timer refetches while the stream is down, and every 30 s anyway so clock-driven ETAs stay fresh.
 */
let source: EventSource | null = null;
let live = false;
const listeners = new Set<() => void>();

function openStream() {
  if (source || typeof EventSource === "undefined") return;
  source = new EventSource("/api/stream");
  source.onopen = () => { live = true; };
  source.onerror = () => { live = false; };
  source.onmessage = () => listeners.forEach((l) => l());
}

/** Called on sign-out so the stream does not outlive the session. */
export function closeStream() {
  source?.close();
  source = null;
  live = false;
}

export const isLive = () => live;

export function useLive<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const latest = useRef(fetcher);
  latest.current = fetcher;
  const seq = useRef(0);
  const lastRun = useRef(0);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    lastRun.current = Date.now();
    try {
      const d = await latest.current();
      if (mine === seq.current) { setData(d); setError(undefined); }
    } catch (e) {
      // keep the last good data; the next tick retries
      if (mine === seq.current) setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    setData(undefined);
    setError(undefined);
    refresh();
    let debounce: ReturnType<typeof setTimeout>;
    const onChange = () => { clearTimeout(debounce); debounce = setTimeout(refresh, 300); };
    listeners.add(onChange);
    openStream();
    const timer = setInterval(() => { if (!live || Date.now() - lastRun.current > 30000) refresh(); }, 5000);
    return () => { listeners.delete(onChange); clearTimeout(debounce); clearInterval(timer); };
  }, deps);

  return { data, error, refresh };
}
