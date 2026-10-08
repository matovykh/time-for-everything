// QA UI-01/02/08: every route renders something meaningful under server errors, empty data and
// hostile user text; no uncaught exceptions. Reuses frontend/src/test helpers read-only.
import { render, screen, waitFor } from "@testing-library/react";
import { App } from "../../frontend/src/app/App";
import { setActingChild } from "../../frontend/src/shared/api/client";
import { ME, activity, idleTimer } from "../../frontend/src/test/mockApi";

const ROUTES = ["", "#home", "#lessons", "#walk", "#chores", "#world", "#rewards", "#settings", "#profile",
  "#activity/a-math", "#activity/does-not-exist", "#garbage/../../x", "#activity/%3Cscript%3E"];

type Reply = { status?: number; body?: unknown };
function stubFetch(handler: (method: string, path: string) => Reply) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const p = url.pathname.replace(/^\/api\/v1/, "");
    calls.push(`${method} ${p}`);
    const r = handler(method, p);
    const status = r.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(r.body ?? {}), {
      status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}
const err = (status: number, code: string) => ({ status, body: { code, message: code, field_errors: [], request_id: "qa-req", details: null } });

const pageErrors: unknown[] = [];
const onErr = (e: ErrorEvent) => pageErrors.push(e.error ?? e.message);
const onRej = (e: PromiseRejectionEvent) => pageErrors.push(e.reason);

beforeEach(() => {
  vi.unstubAllGlobals();
  setActingChild(null);
  sessionStorage.clear();
  localStorage.clear();
  document.cookie = "tfe_csrf=tok-qa; path=/";
  pageErrors.length = 0;
  window.addEventListener("error", onErr);
  window.addEventListener("unhandledrejection", onRej);
});
afterEach(() => {
  window.removeEventListener("error", onErr);
  window.removeEventListener("unhandledrejection", onRej);
});

async function settle(route: string) {
  location.hash = route;
  const { container } = render(<App />);
  await waitFor(() => expect(container.querySelector("main")).not.toBeNull(), { timeout: 3000 });
  await waitFor(() => expect(screen.queryAllByRole("status").filter((s) => s.className.includes("loading")).length).toBe(0),
    { timeout: 3000 });
  return container.querySelector("main")!;
}

describe("UI-02 every route under HTTP 500 for all data", () => {
  for (const route of ROUTES) {
    it(`route '${route || "/"}' shows an error state, not a blank page`, async () => {
      stubFetch((m, p) => {
        if (p === "/auth/csrf") return { body: { csrf_token: "tok-qa" } };
        if (m === "GET" && p === "/me") return { body: ME };
        return err(500, "internal_error");
      });
      const main = await settle(route);
      expect(main.textContent!.trim().length).toBeGreaterThan(0);
      expect(main.textContent).not.toMatch(/undefined|NaN|\[object Object\]|TypeError|stack/i);
      expect(pageErrors).toEqual([]);
      if (route !== "#profile") {
        // data screens must surface the failure (role=alert), not silently show zeros
        await waitFor(() => expect(main.querySelectorAll('[role="alert"]').length).toBeGreaterThan(0));
      }
    });
  }
});

const EMPTY: Record<string, unknown> = {
  "GET /activities": { items: [] },
  "GET /timers": { items: [] },
  "GET /chores": { date: "2026-10-06", items: [], summary: { scheduled_total: 0, scheduled_completed: 0, voluntary_completed: 0 } },
  "GET /dashboard": { today: "2026-10-06", timezone: "Europe/Moscow", display_name: "Алексей", balance: 0,
    walk: null, chores: { date: "2026-10-06", items: [], summary: { scheduled_total: 0, scheduled_completed: 0, voluntary_completed: 0 } },
    timers: [], world: { active_world: "settlers", name: "Тихая бухта", level: 0, next_upgrade: { code: "meadow", title: "Поляна", cost: 60 } },
    rewards: { next_evaluation_on: "2026-10-20", preview_total: 0 } },
  "GET /analytics/time": { timezone: "Europe/Moscow", bucket: "week", group_by: "category", from: "2026-09-14", to: "2026-10-11",
    series: [{ key: "lessons", label: "Уроки" }, { key: "walk", label: "Прогулки" }, { key: "other", label: "Другие занятия" }],
    buckets: [], totals: { lessons: 0, walk: 0, other: 0 }, total_seconds: 0 },
  "GET /rewards": { policy_version: 1, mode: "deterministic", rewards_started_on: "2026-10-06", first_evaluation_on: "2026-10-20",
    next_evaluation_on: "2026-10-20", preview: { as_of: "2026-10-06", window: { start: "2026-09-29", end: "2026-10-05" },
      baseline: { start: "2026-09-22", end: "2026-09-28" }, categories: [], total: 0 }, evaluations: [] },
  "GET /wallet": { balance: 0, items: [], next_cursor: null },
  "GET /worlds": { active_world: null, balance: 0, items: [] },
  "GET /world-catalog": { items: [], next_cursor: null },
  "GET /settings": { app: { env: "test", version: "0" }, integrations: {}, rewards: {}, deferred: [] },
  "GET /day-statuses": { items: [] },
};

describe("UI-02 empty data on every route", () => {
  for (const route of ROUTES) {
    it(`route '${route || "/"}' handles empty collections`, async () => {
      stubFetch((m, p) => {
        if (p === "/auth/csrf") return { body: { csrf_token: "tok-qa" } };
        if (m === "GET" && p === "/me") return { body: ME };
        if (m === "POST" && p === "/rewards/evaluate") return { body: { processed: [], balance: 0 } };
        const hit = EMPTY[`${m} ${p}`];
        return hit ? { body: hit } : err(404, "not_found");
      });
      const main = await settle(route);
      expect(main.textContent!.trim().length).toBeGreaterThan(0);
      expect(main.textContent).not.toMatch(/undefined|NaN|\[object Object\]/);
      expect(pageErrors).toEqual([]);
    });
  }
});

describe("UI-08 hostile names are rendered as text", () => {
  it("activity name with HTML does not execute or inject markup", async () => {
    const evil = `<img src=x onerror="window.__qaXss=1">Математика`;
    const math = activity({ name: evil, timer: idleTimer("a-math") });
    stubFetch((m, p) => {
      if (p === "/auth/csrf") return { body: { csrf_token: "tok-qa" } };
      if (p === "/me") return { body: { ...ME, display_name: `<b id="qa-b">Лёша</b>` } };
      if (p === "/activities") return { body: { items: [math] } };
      if (p === "/activities/a-math") return { body: math };
      if (p === "/activities/a-math/entries") return { body: { items: [], next_cursor: null } };
      if (p === "/activities/a-math/daily-totals") return { body: { activity_id: "a-math", points: [] } };
      if (p === "/activities/a-math/timer") return { body: idleTimer("a-math") };
      const hit = EMPTY[`${m} ${p}`];
      return hit ? { body: hit } : err(404, "not_found");
    });
    const main = await settle("#activity/a-math");
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(document.getElementById("qa-b")).toBeNull();
    expect((window as unknown as { __qaXss?: number }).__qaXss).toBeUndefined();
    expect(document.body.textContent).toContain("Математика");
    expect(main).toBeTruthy();
  });
});

describe("UI-05 no credentials in web storage", () => {
  it("storage never holds token-like values after app start", async () => {
    stubFetch((m, p) => (p === "/me" ? { body: ME } : p === "/auth/csrf" ? { body: { csrf_token: "tok-qa" } } : err(500, "x")));
    await settle("#home");
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(dump).not.toMatch(/eyJ|token|refresh|tok-qa/i);
  });
});
