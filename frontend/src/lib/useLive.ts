import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/*
 * Live data, same rules as the legacy UI (app/index.html, startPolling/connectStream):
 * one shared EventSource on /api/stream; each change message refetches after a 300 ms debounce;
 * a 5 s timer refetches while the stream is down, and every 30 s anyway so clock-driven ETAs stay fresh.
 */
let source: EventSource | null = null;
let live = false;
const listeners = new Set<() => void>();
const liveWatchers = new Set<() => void>();
const setLive = (v: boolean) => { if (live !== v) { live = v; liveWatchers.forEach((w) => w()); } };
let lastSync = 0;  // browser time of the last successful read on any screen

function openStream() {
  if (source || typeof EventSource === "undefined") return;
  source = new EventSource("/api/stream");
  source.onopen = () => setLive(true);
  source.onerror = () => setLive(false);
  source.onmessage = () => listeners.forEach((l) => l());
}

/** Called on sign-out so the stream does not outlive the session. */
export function closeStream() {
  source?.close();
  source = null;
  setLive(false);
}

export const isLive = () => live;

const watch = (cb: () => void) => { liveWatchers.add(cb); return () => { liveWatchers.delete(cb); }; };

/** Re-renders when the live stream connects or drops. */
export function useStreamLive() {
  return useSyncExternalStore(watch, () => live);
}

/** Browser time (ms) of the last successful live read, 0 before the first. */
export function useLastSync() {
  return useSyncExternalStore(watch, () => lastSync);
}

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
      lastSync = Date.now();
      liveWatchers.forEach((w) => w());
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

  /** Show a server reply right away (e.g. the queue_state an action returns); older in-flight reads are dropped. */
  const set = useCallback((d: T) => { seq.current++; setData(d); setError(undefined); }, []);

  return { data, error, refresh, set };
}
