import type { FieldError } from "./types";

// Same-origin JSON client for /api/v1 (docs/API.md §1).
// - Session lives in HttpOnly cookies set by the backend; nothing auth-related
//   is stored in localStorage.
// - Unsafe methods carry X-CSRF-Token (double-submit cookie `tfe_csrf`).
// - 401 session_expired → POST /auth/refresh once, then retry once.
// - 403 csrf_failed → re-bootstrap the CSRF token once, then retry once (unsafe methods
//   only; skipped when the browser did not store the cookie, because a retry cannot help).
// - Every exchange (headers + body) is bounded by a timeout. A timeout is ApiError
//   status 0 / code "timeout" and is never retried automatically.

export const API_BASE = "/api/v1";

/** Upper bound for any API request that does not pass its own `timeoutMs`. */
export const DEFAULT_TIMEOUT_MS = 30_000;
/** /auth/csrf, /auth/refresh and the startup /me check. */
export const AUTH_TIMEOUT_MS = 10_000;
/** POST /auth/login (Supabase sign-in may be slow on a small server). */
export const LOGIN_TIMEOUT_MS = 20_000;
/** GET /health/ready, used only as a diagnostic after another failure. */
export const READY_TIMEOUT_MS = 5_000;

export class ApiError extends Error {
  status: number;
  code: string;
  fieldErrors: FieldError[];
  requestId?: string;
  details: Record<string, unknown> | null;
  retryAfter?: number;
  constructor(init: {
    status: number;
    code: string;
    message: string;
    fieldErrors?: FieldError[];
    requestId?: string;
    details?: Record<string, unknown> | null;
    retryAfter?: number;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.fieldErrors = init.fieldErrors ?? [];
    this.requestId = init.requestId;
    this.details = init.details ?? null;
    this.retryAfter = init.retryAfter;
  }
  fieldMessage(field: string): string | undefined {
    return this.fieldErrors.find((f) => f.field === field)?.message;
  }
}

/** Codes that mean "the installation is not set up", not a user mistake. */
export const SETUP_CODES = new Set(["service_not_configured", "schema_missing", "auth_unavailable"]);

let csrfToken: string | null = null;
let actingChildId: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setActingChild(id: string | null) {
  actingChildId = id;
}
export function getActingChild() {
  return actingChildId;
}
export function onUnauthorized(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}
export function setCsrfToken(token: string | null | undefined) {
  if (token) csrfToken = token;
}
/** Forget per-session client state (CSRF token, acting child) on sign-out. */
export function resetClientState() {
  csrfToken = null;
  actingChildId = null;
}

function readCsrfCookie(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)tfe_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** True when the browser holds the double-submit cookie the server compares against. */
export function hasCsrfCookie(): boolean {
  return readCsrfCookie() !== null;
}

export function isAbortError(e: unknown): boolean {
  return (e as { name?: unknown } | null)?.name === "AbortError";
}

function abortError(): Error {
  return typeof DOMException === "function"
    ? new DOMException("The operation was aborted.", "AbortError")
    : Object.assign(new Error("The operation was aborted."), { name: "AbortError" });
}

/**
 * Settles with `p`, or rejects with an AbortError as soon as `signal` aborts — even if the
 * underlying promise never settles. The abort listener is always removed.
 */
export function abortable<T>(p: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return p;
  if (signal.aborted) {
    p.catch(() => {});
    return Promise.reject(abortError());
  }
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    p.then(
      (v) => {
        signal.removeEventListener("abort", onAbort);
        resolve(v);
      },
      (e) => {
        signal.removeEventListener("abort", onAbort);
        reject(e);
      },
    );
  });
}

let csrfPromise: Promise<string | null> | null = null;
/**
 * Makes sure the double-submit cookie exists. The cookie is the source of truth: a token
 * remembered in memory is useless once the server has cleared the cookie (a failed
 * /auth/refresh does that), so without a cookie we always ask /auth/csrf again.
 * The shared bootstrap is bounded by AUTH_TIMEOUT_MS; `signal` only stops this caller waiting.
 */
