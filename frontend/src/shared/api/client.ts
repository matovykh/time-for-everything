import type { FieldError } from "./types";

// Same-origin JSON client for /api/v1 (docs/API.md §1).
// - Session lives in HttpOnly cookies set by the backend; nothing auth-related
//   is stored in localStorage.
// - Unsafe methods carry X-CSRF-Token (double-submit cookie `tfe_csrf`).
// - 401 session_expired → POST /auth/refresh once, then retry once.
// - 403 csrf_failed → re-bootstrap the CSRF token once, then retry once.

export const API_BASE = "/api/v1";

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

let csrfPromise: Promise<string | null> | null = null;
export async function ensureCsrf(force = false): Promise<string | null> {
  if (!force) {
    const cookie = readCsrfCookie();
    if (cookie) csrfToken = cookie;
    if (csrfToken) return csrfToken;
  }
  csrfPromise ??= (async () => {
    try {
      const res = await rawFetch("GET", "/auth/csrf");
      const body = (await res.json().catch(() => null)) as { csrf_token?: string } | null;
      csrfToken = body?.csrf_token ?? readCsrfCookie();
      return csrfToken;
    } finally {
      csrfPromise = null;
    }
  })();
  return csrfPromise;
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

let refreshPromise: Promise<boolean> | null = null;
export async function refreshSession(): Promise<boolean> {
  refreshPromise ??= (async () => {
    try {
      await ensureCsrf();
      const res = await rawFetch("POST", "/auth/refresh");
      if (!res.ok) return false;
      const body = (await res.json().catch(() => null)) as { csrf_token?: string } | null;
      setCsrfToken(body?.csrf_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

async function toError(res: Response): Promise<ApiError> {
  const body = (await res.json().catch(() => null)) as {
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
  if (method !== "GET") await ensureCsrf();
  let res: Response;
  try {
    res = await rawFetch(method, path, opts);
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError({ status: 0, code: "network_error", message: "Нет связи с сервером" });
  }
  if (res.ok) {
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }
  const err = await toError(res);
  if (!opts.retried && !path.startsWith("/auth/")) {
    if (err.status === 401 && err.code === "session_expired") {
      // Retry with the same Idempotency-Key, so the command is never applied twice.
      if (await refreshSession()) return request<T>(method, path, { ...opts, retried: true });
    }
    if (err.status === 403 && err.code === "csrf_failed") {
      await ensureCsrf(true);
      return request<T>(method, path, { ...opts, retried: true });
    }
  }
  if (err.status === 401 && !path.startsWith("/auth/")) unauthorizedHandler?.();
  return Promise.reject(err);
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
    if (e instanceof ApiError && (e.status === 0 || e.code === "idempotency_conflict")) {
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
