import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  ensureCsrf,
  getActingChild,
  isAbortError,
  onUnauthorized,
  refreshSession,
  resetClientState,
  SETUP_CODES,
  setActingChild,
} from "../shared/api/client";
import * as ep from "../shared/api/endpoints";
import type { HealthReady, Me } from "../shared/api/types";
import { setThemeChoice } from "./theme";

export type SessionStatus =
  | { kind: "checking" }
  | { kind: "setup"; error: ApiError; ready: HealthReady | null }
  | { kind: "anonymous"; reason?: "expired" }
  | { kind: "signed_out"; warning?: string; retryable?: boolean }
  | { kind: "authenticated"; me: Me };

interface SessionValue {
  status: SessionStatus;
  me: Me | null;
  /** Wallet balance from the latest server response; null = not loaded yet. */
  balance: number | null;
  setBalance: (b: number | null | undefined) => void;
  updateMe: (me: Me) => void;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  retry: () => void;
  switchChild: (id: string | null) => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);
const CHILD_KEY = "vse-uspeyu-acting-child";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>({ kind: "checking" });
  const [balance, setBalanceState] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);

  const setBalance = useCallback((b: number | null | undefined) => {
    if (typeof b === "number") setBalanceState(b);
    else if (b === null) setBalanceState(null);
  }, []);

  const afterLogin = useCallback(async (me: Me) => {
    if (me.theme) setThemeChoice(me.theme);
    setStatus({ kind: "authenticated", me });
    // Evaluates only due periods; idempotent and safe on every start (API §6).
    try {
      const r = await ep.evaluateRewards();
      setBalanceState(r.balance);
    } catch {
      try {
        const w = await ep.getWallet(null, 1);
        setBalanceState(w.balance);
      } catch {
        /* header shows "—" until a screen loads the balance */
      }
    }
  }, []);

  // Startup check. Every step is bounded (client.ts): /auth/csrf, /me and /auth/refresh by
  // AUTH_TIMEOUT_MS each, /health/ready by READY_TIMEOUT_MS. A new attempt (retry, child
  // switch, unmount) aborts the previous one, so no stale request can overwrite the status.
  useEffect(() => {
    const ctrl = new AbortController();
    const { signal } = ctrl;
    (async () => {
      setStatus({ kind: "checking" });
      try {
        // Guardian's choice of acting child is not a credential; sessionStorage is fine.
        const savedChild = sessionStorage.getItem(CHILD_KEY);
        if (savedChild) setActingChild(savedChild);
      } catch {
        /* ignore */
      }
      try {
        await ensureCsrf(false, signal);
        let me: Me;
        try {
          me = await ep.getMe({ signal });
        } catch (e) {
          if (e instanceof ApiError && e.status === 401 && (await refreshSession(signal)))
            me = await ep.getMe({ signal });
          else throw e;
        }
        if (!signal.aborted) await afterLogin(me);
      } catch (e) {
        if (signal.aborted || isAbortError(e)) return;
        if (e instanceof ApiError && e.status === 401) {
          // An unconfigured backend still answers /me with 401; check readiness so the
          // child does not face a login form that can never succeed.
          const ready = await ep.getReady(signal);
          if (signal.aborted) return;
          if (ready && ready.status !== "ready")
            setStatus({
              kind: "setup",
              error: new ApiError({ status: 503, code: "service_not_configured", message: "not ready" }),
              ready,
            });
          else setStatus({ kind: "anonymous" });
        } else if (e instanceof ApiError && e.status === 404 && getActingChild()) {
          // Saved child no longer linked: drop it and try again.
          setActingChild(null);
          sessionStorage.removeItem(CHILD_KEY);
          setAttempt((a) => a + 1);
        } else {
          const err =
            e instanceof ApiError
              ? e
              : new ApiError({ status: 0, code: "network_error", message: String(e) });
          const ready = await ep.getReady(signal);
          if (signal.aborted) return;
          setStatus({ kind: "setup", error: err, ready });
        }
      }
    })();
    return () => ctrl.abort();
  }, [attempt, afterLogin]);

  useEffect(() => {
    onUnauthorized(() => {
      setStatus((s) => (s.kind === "authenticated" ? { kind: "anonymous", reason: "expired" } : s));
      setBalanceState(null);
    });
    return () => onUnauthorized(null);
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const me = await ep.login(email, password);
      await afterLogin(me);
    },
    [afterLogin],
  );

  const signOut = useCallback(async () => {
    let warning: string | undefined;
    let retryable = false;
    try {
      await ep.logout();
    } catch (e) {
      if (e instanceof ApiError && e.code === "logout_incomplete") {
        // Cookies are already cleared by the server; the remote session may still be valid.
        warning =
          e.message ||
          "Выход на этом устройстве выполнен, но сервер не смог завершить сессию. Войди снова и повтори выход позже.";
      } else {
        // Network/other failure: the HttpOnly cookies may still be in the browser.
        warning = "Не удалось связаться с сервером, поэтому выход может быть не завершён. Повтори выход, когда связь появится.";
        retryable = true;
      }
    }
    // Drop everything sensitive held by the client, whatever the server said.
    resetClientState();
    setActingChild(null);
    try {
      sessionStorage.removeItem(CHILD_KEY);
    } catch {
      /* ignore */
    }
    history.replaceState(null, "", location.pathname + location.search);
    setBalanceState(null);
    setStatus({ kind: "signed_out", warning, retryable });
  }, []);

  const switchChild = useCallback(async (id: string | null) => {
    setActingChild(id);
    try {
      if (id) sessionStorage.setItem(CHILD_KEY, id);
      else sessionStorage.removeItem(CHILD_KEY);
    } catch {
      /* ignore */
    }
    setBalanceState(null);
    setAttempt((a) => a + 1);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      me: status.kind === "authenticated" ? status.me : null,
      balance,
      setBalance,
      updateMe: (me) => setStatus({ kind: "authenticated", me }),
      signIn,
      signOut,
      retry: () => setAttempt((a) => a + 1),
      switchChild,
    }),
    [status, balance, setBalance, signIn, signOut, switchChild],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}

/** Only for authenticated screens. */
export function useMe(): Me {
  const { me } = useSession();
  if (!me) throw new Error("useMe requires an authenticated session");
  return me;
}

export { SETUP_CODES };