export async function ensureCsrf(force = false, signal?: AbortSignal): Promise<string | null> {
  if (!force) {
    const cookie = readCsrfCookie();
    if (cookie) return (csrfToken = cookie);
  }
  csrfPromise ??= (async () => {
    try {
      const { res, text } = await exchange("GET", "/auth/csrf", {}, AUTH_TIMEOUT_MS);
      const body = res.ok ? (parseJson(text) as { csrf_token?: string } | null) : null;
      csrfToken = body?.csrf_token ?? readCsrfCookie();
      return csrfToken;
    } finally {
      csrfPromise = null;
    }
  })();
  return abortable(csrfPromise, signal);
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  idempotencyKey?: string;
  /** Internal: prevents refresh/CSRF retry loops. */
  retried?: boolean;
  signal?: AbortSignal;
  /** Bound for the whole exchange (headers + body); defaults to DEFAULT_TIMEOUT_MS. */
  timeoutMs?: number;
}

function buildUrl(path: string, query?: RequestOptions["query"]) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return `${API_BASE}${path}${s ? `?${s}` : ""}`;
}

async function rawFetch(method: Method, path: string, opts: RequestOptions = {}) {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = readCsrfCookie() ?? csrfToken;
    if (token) headers["X-CSRF-Token"] = token;
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  if (actingChildId) headers["X-Child-Id"] = actingChildId;
  return fetch(buildUrl(path, opts.query), {
    method,
    headers,
    credentials: "same-origin",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });
}

function parseJson(text: string): unknown {
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

/**
 * One HTTP exchange — response headers and body — bounded by `timeoutMs`. The timer and the
 * caller-signal listener are always cleaned up, and the fetch is aborted on timeout.
 * Caller abort → AbortError; timeout → ApiError(0, "timeout"); other failure → ApiError(0, "network_error").
 */
async function exchange(
  method: Method,
  path: string,
  opts: RequestOptions,
  timeoutMs: number,
): Promise<{ res: Response; text: string }> {
  const outer = opts.signal;
  const ctrl = new AbortController();
  let expired = false;
  const onOuterAbort = () => ctrl.abort();
  if (outer?.aborted) ctrl.abort();
  else outer?.addEventListener("abort", onOuterAbort, { once: true });
  const timer = setTimeout(() => {
    expired = true;
    ctrl.abort();
  }, timeoutMs);
  try {
    // `abortable` guarantees the bound even if a fetch implementation ignores the signal.
    const res = await abortable(rawFetch(method, path, { ...opts, signal: ctrl.signal }), ctrl.signal);
    const text = await abortable(res.text(), ctrl.signal);
    return { res, text };
  } catch (e) {
    if (outer?.aborted) throw abortError();
    if (expired)
      throw new ApiError({
        status: 0,
        code: "timeout",
        message: `Сервер не ответил за ${Math.round(timeoutMs / 1000)} с`,
        details: { timeout_ms: timeoutMs },
      });
    if (isAbortError(e)) throw e;
    throw new ApiError({ status: 0, code: "network_error", message: "Нет связи с сервером" });
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onOuterAbort);
  }
}

/**
 * Bounded GET that never throws on an HTTP error status (for diagnostics such as
 * /health/ready, whose 503 still carries a useful body).
 */
export async function probe(
  path: string,
  opts: { signal?: AbortSignal; timeoutMs: number },
): Promise<{ status: number; body: unknown }> {
  const { res, text } = await exchange("GET", path, { signal: opts.signal }, opts.timeoutMs);
  return { status: res.status, body: parseJson(text) };
}

let refreshPromise: Promise<boolean> | null = null;
/**
 * true = refreshed; false = the server answered 401 (session really over).
 * Anything else rejects with the real error — transport failures as ApiError(0), 429/5xx as
 * themselves — so a slow or briefly unavailable server does not sign the user out.
 * A CSRF rejection gets the same single re-bootstrap + retry as other unsafe requests.
 */
