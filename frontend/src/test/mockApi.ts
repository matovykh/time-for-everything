import { vi } from "vitest";

export interface Call {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body?: unknown; headers?: Record<string, string> } | Promise<never>;

/** Routes "METHOD /path" (query stripped) to handlers; records every call. */
export function mockApi(routes: Record<string, Handler | Handler[]>) {
  const calls: Call[] = [];
  const counters: Record<string, number> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const headers = Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>));
    const call: Call = { method, path: path + url.search, headers, body: init.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const key = `${method} ${path}`;
    const entry = routes[key];
    if (!entry) return json(404, { code: "not_found", message: `no mock for ${key}`, field_errors: [], request_id: "t" });
    const list = Array.isArray(entry) ? entry : [entry];
    const i = Math.min(counters[key] ?? 0, list.length - 1);
    counters[key] = (counters[key] ?? 0) + 1;
    const res = await list[i](call);
    return json(res.status ?? 200, res.body, res.headers);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(status === 204 || body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export const apiError = (status: number, code: string, extra: Record<string, unknown> = {}) => ({
  status,
  body: { code, message: code, field_errors: [], request_id: "req-1", details: null, ...extra },
});

export const ME = {
  id: "u1",
  email: "child@example.com",
  display_name: "Алексей",
  grade: "3",
  timezone: "Europe/Moscow",
  theme: "system",
  role: "child",
  active_world: "settlers",
  onboarding_version: 1,
  rewards_started_on: "2026-10-01",
  today: "2026-10-06",
  acting_child_id: "u1",
  children: [],
  permissions: { can_confirm_quality: false, can_manage_rewards_settings: false, is_admin: false },
};

export const idleTimer = (activity_id: string, revision = 0) => ({
  activity_id,
  state: "idle",
  accumulated_ms: 0,
  running_since: null,
  elapsed_ms: 0,
  session_started_at: null,
  started_on: null,
  long_session: "none",
  revision,
  server_now: "2026-10-06T09:00:00.000Z",
});

export const activity = (over: Record<string, unknown> = {}) => ({
  id: "a-math",
  code: "math",
  name: "Математика",
  icon: "∑",
  kind: "timed",
  category: "lesson",
  objective: "decrease",
  target_seconds: null,
  sort_order: 10,
  reward_eligible: true,
  archived_at: null,
  schedule: null,
  revision: 1,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  timer: idleTimer("a-math"),
  ...over,
});
