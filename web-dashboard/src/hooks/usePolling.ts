/**
 * Custom React hook for REST polling with lifecycle management.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface UsePollingOptions<T> {
  fn: () => Promise<T>;
  intervalMs?: number;
  enabled?: boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
}

export function usePolling<T>({ fn, intervalMs = 5000, enabled = true }: UsePollingOptions<T>): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fnRef = useRef(fn);
  fnRef.current = fn;

  const execute = useCallback(async () => {
    try {
      const result = await fnRef.current();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch data';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    setLoading(true);
    execute();

    const timer = setInterval(() => {
      execute();
    }, intervalMs);

    return () => {
      clearInterval(timer);
    };
  }, [execute, intervalMs, enabled]);

  return {
    data,
    loading,
    error,
    refetch: execute,
    lastUpdated,
  };
}
