// Auth/startup resilience: bounded waiting with cancellation cleanup, precise CSRF errors and a
// bounded CSRF re-bootstrap. The server stays the only CSRF authority; the client never
// fabricates or skips the token, it only fetches a fresh one and retries once.
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { SLOW_START_HINT_MS } from "../features/auth/AuthScreens";
import {
  ApiError,
  AUTH_TIMEOUT_MS,
  command,
  DEFAULT_TIMEOUT_MS,
  LOGIN_TIMEOUT_MS,
  onUnauthorized,
  READY_TIMEOUT_MS,
  request,
  resetClientState,
  setActingChild,
} from "../shared/api/client";
import * as ep from "../shared/api/endpoints";
import { errorText } from "../shared/ui/States";
import { ME, apiError, mockApi, type Call } from "./mockApi";

const FRESH_A = "a".repeat(43);
const FRESH_B = "b".repeat(43);
const hang = () => new Promise<never>(() => {});
const setCookie = (v: string) => {
  document.cookie = `tfe_csrf=${v}; path=/`;
};
const clearCookie = () => {
  document.cookie = "tfe_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
};
const flow = (calls: Call[]) => calls.map((c) => `${c.method} ${c.path}`);
const count = (calls: Call[], key: string) => flow(calls).filter((k) => k === key).length;
/** Fake only timers: fetch mocks and Response bodies keep settling through microtasks. */
const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

function track<T>(p: Promise<T>) {
  const state = { settled: false, value: undefined as unknown };
  const done = p.then(
    (v) => ((state.settled = true), (state.value = v)),
    (e) => ((state.settled = true), (state.value = e)),
  );
  return { state, done };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  resetClientState();
  setActingChild(null);
  sessionStorage.clear();
  localStorage.clear();
  location.hash = "";
  setCookie("tok-1");
});
afterEach(() => {
  vi.useRealTimers();
  onUnauthorized(null);
});

