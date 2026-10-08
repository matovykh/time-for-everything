import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, command, request, setActingChild } from "../shared/api/client";
import { apiError, mockApi } from "./mockApi";

beforeEach(() => {
  vi.unstubAllGlobals();
  setActingChild(null);
  document.cookie = "tfe_csrf=tok-1; path=/";
});

describe("api client", () => {
  it("sends CSRF on unsafe methods, same-origin credentials, and never Authorization", async () => {
    const { calls, fetchMock } = mockApi({ "PATCH /me": () => ({ body: { ok: true } }) });
    await request("PATCH", "/me", { body: { theme: "dark" } });
    expect(calls[0].headers["X-CSRF-Token"]).toBe("tok-1");
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "same-origin" });
    expect(localStorage.length).toBe(0);
  });

  it("adds X-Child-Id for a guardian's acting child", async () => {
    const { calls } = mockApi({ "GET /dashboard": () => ({ body: {} }) });
    setActingChild("child-7");
    await request("GET", "/dashboard");
    expect(calls[0].headers["X-Child-Id"]).toBe("child-7");
  });

  it("refreshes once on session_expired and retries", async () => {
    const { calls } = mockApi({
      "GET /wallet": [() => apiError(401, "session_expired"), () => ({ body: { balance: 5 } })],
      "POST /auth/refresh": () => ({ body: { csrf_token: "tok-2", expires_at: "x" } }),
    });
    const res = await request<{ balance: number }>("GET", "/wallet");
    expect(res.balance).toBe(5);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /wallet", "POST /auth/refresh", "GET /wallet"]);
  });

  it("parses the error body and Retry-After", async () => {
    mockApi({
      "POST /auth/login": () => ({ ...apiError(429, "rate_limited"), headers: { "Retry-After": "30" } }),
    });
    const err = (await request("POST", "/auth/login", { body: {} }).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("rate_limited");
    expect(err.retryAfter).toBe(30);
    expect(err.requestId).toBe("req-1");
  });

  it("reuses the same Idempotency-Key when retrying a command after a network error", async () => {
    let n = 0;
    const { calls } = mockApi({
      "POST /activities/a1/timer/start": () => {
        n += 1;
        if (n === 1) return Promise.reject(new TypeError("network down"));
        return { body: { timer: {}, other_running: [] } };
      },
    });
    await command("POST", "/activities/a1/timer/start", { body: { revision: 3 } });
    expect(calls).toHaveLength(2);
    expect(calls[0].headers["Idempotency-Key"]).toBeTruthy();
    expect(calls[1].headers["Idempotency-Key"]).toBe(calls[0].headers["Idempotency-Key"]);
    expect(calls[1].body).toEqual({ revision: 3 });
  });

  it("uses a fresh key for each separate user action", async () => {
    const { calls } = mockApi({ "POST /worlds/settlers/purchases": () => ({ status: 201, body: {} }) });
    await command("POST", "/worlds/settlers/purchases", { body: { upgrade_code: "meadow" } });
    await command("POST", "/worlds/settlers/purchases", { body: { upgrade_code: "workshop" } });
    expect(calls[0].headers["Idempotency-Key"]).not.toBe(calls[1].headers["Idempotency-Key"]);
  });

  it("maps network failure to status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    const err = (await request("GET", "/me").catch((e) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.code).toBe("network_error");
  });
});
