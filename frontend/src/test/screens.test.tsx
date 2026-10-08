import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { ProgressLine } from "../shared/charts/Charts";
import { TimerPanel } from "../features/timers/TimerPanel";
import { ToastProvider } from "../shared/ui/Toast";
import { setActingChild } from "../shared/api/client";
import { ME, activity, apiError, idleTimer, mockApi } from "./mockApi";

beforeEach(() => {
  vi.unstubAllGlobals();
  setActingChild(null);
  sessionStorage.clear();
  localStorage.clear();
  location.hash = "";
  document.cookie = "tfe_csrf=tok-1; path=/";
});

const csrf = { "GET /auth/csrf": () => ({ body: { csrf_token: "tok-1" } }) };

describe("auth and setup", () => {
  it("shows the login screen without a session and signs in through the backend", async () => {
    const { calls } = mockApi({
      ...csrf,
      "GET /me": () => apiError(401, "not_authenticated"),
      "POST /auth/refresh": () => apiError(401, "session_expired"),
      "POST /auth/login": () => ({ body: { me: ME, csrf_token: "tok-2" } }),
      "POST /rewards/evaluate": () => ({ body: { processed: [], balance: 0 } }),
      "GET /dashboard": () => new Promise(() => {}) as never,
      "GET /activities": () => new Promise(() => {}) as never,
      "GET /analytics/time": () => new Promise(() => {}) as never,
    });
    render(<App />);
    const email = await screen.findByLabelText("Электронная почта");
    await userEvent.type(email, "child@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await screen.findByText("Собираем твой день…");
    const login = calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toEqual({ email: "child@example.com", password: "secret" });
    expect(login.headers["X-CSRF-Token"]).toBe("tok-1");
    expect(JSON.stringify(localStorage)).not.toContain("secret");
    // Wallet starts at the real server balance, never a demo amount.
    await waitFor(() => expect(screen.getByLabelText("Баланс: 0 звёзд")).toBeInTheDocument());
  });

  it("shows a neutral error for wrong credentials", async () => {
    mockApi({
      ...csrf,
      "GET /me": () => apiError(401, "not_authenticated"),
      "POST /auth/refresh": () => apiError(401, "session_expired"),
      "POST /auth/login": () => apiError(401, "invalid_credentials"),
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Электронная почта"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Пароль"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверная почта или пароль.");
  });

  it("shows setup guidance when the backend is not configured", async () => {
    mockApi({
      ...csrf,
      "GET /me": () => apiError(503, "service_not_configured", { details: { missing: ["DATABASE_URL", "SUPABASE_URL"] } }),
      "GET /health/ready": () => ({
        status: 503,
        body: { status: "not_ready", checks: { database: "not_configured" }, setup: ["Задайте DATABASE_URL"] },
      }),
    });
    render(<App />);
    expect(await screen.findByText("Приложение ещё настраивается")).toBeInTheDocument();
    expect(screen.getByText("DATABASE_URL, SUPABASE_URL")).toBeInTheDocument();
    expect(screen.getByText("Задайте DATABASE_URL")).toBeInTheDocument();
  });
});

describe("unconfigured backend", () => {
  it("shows setup guidance instead of an unusable login when /me is 401 but not ready", async () => {
    mockApi({
      ...csrf,
      "GET /me": () => apiError(401, "not_authenticated"),
      "POST /auth/refresh": () => apiError(401, "session_expired"),
      "GET /health/ready": () => ({
        status: 503,
        body: {
          status: "not_ready",
          checks: { database: "not_configured", auth: "not_configured" },
          setup: ["Задайте SUPABASE_URL и SUPABASE_PUBLISHABLE_KEY"],
        },
      }),
    });
    render(<App />);
    expect(await screen.findByText("Приложение ещё настраивается")).toBeInTheDocument();
    expect(screen.getByText("Задайте SUPABASE_URL и SUPABASE_PUBLISHABLE_KEY")).toBeInTheDocument();
    expect(screen.queryByLabelText("Пароль")).not.toBeInTheDocument();
  });
});

describe("progress line", () => {
  it("lists every recorded date in order and never fills gaps with zeros", () => {
    render(
      <ProgressLine
        mode="light"
        points={[
          { date: "2026-10-05", minutes: 30, entries: 2 },
          { date: "2025-01-10", minutes: 15, entries: 1 },
          { date: "2026-06-01", minutes: 45, entries: 1 },
        ]}
      />,
    );
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.firstElementChild!.textContent)).toEqual(["10.01.2025", "01.06.2026", "05.10.2026"]);
    expect(rows).toHaveLength(3);
  });
});

describe("timer panel", () => {
  it("starts with revision + idempotency key and warns about other running timers", async () => {
    const { calls } = mockApi({
      "POST /activities/a-math/timer/start": () => ({
        body: {
          timer: { ...idleTimer("a-math", 1), state: "running", running_since: "2026-10-06T09:00:00Z", started_on: "2026-10-06" },
          other_running: [{ activity_id: "a-rus", name: "Русский язык", elapsed_ms: 900000 }],
        },
      }),
    });
    render(
      <ToastProvider>
        <TimerPanel activity={activity() as never} today="2026-10-06" onSaved={() => {}} />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Начать/ }));
    expect(await screen.findByText(/Сейчас идут и другие таймеры/)).toBeInTheDocument();
    expect(screen.getByText(/Русский язык · 00:15:00/)).toBeInTheDocument();
    expect(calls[0].body).toEqual({ revision: 0 });
    expect(calls[0].headers["Idempotency-Key"]).toBeTruthy();
    expect(screen.getByRole("button", { name: /Пауза/ })).toBeInTheDocument();
  });

  it("adopts the server state on a revision conflict instead of double-applying", async () => {
    mockApi({
      "POST /activities/a-math/timer/start": () =>
        apiError(409, "revision_conflict", {
          details: { current: { ...idleTimer("a-math", 5), state: "paused", elapsed_ms: 600000, accumulated_ms: 600000, started_on: "2026-10-06" } },
        }),
    });
    render(
      <ToastProvider>
        <TimerPanel activity={activity() as never} today="2026-10-06" onSaved={() => {}} />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Начать/ }));
    expect(await screen.findByText("00:10:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Продолжить/ })).toBeInTheDocument();
  });

  it("saves to the chosen date and requires correction for >24h sessions", async () => {
    const paused = {
      ...idleTimer("a-math", 4),
      state: "paused",
      elapsed_ms: 25 * 3600_000,
      accumulated_ms: 25 * 3600_000,
      started_on: "2026-10-05",
      long_session: "correct",
    };
    const { calls } = mockApi({
      "POST /activities/a-math/timer/save": () => ({
        status: 201,
        body: { timer: idleTimer("a-math", 5), entry: { activity_date: "2026-10-05", duration_seconds: 2700 } },
      }),
    });
    const onSaved = vi.fn();
    render(
      <ToastProvider>
        <TimerPanel activity={activity({ timer: paused }) as never} today="2026-10-06" onSaved={onSaved} />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Сохранить/ }));
    await userEvent.click(screen.getByRole("button", { name: /Записать время/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Укажи реальное время");
    await userEvent.type(screen.getByLabelText("Минуты"), "45");
    await userEvent.click(screen.getByRole("button", { name: /Записать время/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(calls[0].body).toMatchObject({ revision: 4, activity_date: "2026-10-05", duration_seconds: 2700 });
  });
});

describe("theme", () => {
  it("switches light/dark/system with aria-pressed on the login screen", async () => {
    mockApi({ ...csrf, "GET /me": () => apiError(401, "not_authenticated"), "POST /auth/refresh": () => apiError(401, "session_expired") });
    render(<App />);
    const dark = await screen.findByRole("button", { name: "Тёмная тема" });
    await act(async () => userEvent.click(dark));
    expect(dark).toHaveAttribute("aria-pressed", "true");
    expect(document.body.dataset.theme).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Светлая тема" }));
    expect(document.body.dataset.theme).toBe("light");
  });
});