describe("bounded waiting", () => {
  it("documents the exact bounds", () => {
    expect({ DEFAULT_TIMEOUT_MS, AUTH_TIMEOUT_MS, LOGIN_TIMEOUT_MS, READY_TIMEOUT_MS, SLOW_START_HINT_MS }).toEqual({
      DEFAULT_TIMEOUT_MS: 30_000,
      AUTH_TIMEOUT_MS: 10_000,
      LOGIN_TIMEOUT_MS: 20_000,
      READY_TIMEOUT_MS: 5_000,
      SLOW_START_HINT_MS: 5_000,
    });
  });

  it("fails a hanging request with code 'timeout' exactly at the bound, aborts fetch and leaves no timer", async () => {
    fakeTimers();
    const { calls } = mockApi({ "GET /me": hang });
    const t = track(request("GET", "/me", { timeoutMs: 10_000 }));
    await vi.advanceTimersByTimeAsync(9_999);
    expect(t.state.settled).toBe(false);
    expect(calls[0].signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await t.done;
    const err = t.state.value as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0, code: "timeout" });
    expect(calls[0].signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("applies the 30 s default when no timeout is given", async () => {
    fakeTimers();
    mockApi({ "GET /dashboard": hang });
    const t = track(request("GET", "/dashboard"));
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS - 1);
    expect(t.state.settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await t.done;
    expect(t.state.value).toMatchObject({ code: "timeout" });
  });

  it("also bounds a response whose body never finishes", async () => {
    fakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(), text: hang }) as unknown as Response),
    );
    const t = track(request("GET", "/me", { timeoutMs: 1_000 }));
    await vi.advanceTimersByTimeAsync(1_000);
    await t.done;
    expect(t.state.value).toMatchObject({ status: 0, code: "timeout" });
  });

  it("caller abort rejects with AbortError (not an ApiError) and cleans up the timer", async () => {
    fakeTimers();
    const { calls } = mockApi({ "GET /me": hang });
    const ctrl = new AbortController();
    const t = track(request("GET", "/me", { signal: ctrl.signal }));
    await vi.advanceTimersByTimeAsync(0);
    ctrl.abort();
    await t.done;
    expect((t.state.value as Error).name).toBe("AbortError");
    expect(t.state.value).not.toBeInstanceOf(ApiError);
    expect(calls[0].signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a successful request clears its timer", async () => {
    fakeTimers();
    mockApi({ "GET /me": () => ({ body: ME }) });
    await request("GET", "/me");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not auto-retry a command that timed out (network errors still retry once)", async () => {
    fakeTimers();
    const { calls } = mockApi({ "POST /activities/a1/timer/start": hang });
    const t = track(command("POST", "/activities/a1/timer/start", { body: { revision: 1 } }));
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS);
    await t.done;
    expect(t.state.value).toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(count(calls, "POST /activities/a1/timer/start")).toBe(1);
  });

  it("a refresh that cannot reach the server is reported as such, not as a signed-out session", async () => {
    const unauthorized = vi.fn();
    onUnauthorized(unauthorized);
    mockApi({
      "GET /wallet": () => apiError(401, "session_expired"),
      "POST /auth/refresh": () => Promise.reject(new TypeError("offline")),
    });
    const err = (await request("GET", "/wallet").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 0, code: "network_error" });
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("a refresh answered 503 surfaces that error instead of signing the user out", async () => {
    const unauthorized = vi.fn();
    onUnauthorized(unauthorized);
    mockApi({
      "GET /wallet": () => apiError(401, "session_expired"),
      "POST /auth/refresh": () => apiError(503, "auth_unavailable"),
    });
    const err = (await request("GET", "/wallet").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 503, code: "auth_unavailable" });
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("a refresh answered 429 surfaces the rate limit (with Retry-After) instead of signing the user out", async () => {
    const unauthorized = vi.fn();
    onUnauthorized(unauthorized);
    const { calls } = mockApi({
      "GET /wallet": () => apiError(401, "session_expired"),
      "POST /auth/refresh": () => ({ ...apiError(429, "rate_limited"), headers: { "Retry-After": "60" } }),
    });
    const err = (await request("GET", "/wallet").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 429, code: "rate_limited", retryAfter: 60 });
    expect(unauthorized).not.toHaveBeenCalled();
    expect(count(calls, "POST /auth/refresh")).toBe(1);
    expect(count(calls, "GET /wallet")).toBe(1);
  });

  it("a refresh rejected by CSRF while the browser keeps no cookie fails precisely, without a retry", async () => {
    clearCookie();
    const { calls } = mockApi({
      "GET /wallet": () => apiError(401, "session_expired"),
      "GET /auth/csrf": () => ({ body: { csrf_token: FRESH_A } }),
      "POST /auth/refresh": () => apiError(403, "csrf_failed"),
    });
    const err = (await request("GET", "/wallet").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 403, code: "csrf_cookie_missing" });
    expect(count(calls, "POST /auth/refresh")).toBe(1);
  });

  it("a refresh rejected by CSRF gets one fresh token and one retry", async () => {
    const { calls } = mockApi({
      "GET /wallet": [() => apiError(401, "session_expired"), () => ({ body: { balance: 3 } })],
      "GET /auth/csrf": () => (setCookie(FRESH_A), { body: { csrf_token: FRESH_A } }),
      "POST /auth/refresh": [() => apiError(403, "csrf_failed"), () => ({ body: { csrf_token: FRESH_A } })],
    });
    const res = await request<{ balance: number }>("GET", "/wallet");
    expect(res.balance).toBe(3);
    expect(flow(calls)).toEqual(["GET /wallet", "POST /auth/refresh", "GET /auth/csrf", "POST /auth/refresh", "GET /wallet"]);
  });

  it("a refresh answered 401 still means the session is over", async () => {
    const unauthorized = vi.fn();
    onUnauthorized(unauthorized);
    const { calls } = mockApi({
      "GET /wallet": () => apiError(401, "session_expired"),
      "POST /auth/refresh": () => apiError(401, "session_expired"),
    });
    const err = (await request("GET", "/wallet").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 401, code: "session_expired" });
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(count(calls, "POST /auth/refresh")).toBe(1);
  });
});

