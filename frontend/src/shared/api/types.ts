// Types mirror docs/API.md (contract v1). Do not add fields the backend does not send.

export type Role = "child" | "guardian" | "admin";
export type ThemeChoice = "light" | "dark" | "system";

export interface Me {
  id: string;
  email: string;
  display_name: string;
  grade: string | null;
  timezone: string;
  theme: ThemeChoice;
  role: Role;
  active_world: string;
  onboarding_version: number;
  rewards_started_on: string;
  today: string;
  acting_child_id: string;
  children: { id: string; display_name: string }[];
  permissions: {
    can_confirm_quality: boolean;
    can_manage_rewards_settings: boolean;
    is_admin: boolean;
    /** Added after QA (backend me_dict); optional so an older backend degrades to "not allowed". */
    can_edit_timezone?: boolean;
    can_set_workload?: boolean;
    can_delete_reviewed_entries?: boolean;
  };
}

export interface Schedule {
  weekdays: number[]; // ISO 1=Mon … 7=Sun
  starts_on: string;
  ends_on: string | null;
}

export type TimerStateName = "idle" | "running" | "paused";

export interface TimerState {
  activity_id: string;
  state: TimerStateName;
  accumulated_ms: number;
  running_since: string | null;
  elapsed_ms: number;
  session_started_at: string | null;
  started_on: string | null;
  long_session: "none" | "confirm" | "correct";
  revision: number;
  server_now: string;
}

export type ActivityKind = "timed" | "boolean";
export type ActivityCategory = "lesson" | "walk" | "reading" | "custom" | "chore";
export type Objective = "decrease" | "reach" | "maintain" | "none";

export interface Activity {
  id: string;
  code: string | null;
  name: string;
  icon: string | null;
  kind: ActivityKind;
  category: ActivityCategory;
  objective: Objective;
  target_seconds: number | null;
  sort_order: number;
  reward_eligible: boolean;
  archived_at: string | null;
  schedule: Schedule | null;
  revision: number;
  created_at: string;
  updated_at: string;
  timer: TimerState | null;
}

export type Workload = "normal" | "increased" | "excluded";
export type QualityStatus = "pending" | "confirmed" | "rejected" | "not_required";

