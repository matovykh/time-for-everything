import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (updater: T | ((prev: T | undefined) => T | undefined)) => void;
}

/**
 * Minimal loader: fetches on mount and whenever `deps` change; ignores stale
 * responses. Keeps the previous data while reloading so screens don't flash.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async () => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      if (id === seq.current) setDataState(result);
    } catch (e) {
      if (id === seq.current) setError(e);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const setData = useCallback((u: T | ((prev: T | undefined) => T | undefined)) => {
    setDataState((prev) => (typeof u === "function" ? (u as (p: T | undefined) => T | undefined)(prev) : u));
  }, []);

  return { data, error, loading, reload: run, setData };
}