describe("CSRF", () => {
  it("re-bootstraps when the cookie is gone even though a token is remembered (failed refresh clears it)", async () => {
    clearCookie();
    const { calls } = mockApi({
      "GET /auth/csrf": [
        () => (setCookie(FRESH_A), { body: { csrf_token: FRESH_A } }),
        () => (setCookie(FRESH_B), { body: { csrf_token: FRESH_B } }),
      ],
      "GET /me": () => apiError(401, "not_authenticated"),
      // The real backend deletes tfe_csrf together with the session cookies here.
      "POST /auth/refresh": () => (clearCookie(), apiError(401, "session_expired")),
      "GET /health/ready": () => ({ body: { status: "ready", checks: {} } }),
      "POST /auth/login": () => ({ body: { me: ME, csrf_token: "tok-2" } }),
      "POST /rewards/evaluate": hang,
      "GET /dashboard": hang,
      "GET /activities": hang,
      "GET /analytics/time": hang,
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Электронная почта"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Пароль"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await screen.findByText("Собираем твой день…");
    const loginAt = flow(calls).indexOf("POST /auth/login");
    expect(flow(calls)[loginAt - 1]).toBe("GET /auth/csrf");
    expect(calls[loginAt].headers["X-CSRF-Token"]).toBe(FRESH_B);
    expect(count(calls, "POST /auth/login")).toBe(1);
  });

  it("login rejected by CSRF: one fresh token, one retry, success", async () => {
    const { calls } = mockApi({
      "GET /auth/csrf": () => (setCookie(FRESH_A), { body: { csrf_token: FRESH_A } }),
      "POST /auth/login": [() => apiError(403, "csrf_failed"), () => ({ body: { me: ME, csrf_token: "tok-2" } })],
    });
    const me = await ep.login("a@b.c", "pw");
    expect(me.id).toBe("u1");
    expect(flow(calls)).toEqual(["POST /auth/login", "GET /auth/csrf", "POST /auth/login"]);
    expect(calls[0].headers["X-CSRF-Token"]).toBe("tok-1");
    expect(calls[2].headers["X-CSRF-Token"]).toBe(FRESH_A);
    expect(calls[2].body).toEqual({ email: "a@b.c", password: "pw" });
  });

  it("persistent CSRF rejection: exactly one retry, then a precise csrf_failed error", async () => {
    const { calls } = mockApi({
      "GET /auth/csrf": () => (setCookie(FRESH_A), { body: { csrf_token: FRESH_A } }),
      "POST /auth/login": () => apiError(403, "csrf_failed"),
    });
    const err = (await ep.login("a@b.c", "pw").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 403, code: "csrf_failed" });
    expect(count(calls, "POST /auth/login")).toBe(2);
    expect(count(calls, "GET /auth/csrf")).toBe(1);
  });

  it("cookie not stored by the browser: no pointless retry, csrf_cookie_missing", async () => {
    clearCookie();
    // Server answers, but the browser drops the cookie (e.g. Secure cookie over plain http).
    const { calls } = mockApi({
      "GET /auth/csrf": () => ({ body: { csrf_token: FRESH_A } }),
      "POST /auth/login": () => apiError(403, "csrf_failed"),
    });
    const err = (await ep.login("a@b.c", "pw").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 403, code: "csrf_cookie_missing", requestId: "req-1" });
    expect(flow(calls)).toEqual(["GET /auth/csrf", "POST /auth/login", "GET /auth/csrf"]);
  });

  it("never retries login after a timeout", async () => {
    fakeTimers();
    const { calls } = mockApi({ "POST /auth/login": hang });
    const t = track(ep.login("a@b.c", "pw"));
    await vi.advanceTimersByTimeAsync(LOGIN_TIMEOUT_MS - 1);
    expect(t.state.settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await t.done;
    expect(t.state.value).toMatchObject({ status: 0, code: "timeout" });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(count(calls, "POST /auth/login")).toBe(1);
  });

  it("never retries login after a network failure", async () => {
    const { calls } = mockApi({ "POST /auth/login": () => Promise.reject(new TypeError("reset")) });
    const err = (await ep.login("a@b.c", "pw").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 0, code: "network_error" });
    expect(count(calls, "POST /auth/login")).toBe(1);
  });

  it("explains CSRF failures precisely instead of 'insufficient rights'", () => {
    const e = (code: string, status = 403) => new ApiError({ status, code, message: code });
    expect(errorText(e("csrf_failed"))).toMatch(/CSRF/);
    expect(errorText(e("csrf_failed"))).not.toMatch(/Недостаточно прав/);
    expect(errorText(e("csrf_cookie_missing"))).toMatch(/не сохранил защитный cookie/);
    expect(errorText(e("forbidden"))).toBe("Недостаточно прав для этого действия.");
    expect(errorText(e("timeout", 0))).toMatch(/не ответил вовремя/);
    expect(errorText(e("network_error", 0))).toMatch(/Нет связи/);
  });

  it("the login form shows the precise CSRF message", async () => {
    const { calls } = mockApi({
      "GET /auth/csrf": () => (setCookie(FRESH_A), { body: { csrf_token: FRESH_A } }),
      "GET /me": () => apiError(401, "not_authenticated"),
      "POST /auth/refresh": () => apiError(401, "session_expired"),
      "GET /health/ready": () => ({ body: { status: "ready", checks: {} } }),
      "POST /auth/login": () => apiError(403, "csrf_failed"),
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Электронная почта"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Пароль"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/CSRF/);
    expect(alert).not.toHaveTextContent(/Недостаточно прав/);
    expect(count(calls, "POST /auth/login")).toBe(2);
  });
});

describe("startup never spins forever", () => {
  const anonymous = {
    "GET /auth/csrf": () => ({ body: { csrf_token: "tok-1" } }),
    "POST /auth/refresh": () => apiError(401, "session_expired"),
  };

  it("hanging /me and /health/ready: hint at 5 s, 'server not responding' screen at 15 s, retry recovers", async () => {
    fakeTimers();
    const { calls } = mockApi({
      ...anonymous,
      "GET /me": [hang, () => apiError(401, "not_authenticated")],
      "GET /health/ready": [hang, () => ({ body: { status: "ready", checks: {} } })],
    });
    render(<App />);
    expect(screen.getByText("Открываем твой остров…")).toBeInTheDocument();
    expect(screen.queryByText(/дольше обычного/)).toBeNull();

    await advance(SLOW_START_HINT_MS);
    expect(screen.getByText(/Сервер отвечает дольше обычного/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Попробовать снова" })).toBeInTheDocument();

    await advance(AUTH_TIMEOUT_MS - SLOW_START_HINT_MS); // t = 10 s: /me gives up
    expect(calls.find((c) => c.path === "/me")?.signal?.aborted).toBe(true);
    expect(screen.queryByRole("heading", { name: "Сервер не отвечает" })).toBeNull();

    await advance(READY_TIMEOUT_MS); // t = 15 s: readiness probe gives up too
    expect(screen.getByRole("heading", { name: "Сервер не отвечает" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/не ответил вовремя/);
    expect(calls.find((c) => c.path === "/health/ready")?.signal?.aborted).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Проверить снова" }));
    await advance(0);
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
  });

  it("'try again' while checking aborts the in-flight attempt; it cannot overwrite the new result later", async () => {
    fakeTimers();
    const { calls } = mockApi({
      ...anonymous,
      "GET /me": [hang, () => apiError(401, "not_authenticated")],
      "GET /health/ready": () => ({ body: { status: "ready", checks: {} } }),
    });
    render(<App />);
    await advance(SLOW_START_HINT_MS);
    fireEvent.click(screen.getByRole("button", { name: "Попробовать снова" }));
    await advance(0);
    const meCalls = calls.filter((c) => c.path === "/me");
    expect(meCalls).toHaveLength(2);
    expect(meCalls[0].signal?.aborted).toBe(true);
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
    await advance(60_000); // the first attempt's timers were cleared; nothing flips the screen
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Сервер не отвечает" })).toBeNull();
  });

  for (const [status, code] of [
    [503, "auth_unavailable"],
    [429, "rate_limited"],
  ] as const) {
    it(`startup: refresh answered ${status} shows the retryable server screen, not the login form`, async () => {
      const { calls } = mockApi({
        "GET /auth/csrf": () => ({ body: { csrf_token: "tok-1" } }),
        "GET /me": [() => apiError(401, "not_authenticated"), () => apiError(401, "not_authenticated")],
        "POST /auth/refresh": [() => apiError(status, code), () => apiError(401, "session_expired")],
        "GET /health/ready": () => ({ body: { status: "ready", checks: {} } }),
      });
      render(<App />);
      expect(await screen.findByRole("heading", { name: "Приложение ещё настраивается" })).toBeInTheDocument();
      expect(screen.queryByLabelText("Пароль")).toBeNull();
      expect(screen.getByRole("alert")).toHaveTextContent(
        status === 503 ? "Supabase Auth" : "Слишком много попыток",
      );
      expect(count(calls, "POST /auth/refresh")).toBe(1);
      // Retry: the refresh now definitively says 401 → the login form.
      await userEvent.click(screen.getByRole("button", { name: "Проверить снова" }));
      expect(await screen.findByLabelText("Пароль")).toBeInTheDocument();
    });
  }

  it("unmount aborts startup requests", async () => {
    fakeTimers();
    const { calls } = mockApi({ ...anonymous, "GET /me": hang });
    const { unmount } = render(<App />);
    await advance(0);
    unmount();
    expect(calls.find((c) => c.path === "/me")?.signal?.aborted).toBe(true);
  });

  it("a hanging CSRF bootstrap is bounded as well", async () => {
    fakeTimers();
    clearCookie();
    mockApi({ "GET /auth/csrf": hang, "GET /health/ready": hang });
    render(<App />);
    await advance(AUTH_TIMEOUT_MS + READY_TIMEOUT_MS);
    expect(screen.getByRole("heading", { name: "Сервер не отвечает" })).toBeInTheDocument();
  });
});
