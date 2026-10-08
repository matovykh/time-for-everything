import { api, command, request, setCsrfToken, ensureCsrf } from "./client";
import type {
  Activity,
  Analytics,
  ChoreItem,
  ChoresResponse,
  CatalogWorld,
  CollectionWorld,
  DailyTotals,
  Dashboard,
  EvaluateResponse,
  HealthReady,
  Me,
  Objective,
  Page,
  PurchaseResponse,
  QualityStatus,
  RewardsResponse,
  Schedule,
  SettingsResponse,
  ThemeChoice,
  TimeEntry,
  TimerState,
  WalletResponse,
  Workload,
  WorldDetail,
  WorldsResponse,
} from "./types";

const enc = encodeURIComponent;

// ── Health / auth / profile ───────────────────────────────────────────
export const getReady = async (): Promise<HealthReady | null> => {
  // 503 still carries the HealthReady shape; read it without the error path.
  try {
    const res = await fetch("/api/v1/health/ready", { credentials: "same-origin" });
    const body = (await res.json()) as HealthReady;
    return body && (body.status === "ready" || body.status === "not_ready") ? body : null;
  } catch {
    return null;
  }
};

export async function login(email: string, password: string): Promise<Me> {
  await ensureCsrf();
  const res = await request<{ me: Me; csrf_token: string }>("POST", "/auth/login", {
    body: { email, password },
  });
  setCsrfToken(res.csrf_token);
  return res.me;
}

export const logout = () =>
  request<void>("POST", "/auth/logout", { body: { pause_running_timers: true } });

export const getMe = () => api.get<Me>("/me");

export const patchMe = (body: Partial<{
  display_name: string;
  grade: string | null;
  timezone: string;
  theme: ThemeChoice;
  onboarding_version: number;
}>) => api.patch<Me>("/me", body);

export const setActiveWorld = (theme_code: string) =>
  api.put<{ active_world: string }>("/me/active-world", { theme_code });

// ── Activities & timers ───────────────────────────────────────────────
export const listActivities = (includeArchived = false) =>
  api.get<{ items: Activity[] }>("/activities", { include_archived: includeArchived });

export const getActivity = (id: string) => api.get<Activity>(`/activities/${enc(id)}`);

export interface NewActivity {
  name: string;
  kind: "timed" | "boolean";
  icon?: string | null;
  objective?: Objective;
  target_seconds?: number;
  schedule?: { weekdays: number[]; starts_on: string; ends_on?: string | null } | null;
}
export const createActivity = (body: NewActivity) => api.post<Activity>("/activities", body);

export const patchActivity = (
  id: string,
  body: { revision: number } & Partial<{
    name: string;
    icon: string | null;
    sort_order: number;
    objective: Objective;
    target_seconds: number | null;
    archived: boolean;
    schedule: Omit<Schedule, "ends_on"> & { ends_on?: string | null };
    reward_eligible: boolean;
  }>,
) => api.patch<Activity>(`/activities/${enc(id)}`, body);

export const listTimers = () => api.get<{ items: TimerState[] }>("/timers");
export const getTimer = (activityId: string) =>
  api.get<TimerState>(`/activities/${enc(activityId)}/timer`);

export interface TimerCommandResult {
  timer: TimerState;
  other_running: { activity_id: string; name: string; elapsed_ms: number }[];
}
export const timerCommand = (
  activityId: string,
  cmd: "start" | "pause" | "reset",
  revision: number,
) =>
  command<TimerCommandResult>("POST", `/activities/${enc(activityId)}/timer/${cmd}`, {
    body: { revision },
  });

export interface SaveTimerBody {
  revision: number;
  activity_date: string;
  confirm_long_session: boolean;
  duration_seconds: number | null;
  note: string;
  /** Only sent by adults (can_set_workload); the server defaults to "normal". */
  workload?: Workload;
}
export const saveTimer = (activityId: string, body: SaveTimerBody) =>
  command<{ timer: TimerState; entry: TimeEntry }>(
    "POST",
    `/activities/${enc(activityId)}/timer/save`,
    { body },
  );

// ── Entries ───────────────────────────────────────────────────────────
export const listEntries = (activityId: string, cursor?: string | null, limit = 100) =>
  api.get<Page<TimeEntry>>(`/activities/${enc(activityId)}/entries`, { limit, cursor });

export const getDailyTotals = (activityId: string) =>
  api.get<DailyTotals>(`/activities/${enc(activityId)}/daily-totals`);

export const createEntry = (
  activityId: string,
  body: { activity_date: string; duration_seconds: number; note: string; workload?: Workload },
) =>
  command<TimeEntry>("POST", `/activities/${enc(activityId)}/entries`, { body });

export const patchEntry = (
  id: string,
  body: { revision: number } & Partial<{
    activity_date: string;
    duration_seconds: number;
    note: string;
    workload: Workload;
  }>,
) => api.patch<TimeEntry>(`/entries/${enc(id)}`, body);

export const deleteEntry = (id: string, revision: number) =>
  api.del<void>(`/entries/${enc(id)}`, { revision });

export const setEntryQuality = (id: string, revision: number, quality_status: QualityStatus) =>
  api.put<TimeEntry>(`/entries/${enc(id)}/quality`, { revision, quality_status });

// ── Chores & day statuses ─────────────────────────────────────────────
export const getChores = (date?: string) => api.get<ChoresResponse>("/chores", { date });
export const setChoreCompletion = (activityId: string, date: string, completed: boolean) =>
  api.put<ChoreItem>(`/chores/${enc(activityId)}/completions/${enc(date)}`, { completed });

export const getWalkStatuses = (from: string, to: string) =>
  api.get<{ items: { date: string; status: string }[] }>("/day-statuses", {
    category: "walk",
    from,
    to,
  });
export const setWalkStatus = (date: string, status: "no_walk" | "excluded" | null) =>
  api.put<{ date: string; status: string | null }>(`/day-statuses/walk/${enc(date)}`, { status });

// ── Dashboard, analytics, rewards, wallet ─────────────────────────────
export const getDashboard = () => api.get<Dashboard>("/dashboard");
export const getWeeklyAnalytics = (weeks: number, groupBy: "category" | "activity") =>
  api.get<Analytics>("/analytics/time", { bucket: "week", group_by: groupBy, weeks });
export const getRewards = () => api.get<RewardsResponse>("/rewards");
export const evaluateRewards = () => api.post<EvaluateResponse>("/rewards/evaluate");
export const getWallet = (cursor?: string | null, limit = 50) =>
  api.get<WalletResponse>("/wallet", { limit, cursor });

// ── Worlds ────────────────────────────────────────────────────────────
export const getWorlds = () => api.get<WorldsResponse>("/worlds");
export const getWorld = (code: string) => api.get<WorldDetail>(`/worlds/${enc(code)}`);
export const searchCatalog = (search: string, cursor?: string | null) =>
  api.get<Page<CatalogWorld>>("/world-catalog", { search, cursor });
export const addWorld = (theme_code: string) =>
  api.post<{ item: CollectionWorld; created: boolean }>("/worlds", { theme_code });
export const purchaseUpgrade = (code: string, upgrade_code: string) =>
  command<PurchaseResponse>("POST", `/worlds/${enc(code)}/purchases`, {
    body: { upgrade_code },
  });

// ── Settings ──────────────────────────────────────────────────────────
export const getSettings = () => api.get<SettingsResponse>("/settings");