export async function refreshSession(signal?: AbortSignal): Promise<boolean> {
  refreshPromise ??= (async () => {
    try {
      await ensureCsrf();
      const send = () => exchange("POST", "/auth/refresh", {}, AUTH_TIMEOUT_MS);
      let { res, text } = await send();
      if (res.status === 403 && toError(res, text).code === "csrf_failed") {
        await ensureCsrf(true);
        if (hasCsrfCookie()) ({ res, text } = await send());
      }
      if (res.ok) {
        setCsrfToken((parseJson(text) as { csrf_token?: string } | null)?.csrf_token);
        return true;
      }
      if (res.status === 401) return false;
      throw csrfAware(toError(res, text));
    } finally {
      refreshPromise = null;
    }
  })();
  return abortable(refreshPromise, signal);
}

function toError(res: Response, text: string): ApiError {
  const body = parseJson(text) as {
    code?: string;
    message?: string;
    field_errors?: FieldError[];
    request_id?: string;
    details?: Record<string, unknown> | null;
  } | null;
  const retry = Number(res.headers.get("Retry-After"));
  return new ApiError({
    status: res.status,
    code: body?.code ?? `http_${res.status}`,
    message: body?.message ?? res.statusText ?? "Ошибка запроса",
    fieldErrors: body?.field_errors ?? [],
    requestId: body?.request_id ?? res.headers.get("X-Request-ID") ?? undefined,
    details: body?.details ?? null,
    retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
  });
}

export async function request<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
  if (method !== "GET") await ensureCsrf(false, opts.signal);
  const { res, text } = await exchange(method, path, opts, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  if (res.ok) {
    if (res.status === 204) return undefined as T;
    return (text ? JSON.parse(text) : undefined) as T;
  }
  const err = toError(res, text);
  if (!opts.retried) {
    if (err.status === 401 && err.code === "session_expired" && !path.startsWith("/auth/")) {
      // Retry with the same Idempotency-Key, so the command is never applied twice.
      if (await refreshSession(opts.signal)) return request<T>(method, path, { ...opts, retried: true });
    }
    if (err.status === 403 && err.code === "csrf_failed" && method !== "GET") {
      // The CSRF middleware rejects before any handler runs (no login attempt is counted,
      // no command is applied), so one fresh token + one retry is safe — including for
      // /auth/login. Without a stored cookie the retry would fail the same way: skip it.
      await ensureCsrf(true, opts.signal);
      if (hasCsrfCookie()) return request<T>(method, path, { ...opts, retried: true });
    }
  }
  if (err.status === 401 && !path.startsWith("/auth/")) unauthorizedHandler?.();
  throw csrfAware(err);
}

/** A CSRF rejection while the browser holds no CSRF cookie: name the real cause. */
function csrfAware(err: ApiError): ApiError {
  if (err.code !== "csrf_failed" || hasCsrfCookie()) return err;
  return new ApiError({ status: 403, code: "csrf_cookie_missing", message: err.message, requestId: err.requestId });
}

/**
 * Commands that require Idempotency-Key: one key per user action, reused for a
 * single automatic retry after a network failure (API.md §1.5).
 */
export async function command<T>(method: Method, path: string, opts: Omit<RequestOptions, "idempotencyKey"> = {}): Promise<T> {
  const key = newIdempotencyKey();
  try {
    return await request<T>(method, path, { ...opts, idempotencyKey: key });
  } catch (e) {
    // A timeout is not retried: a server that just hung for the whole bound is unlikely to
    // answer now, and the user gets an understandable error instead of a doubled wait.
    if (e instanceof ApiError && ((e.status === 0 && e.code !== "timeout") || e.code === "idempotency_conflict")) {
      await new Promise((r) => setTimeout(r, e.status === 0 ? 600 : 1200));
      return request<T>(method, path, { ...opts, idempotencyKey: key });
    }
    throw e;
  }
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T>(path: string, query?: RequestOptions["query"]) => request<T>("DELETE", path, { query }),
};
