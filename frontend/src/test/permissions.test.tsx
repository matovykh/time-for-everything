import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { ManualEntryForm } from "../features/time-entries/EntryForm";
import { HistoryTable } from "../features/time-entries/HistoryTable";
import { TimerPanel } from "../features/timers/TimerPanel";
import { setActingChild } from "../shared/api/client";
import type { TimeEntry } from "../shared/api/types";
import { ToastProvider } from "../shared/ui/Toast";
import { ME, activity, apiError, idleTimer, mockApi } from "./mockApi";

beforeEach(() => {
  vi.unstubAllGlobals();
  setActingChild(null);
  sessionStorage.clear();
  localStorage.clear();
  location.hash = "";
  document.cookie = "tfe_csrf=tok-1; path=/";
});

const childPerms = { canConfirmQuality: false, canSetWorkload: false, canEditTimezone: false, canDeleteReviewed: false };
const adultPerms = { canConfirmQuality: true, canSetWorkload: true, canEditTimezone: true, canDeleteReviewed: true };

const entry = (over: Partial<TimeEntry> = {}): TimeEntry => ({
  id: "e1",
  activity_id: "a-math",
  activity_date: "2026-10-05",
  duration_seconds: 1500,
  source: "manual",
  quality_status: "confirmed",
  workload: "normal",
  note: "",
  revision: 2,
  created_at: "",
  updated_at: "",
  ...over,
});

const wrap = (ui: React.ReactNode) => render(<ToastProvider>{ui}</ToastProvider>);

describe("workload is an adult's decision", () => {
  it("child: no workload control and no workload in the manual entry body", async () => {
    const { calls } = mockApi({ "POST /activities/a-math/entries": () => ({ status: 201, body: entry({ quality_status: "pending" }) }) });
    wrap(<ManualEntryForm activity={activity() as never} today="2026-10-06" onCreated={() => {}} canSetWorkload={false} />);
    expect(screen.queryByLabelText("Объём домашнего задания")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Минуты"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Добавить запись" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ activity_date: "2026-10-06", duration_seconds: 1500, note: "" });
  });

  it("adult: workload control is shown and sent", async () => {
    const { calls } = mockApi({ "POST /activities/a-math/entries": () => ({ status: 201, body: entry() }) });
    wrap(<ManualEntryForm activity={activity() as never} today="2026-10-06" onCreated={() => {}} canSetWorkload />);
    await userEvent.selectOptions(screen.getByLabelText("Объём домашнего задания"), "increased");
    await userEvent.type(screen.getByLabelText("Минуты"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Добавить запись" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ workload: "increased" });
  });

  it("child: timer save omits workload", async () => {
    const paused = { ...idleTimer("a-math", 2), state: "paused", elapsed_ms: 600000, accumulated_ms: 600000, started_on: "2026-10-06" };
    const { calls } = mockApi({
      "POST /activities/a-math/timer/save": () => ({ status: 201, body: { timer: idleTimer("a-math", 3), entry: entry({ activity_date: "2026-10-06" }) } }),
    });
    wrap(<TimerPanel activity={activity({ timer: paused }) as never} today="2026-10-06" onSaved={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Сохранить/ }));
    expect(screen.queryByLabelText("Объём домашнего задания")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Записать время/ }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).not.toHaveProperty("workload");
  });
});

describe("reviewed entries", () => {
  const table = (perms: typeof childPerms, e = entry()) =>
    wrap(
      <HistoryTable
        activity={activity() as never}
        entries={[e]}
        totalCount={1}
        hasMore={false}
        loadingMore={false}
        onLoadMore={() => {}}
        onChanged={() => {}}
        today="2026-10-06"
        permissions={perms}
      />,
    );

  it("child cannot delete a confirmed entry and may edit only its note", async () => {
    const { calls } = mockApi({ "PATCH /entries/e1": () => ({ body: entry({ note: "ok" }) }) });
    table(childPerms);
    expect(screen.queryByRole("button", { name: /Удалить запись/ })).not.toBeInTheDocument();
    expect(screen.getByText("Удаляет взрослый")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Изменить запись/ }));
    expect(screen.getByLabelText("Дата")).toBeDisabled();
    expect(screen.getByLabelText("Минуты")).toBeDisabled();
    expect(screen.queryByLabelText("Объём")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Заметка"), "ok");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ revision: 2, note: "ok" });
  });

  it("child can still fully edit and delete a pending entry", async () => {
    table(childPerms, entry({ quality_status: "pending" }));
    expect(screen.getByRole("button", { name: /Удалить запись/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Изменить запись/ }));
    expect(screen.getByLabelText("Дата")).toBeEnabled();
  });

  it("adult can delete reviewed entries and set workload", async () => {
    table(adultPerms);
    expect(screen.getByRole("button", { name: /Удалить запись/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Изменить запись/ }));
    expect(screen.getByLabelText("Объём")).toBeInTheDocument();
    expect(screen.getByLabelText("Дата")).toBeEnabled();
  });
});

const signedIn = (me = ME) => ({
  "GET /auth/csrf": () => ({ body: { csrf_token: "tok-1" } }),
  "GET /me": () => ({ body: me }),
  "POST /rewards/evaluate": () => ({ body: { processed: [], balance: 10 } }),
});

describe("profile and sign-out", () => {
  it("locks the timezone for a child and never sends it", async () => {
    location.hash = "#profile";
    const { calls } = mockApi({ ...signedIn(), "PATCH /me": () => ({ body: ME }) });
    render(<App />);
    const tz = await screen.findByLabelText("Часовой пояс профиля");
    expect(tz).toBeDisabled();
    expect(screen.getByText(/Часовой пояс меняет взрослый/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Сохранить профиль" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).not.toHaveProperty("timezone");
  });

  it("allows timezone changes with can_edit_timezone", async () => {
    location.hash = "#profile";
    mockApi(signedIn({ ...ME, permissions: { ...ME.permissions, can_edit_timezone: true } } as typeof ME));
    render(<App />);
    expect(await screen.findByLabelText("Часовой пояс профиля")).toBeEnabled();
  });

  it("leaves the app and warns when logout is incomplete (503 logout_incomplete)", async () => {
    location.hash = "#profile";
    mockApi({
      ...signedIn(),
      "POST /auth/logout": () =>
        apiError(503, "logout_incomplete", { message: "Выход на этом устройстве выполнен, но сервер не смог завершить сессию." }),
    });
    sessionStorage.setItem("vse-uspeyu-acting-child", "c1");
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Выйти/ }));
    expect(await screen.findByText("До нового открытия!")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("сервер не смог завершить сессию");
    expect(screen.queryByLabelText("Часовой пояс профиля")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("vse-uspeyu-acting-child")).toBeNull();
    expect(location.hash).toBe("");
  });

  it("offers to retry when the logout request cannot reach the server", async () => {
    location.hash = "#profile";
    mockApi({ ...signedIn(), "POST /auth/logout": () => Promise.reject(new TypeError("offline")) });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Выйти/ }));
    expect(await screen.findByRole("button", { name: "Повторить выход" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("выход может быть не завершён");
  });
});
