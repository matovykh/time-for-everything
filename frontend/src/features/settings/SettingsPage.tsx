import { useState, type FormEvent } from "react";
import { useMe } from "../../app/session";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { Activity, Objective } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { addDays } from "../../shared/dates";
import { ErrorState, Loading, PageTitle, errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";
import { WEEKDAY_LONG, scheduleName } from "../chores/Chores";

type ScheduleKind = "daily" | "weekdays" | "weekly" | "custom" | "none";

export function weekdaysFor(kind: ScheduleKind, weekly: number, custom: number[]): number[] | null {
  if (kind === "none") return null;
  if (kind === "daily") return [1, 2, 3, 4, 5, 6, 7];
  if (kind === "weekdays") return [1, 2, 3, 4, 5];
  if (kind === "weekly") return [weekly];
  return [...new Set(custom)].sort();
}

const DEFERRED_LABELS: Record<string, string> = {
  admin_connections_write: "Запись подключений сервера (.env) из интерфейса",
  ai_assisted_rewards: "AI-оценка наград",
  signup: "Регистрация",
  password_recovery: "Восстановление пароля",
  guardian_management: "Связывание взрослых и детей",
  wallet_adjustments: "Корректировки кошелька",
  chore_exceptions: "Исключения поручений (отпуск, болезнь)",
};

const INTEGRATION_LABELS: Record<string, string> = {
  database: "База данных PostgreSQL",
  supabase_auth: "Supabase Auth",
  openai: "OpenAI",
};

function ScheduleFields({
  kind,
  setKind,
  weekly,
  setWeekly,
  custom,
  setCustom,
  startsOn,
  setStartsOn,
  endsOn,
  setEndsOn,
  today,
  allowNone,
}: {
  kind: ScheduleKind;
  setKind: (k: ScheduleKind) => void;
  weekly: number;
  setWeekly: (n: number) => void;
  custom: number[];
  setCustom: (d: number[]) => void;
  startsOn: string;
  setStartsOn: (s: string) => void;
  endsOn: string;
  setEndsOn: (s: string) => void;
  today: string;
  allowNone: boolean;
}) {
  return (
    <>
      <label>
        Расписание поручения
        <select value={kind} onChange={(e) => setKind(e.target.value as ScheduleKind)}>
          <option value="daily">Каждый день</option>
          <option value="weekdays">По будням</option>
          <option value="weekly">Раз в неделю</option>
          <option value="custom">Выбранные дни недели</option>
          {allowNone && <option value="none">Без расписания · по желанию</option>}
        </select>
      </label>
      {kind === "weekly" && (
        <label>
          День для «раз в неделю»
          <select value={weekly} onChange={(e) => setWeekly(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6, 7].map((d) => (
              <option key={d} value={d}>
                {WEEKDAY_LONG[d]}
              </option>
            ))}
          </select>
        </label>
      )}
      {kind === "custom" && (
        <fieldset className="weekday-picker">
          <legend>Дни недели</legend>
          {[1, 2, 3, 4, 5, 6, 7].map((d) => (
            <label key={d} className="check-row">
              <input
                type="checkbox"
                checked={custom.includes(d)}
                onChange={(e) => setCustom(e.target.checked ? [...custom, d] : custom.filter((x) => x !== d))}
              />
              {WEEKDAY_LONG[d]}
            </label>
          ))}
        </fieldset>
      )}
      {kind !== "none" && (
        <div className="form-row">
          <label>
            Действует с
            <input type="date" min={today} value={startsOn} onChange={(e) => setStartsOn(e.target.value)} required />
          </label>
          <label>
            До (необязательно)
            <input type="date" min={startsOn} value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
          </label>
        </div>
      )}
    </>
  );
}

export function SettingsPage() {
  const me = useMe();
  const activities = useApi(() => ep.listActivities(true), [me.acting_child_id]);
  const settings = useApi(() => ep.getSettings(), []);
  return (
    <>
      <PageTitle
        title="Настройки приложения"
        subtitle="Занятия, поручения и подключения. Личные данные — в профиле по клику на аватар."
      />
      <div className="settings-grid">
        <div>
          <NewActivityForm onCreated={() => void activities.reload()} />
          <section className="card">
            <h2>Мои занятия и поручения</h2>
            {activities.loading && !activities.data ? (
              <Loading />
            ) : activities.error && !activities.data ? (
              <ErrorState error={activities.error} onRetry={activities.reload} />
            ) : (
              <ActivityManager items={activities.data!.items} onChanged={() => void activities.reload()} />
            )}
          </section>
        </div>
        <div>
          <section className="card">
            <h2>Как начислять награды</h2>
            {settings.loading && !settings.data ? (
              <Loading />
            ) : settings.error && !settings.data ? (
              <ErrorState error={settings.error} onRetry={settings.reload} />
            ) : (
              <>
                <label>
                  Режим
                  <select value={settings.data!.rewards.mode} disabled>
                    <option value="deterministic">По понятным правилам</option>
                    <option value="ai_assisted">AI-оценка в пределах правил</option>
                  </select>
                </label>
                <div className="notice">
                  Сейчас работает расчёт по понятным правилам (версия {settings.data!.rewards.policy_version}).
                  {settings.data!.rewards.ai_available
                    ? " AI-оценка доступна на сервере, но переключение режима появится на следующем этапе."
                    : " AI-оценка — следующий этап: модель будет объяснять результат в пределах правил, а кошелёк останется под контролем сервера."}
                </div>
              </>
            )}
          </section>
          <section className="card">
            <h2>Подключения сервера</h2>
            <p className="muted">Состояние без секретов: сервер сообщает только, настроено подключение или нет.</p>
            {settings.data && (
              <ul className="integration-list">
                {Object.entries(settings.data.integrations).map(([k, v]) => (
                  <li key={k}>
                    <span>{INTEGRATION_LABELS[k] ?? k}</span>
                    <span className={`pill ${v.configured ? "ok" : "off"}`}>{v.configured ? "✓ Настроено" : "Не настроено"}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="fields">
              <label>
                OpenAI API key
                <input type="password" placeholder="••••••••••••••••" disabled autoComplete="off" />
              </label>
              <label>
                Supabase URL
                <input type="password" placeholder="••••••••••••••••" disabled autoComplete="off" />
              </label>
              <label>
                Строка подключения PostgreSQL
                <input type="password" placeholder="••••••••••••••••" disabled autoComplete="off" />
              </label>
              <button disabled>Проверить и сохранить в .env</button>
            </div>
            <small>
              Изменение подключений из интерфейса — следующий этап. Сейчас ключи задаются только в окружении сервера и никогда не
              передаются в браузер.
            </small>
          </section>
          {settings.data && settings.data.deferred.length > 0 && (
            <section className="card">
              <h2>Пока не реализовано</h2>
              <ul className="deferred-list">
                {settings.data.deferred.map((d) => (
                  <li key={d}>{DEFERRED_LABELS[d] ?? d}</li>
                ))}
              </ul>
              <small>Версия приложения: {settings.data.app.version}</small>
            </section>
          )}
        </div>
      </div>
    </>
  );
}

function NewActivityForm({ onCreated }: { onCreated: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [name, setName] = useState("");
  const [type, setType] = useState<"boolean" | "timed">("boolean");
  const [kind, setKind] = useState<ScheduleKind>("daily");
  const [weekly, setWeekly] = useState(5);
  const [custom, setCustom] = useState<number[]>([1, 3, 5]);
  const [startsOn, setStartsOn] = useState(me.today);
  const [endsOn, setEndsOn] = useState("");
  const [objective, setObjective] = useState<Objective>("none");
  const [targetMin, setTargetMin] = useState("20");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) return setError("Введи название.");
    if (trimmed.length > 70) return setError("Название — не длиннее 70 символов.");
    let body: ep.NewActivity;
    if (type === "timed") {
      body = { name: trimmed, kind: "timed", objective };
      if (objective !== "none") {
        const t = Number(targetMin) * 60;
        if (!Number.isInteger(t) || t < 60 || t > 86400) return setError("Цель: от 1 до 1440 минут.");
        body.target_seconds = t;
      }
    } else {
      const days = weekdaysFor(kind, weekly, custom);
      if (days && !days.length) return setError("Выбери хотя бы один день недели.");
      if (days && startsOn < me.today) return setError("Расписание может начаться не раньше сегодняшнего дня.");
      if (days && endsOn && endsOn < startsOn) return setError("Дата окончания раньше даты начала.");
      body = {
        name: trimmed,
        kind: "boolean",
        schedule: days ? { weekdays: days, starts_on: startsOn, ends_on: endsOn || null } : null,
      };
    }
    setBusy(true);
    try {
      await ep.createActivity(body);
      setName("");
      toast(type === "timed" ? "Занятие добавлено! Найди его в разделе «Уроки»." : "Поручение добавлено!");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? (err.fieldErrors[0]?.message ?? errorText(err)) : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Новое занятие или поручение</h2>
      <form className="fields" onSubmit={submit} noValidate>
        <label>
          Название
          <input maxLength={70} placeholder="Например, покормить кота" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Тип
          <select value={type} onChange={(e) => setType(e.target.value as "boolean" | "timed")}>
            <option value="boolean">Поручение · выполнено / нет</option>
            <option value="timed">Занятие · с таймером</option>
          </select>
        </label>
        {type === "boolean" ? (
          <ScheduleFields
            {...{ kind, setKind, weekly, setWeekly, custom, setCustom, startsOn, setStartsOn, endsOn, setEndsOn }}
            today={me.today}
            allowNone
          />
        ) : (
          <>
            <label>
              Цель занятия
              <select value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
                <option value="none">Просто учитывать время</option>
                <option value="reach">Заниматься не меньше цели</option>
                <option value="maintain">Держать примерно на уровне цели</option>
              </select>
            </label>
            {objective !== "none" && (
              <label>
                Цель в минутах за день
                <input type="number" min={1} max={1440} value={targetMin} onChange={(e) => setTargetMin(e.target.value)} />
              </label>
            )}
          </>
        )}
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "Добавляем…" : "Добавить"}
        </button>
      </form>
      <small>
        Занятия и поручения, созданные ребёнком, не влияют на награды. Учитывать их в наградах может решить взрослый.
      </small>
    </section>
  );
}

function ActivityManager({ items, onChanged }: { items: Activity[]; onChanged: () => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  const custom = items.filter((a) => a.code === null);
  const defaults = items.filter((a) => a.code !== null);
  return (
    <>
      {custom.length === 0 && <p className="muted">Своих занятий пока нет — добавь первое в форме выше.</p>}
      <div className="task-list">
        {custom.map((a) =>
          editing === a.id ? (
            <EditActivity key={a.id} activity={a} onDone={(changed) => (setEditing(null), changed && onChanged())} />
          ) : (
            <div key={a.id} className={`task ${a.archived_at ? "archived" : ""}`}>
              <div className="grow">
                <b>
                  {a.icon ? `${a.icon} ` : ""}
                  {a.name}
                </b>
                <small>
                  {a.kind === "timed" ? "Занятие с таймером" : scheduleName(a.schedule)}
                  {a.archived_at ? " · в архиве" : ""}
                </small>
              </div>
              <button className="ghost" onClick={() => setEditing(a.id)}>
                Изменить
              </button>
            </div>
          ),
        )}
      </div>
      {defaults.length > 0 && (
        <details className="chart-data">
          <summary>Стандартные занятия ({defaults.length}) — меняет взрослый</summary>
          <ul className="deferred-list">
            {defaults.map((a) => (
              <li key={a.id}>
                {a.name} · {a.kind === "timed" ? "таймер" : scheduleName(a.schedule)}
                {a.archived_at ? " · в архиве" : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function EditActivity({ activity: a, onDone }: { activity: Activity; onDone: (changed: boolean) => void }) {
  const me = useMe();
  const toast = useToast();
  const s = a.schedule;
  const initialKind: ScheduleKind = !s
    ? "none"
    : s.weekdays.length === 7
      ? "daily"
      : s.weekdays.join() === "1,2,3,4,5"
        ? "weekdays"
        : s.weekdays.length === 1
          ? "weekly"
          : "custom";
  const [name, setName] = useState(a.name);
  const [kind, setKind] = useState<ScheduleKind>(initialKind);
  const [weekly, setWeekly] = useState(s?.weekdays[0] ?? 5);
  const [custom, setCustom] = useState<number[]>(s?.weekdays ?? [1]);
  // A schedule change applies from a chosen date ≥ today (past days keep old rules).
  const [startsOn, setStartsOn] = useState(s && s.starts_on > me.today ? s.starts_on : addDays(me.today, 1));
  const [endsOn, setEndsOn] = useState(s?.ends_on ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: Parameters<typeof ep.patchActivity>[1] = { revision: a.revision };
    if (name.trim() !== a.name) body.name = name.trim();
    if (a.kind === "boolean") {
      const days = weekdaysFor(kind, weekly, custom);
      const changed = JSON.stringify(days) !== JSON.stringify(s?.weekdays ?? null) || (endsOn || null) !== (s?.ends_on ?? null);
      if (changed) {
        if (!days) return setError("Отменить расписание у существующего поручения сейчас нельзя — можно отправить его в архив.");
        if (!days.length) return setError("Выбери хотя бы один день недели.");
        if (startsOn < me.today) return setError("Изменение действует с сегодняшнего или будущего дня.");
        body.schedule = { weekdays: days, starts_on: startsOn, ends_on: endsOn || null };
      }
    }
    if (Object.keys(body).length === 1) return onDone(false);
    setBusy(true);
    try {
      await ep.patchActivity(a.id, body);
      toast("Сохранено");
      onDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast("Занятие изменилось на другом устройстве. Обновили список.");
        onDone(true);
      } else if (err instanceof ApiError && err.status === 403) setError("Это может изменить только взрослый.");
      else setError(err instanceof ApiError ? (err.fieldErrors[0]?.message ?? errorText(err)) : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive() {
    setBusy(true);
    try {
      await ep.patchActivity(a.id, { revision: a.revision, archived: !a.archived_at });
      toast(a.archived_at ? "Возвращено из архива" : "В архиве. История сохранена.");
      onDone(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="fields edit-activity" onSubmit={save}>
      <label>
        Название
        <input maxLength={70} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      {a.kind === "boolean" && (
        <ScheduleFields
          {...{ kind, setKind, weekly, setWeekly, custom, setCustom, startsOn, setStartsOn, endsOn, setEndsOn }}
          today={me.today}
          allowNone={!s}
        />
      )}
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="inline-actions">
        <button className="primary" disabled={busy}>
          Сохранить
        </button>
        <button type="button" className="ghost" onClick={() => onDone(false)} disabled={busy}>
          Отмена
        </button>
        <button type="button" className="ghost" onClick={toggleArchive} disabled={busy}>
          {a.archived_at ? "Вернуть из архива" : "В архив"}
        </button>
      </div>
    </form>
  );
}
