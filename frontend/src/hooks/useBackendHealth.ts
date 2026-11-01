/** Connection state machine: polling /api/health, retry with backoff. */

import { useCallback, useEffect, useRef, useState } from "react";

import { describeError, fetchHealth } from "../api/client";
import type { Health, HealthStatus } from "../types";

const RETRY_MS = 5000;

export interface BackendHealth {
  status: HealthStatus;
  info: Health | null;
  error: string | null;
}

export function useBackendHealth(): BackendHealth & { recheck: () => void } {
  const [state, setState] = useState<BackendHealth>({
    status: "checking",
    info: null,
    error: null,
  });
  const timer = useRef<number | null>(null);

  const checkNow = useCallback(() => {
    fetchHealth()
      .then((info) => setState({ status: "online", info, error: null }))
      .catch((error: unknown) =>
        setState({ status: "offline", info: null, error: describeError(error) }),
      );
  }, []);

  const recheck = useCallback(() => {
    setState((prev) => ({ ...prev, status: "checking" }));
    checkNow();
  }, [checkNow]);

  useEffect(() => {
    checkNow();
    timer.current = window.setInterval(checkNow, RETRY_MS);
    return () => {
      if (timer.current !== null) {
        window.clearInterval(timer.current);
      }
    };
  }, [checkNow]);

  return { ...state, recheck };
}