export interface TimeEntry {
  id: string;
  activity_id: string;
  activity_date: string;
  duration_seconds: number;
  source: "timer" | "manual";
  quality_status: QualityStatus;
  workload: Workload;
  note: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface DailyTotals {
  activity_id: string;
  points: { date: string; seconds: number; entries: number }[];
}

export interface ChoreItem {
  activity_id: string;
  code: string | null;
  name: string;
  icon: string | null;
  date: string;
  scheduled: boolean;
  voluntary: boolean;
  due: boolean;
  completed: boolean;
  completed_at: string | null;
  reward_eligible: boolean;
  schedule: Schedule | null;
}

export interface ChoreSummary {
  scheduled_total: number;
  scheduled_completed: number;
  voluntary_completed: number;
}

export interface ChoresResponse {
  date: string;
  items: ChoreItem[];
  summary: ChoreSummary;
}

export interface NextUpgrade {
  code: string;
  title: string;
  cost: number;
}

export interface Dashboard {
  today: string;
  timezone: string;
  display_name: string;
  balance: number;
  walk: { activity_id: string; today_seconds: number; target_seconds: number } | null;
  chores: ChoresResponse;
  timers: TimerState[];
  world: {
    active_world: string | null;
    name: string | null;
    level: number;
    next_upgrade: NextUpgrade | null;
  };
  rewards: { next_evaluation_on: string | null; preview_total: number | null };
}

export interface AnalyticsBucket {
  start: string;
  end: string;
  complete: boolean;
  totals: Record<string, number>;
  total_seconds: number;
}

export interface Analytics {
  timezone: string;
  bucket: "week" | "day";
  group_by: "category" | "activity";
  from: string;
  to: string;
  series: { key: string; label: string }[];
  buckets: AnalyticsBucket[];
  totals: Record<string, number>;
  total_seconds: number;
}

export type RewardCategory = "lessons" | "walk" | "chores";
export type RewardStatus = "eligible" | "no_reward" | "insufficient_data" | "awaiting_data";

export interface LessonSubjectFacts {
  activity_id: string;
  name: string;
  status: string;
  baseline_days: number;
  current_days: number;
  baseline_median_seconds: number | null;
  current_median_seconds: number | null;
  progress_percent: number | null;
  amount: number;
}

export interface CategoryResult {
  category: RewardCategory;
  status: RewardStatus;
  amount: number;
  reason_code: string;
  explanation: string;
  facts: Record<string, unknown> & {
    subjects?: LessonSubjectFacts[];
    cap?: number;
    target_seconds?: number;
    included_days?: number;
    recorded_days?: number;
    goal_days?: number;
    required_goal_days?: number;
    mean_ratio?: number | null;
    baseline_mean_ratio?: number | null;
    missing_dates?: string[];
    scheduled?: number;
    completed?: number;
    completion_days?: number;
    required_days?: number;
  };
  state?: "final" | "deferred";
  evaluated_at?: string;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface RewardsResponse {
  policy_version: number;
  mode: "deterministic" | "ai_assisted";
  rewards_started_on: string;
  first_evaluation_on: string;
  next_evaluation_on: string;
  preview: {
    as_of: string;
    window: DateRange;
    baseline: DateRange;
    categories: CategoryResult[];
    total: number;
  } | null;
  evaluations: {
    period_end: string;
    window: DateRange;
    baseline: DateRange;
    categories: CategoryResult[];
    total_awarded: number;
  }[];
}

export interface EvaluateResponse {
  processed: { period_end: string; category: RewardCategory; state: string; amount: number }[];
  balance: number;
}

export interface WalletItem {
  id: string;
  amount: number;
  balance_after: number;
  reason_code: string;
  description: string;
  source_type: string | null;
  source_id: string | null;
  period_end: string | null;
  created_at: string;
}

export interface WalletResponse extends Page<WalletItem> {
  balance: number;
}

export interface WorldTheme {
  code: string;
  name: string;
  type: string;
  badge: string;
  color: string;
  resource: string;
  inhabitants_label: string;
  upgrades_total: number;
}

export interface CatalogWorld extends WorldTheme {
  in_collection: boolean;
  level: number;
}

export interface CollectionWorld extends WorldTheme {
  position: number;
  added_at: string;
  level: number;
  unlocked: string[];
  next_upgrade: NextUpgrade | null;
}

export interface WorldsResponse {
  active_world: string;
  balance: number;
  items: CollectionWorld[];
}

export type BlockedReason = null | "already_owned" | "prerequisite_missing" | "insufficient_balance";

export interface WorldUpgrade {
  code: string;
  index: number;
  title: string;
  effect: string;
  kind: string;
  space: string;
  cost: number;
  requires: string | null;
  owned: boolean;
  purchased_at: string | null;
  can_purchase: boolean;
  blocked_reason: BlockedReason;
}

export interface WorldDetail {
  theme: WorldTheme;
  level: number;
  territories: number;
  inhabitants: number;
  balance: number;
  upgrades: WorldUpgrade[];
  events: {
    id: string;
    upgrade_code: string;
    event_type: string;
    text: string;
    created_at: string;
  }[];
}

export interface PurchaseResponse {
  purchase: {
    id: string;
    upgrade_code: string;
    cost: number;
    purchased_at: string;
    transaction_id: string;
  };
  balance: number;
  world: WorldDetail;
}

export interface SettingsResponse {
  app: { env: string; version: string };
  integrations: Record<string, { configured: boolean }>;
  rewards: { policy_version: number; mode: string; ai_available: boolean };
  deferred: string[];
}

export interface HealthReady {
  status: "ready" | "not_ready";
  checks: Record<string, string>;
  setup: string[];
}

export interface FieldError {
  field: string;
  code: string;
  message: string;
}
