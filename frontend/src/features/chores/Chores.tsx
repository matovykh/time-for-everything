import { useState } from "react";
import { useMe } from "../../app/session";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { Activity, ChoreItem, ChoresResponse, Schedule } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { addDays, ruDate, ruShortDate, weekStart } from "../../shared/dates";
import { Empty, ErrorState, Loading, PageTitle, errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";

export const WEEKDAY_SHORT = ["", "пн", "вт", "ср", "чт", "пт", "сб", "вс"];
export const WEEKDAY_LONG = ["", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

export function scheduleName(s: Schedule | null): string {
  if (!s) return "Без расписания · по желанию";
  const days = [...s.weekdays].sort();
  let base: string;
  if (days.length === 7) base = "Каждый день";
  else if (days.join() === "1,2,3,4,5") base = "По будням";
  else if (days.join() === "6,7") base = "По выходным";
  else if (days.length === 1) base = `Раз в неделю · ${WEEKDAY_SHORT[days[0]]}`;
  else base = days.map((d) => WEEKDAY_SHORT[d]).join(", ");
  const extra = [
    s.starts_on ? `с ${ruDate(s.starts_on)}` : "",
    s.ends_on ? `по ${ruDate(s.ends_on)}` : "",
  ].filter(Boolean);
  return extra.length ? `${base} · ${extra.join(" ")}` : base;
}

function pill(item: ChoreItem) {
  if (!item.due) return "Не сегодня";
  if (item.completed) return "Готово ✓";
  if (item.voluntary) return "Доброе дело";
  return "На сегодня";
}

/**
 * Checklist for one date. `editable` = the child may toggle (only today);
 * the server enforces the same rule (422 date_not_allowed).
 */
export function ChoreChecklist({
  data,
  editable,
  onChange,
  onlyDue = false,
}: {
  data: ChoresResponse;
  editable: boolean;
  onChange: (item: ChoreItem) => void;
  onlyDue?: boolean;
}) {
  const toast = useToast();
  const [pending, setPending] = useState<string | null>(null);
  const items = onlyDue ? data.items.filter((i) => i.due) : data.items;

  async function toggle(item: ChoreItem, completed: boolean) {
    setPending(item.activity_id);
    try {
      const updated = await ep.setChoreCompletion(item.activity_id, data.date, completed);
      onChange(updated);
      toast(completed ? "Дело сделано. Здорово!" : "Отметка отменена");
    } catch (e) {
      const map: Record<string, string> = {
        date_not_allowed: "Отметить можно только сегодняшние дела.",
        not_scheduled: "Это дело сегодня не запланировано.",
        activity_archived: "Поручение в архиве.",
      };
      toast(e instanceof ApiError ? (map[e.code] ?? errorText(e)) : errorText(e));
    } finally {
      setPending(null);
    }
  }

  if (!items.length) return <Empty>{onlyDue ? "На сегодня поручений нет. Можно отдохнуть!" : "Поручений нет."}</Empty>;
  return (
    <div className="task-list">
      {items.map((c) => {
        const id = `chore-${data.date}-${c.activity_id}`;
        return (
          <div key={c.activity_id} className={`task ${c.completed ? "done" : ""} ${c.voluntary ? "voluntary" : ""}`}>
            <input
              type="checkbox"
              id={id}
              checked={c.completed}
              disabled={!editable || !c.due || pending === c.activity_id}
              onChange={(e) => toggle(c, e.target.checked)}
            />
            <label htmlFor={id}>
              <b>{c.name}</b>
              <small>
                {scheduleName(c.schedule)}
                {c.voluntary ? " · не влияет на обязательный процент" : ""}
              </small>
            </label>
            <span className="pill">{pill(c)}</span>
          </div>
        );
      })}
    </div>
  );
}

type Tab = "today" | "week" | "all";

export function ChoresPage() {
  const me = useMe();
  const [tab, setTab] = useState<Tab>("today");
  return (
    <>
      <PageTitle title="Мои поручения" subtitle="Забота о себе и помощь другим — тоже достижения" />
      <div className="tab-row" role="tablist" aria-label="Период">
        {(
          [
            ["today", "Сегодня"],
            ["week", "Неделя"],
            ["all", "Все"],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "selected" : ""} onClick={() => setTab(t)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "today" && <TodayTab today={me.today} />}
      {tab === "week" && <WeekTab today={me.today} />}
      {tab === "all" && <AllTab />}
      <div className="notice">
        Отметка сохраняется за сегодняшний день. Звёзды за регулярность появятся после оценки недели. Дела без расписания
        отмечаются не более одного раза в день и не приносят звёзд сразу.
      </div>
      <a href="#settings" className="button-link primary">
        + Добавить поручение
      </a>
    </>
  );
}

function TodayTab({ today }: { today: string }) {
  const chores = useApi(() => ep.getChores(today), [today]);
  return (
    <section className="card">
      <div className="section-head">
        <h2>Сегодня и по расписанию</h2>
        {chores.data && (
          <span className="pill">
            {chores.data.summary.scheduled_completed} из {chores.data.summary.scheduled_total} обязательных
          </span>
        )}
      </div>
      {chores.loading && !chores.data ? (
        <Loading />
      ) : chores.error && !chores.data ? (
        <ErrorState error={chores.error} onRetry={chores.reload} />
      ) : (
        <ChoreChecklist data={chores.data!} editable onChange={() => void chores.reload()} />
      )}
    </section>
  );
}

function WeekTab({ today }: { today: string }) {
  const start = weekStart(today);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const week = useApi(() => Promise.all(days.map((d) => ep.getChores(d))), [start]);
  if (week.loading && !week.data) return <Loading />;
  if (week.error && !week.data) return <ErrorState error={week.error} onRetry={week.reload} />;
  return (
    <div className="week-chores">
      {week.data!.map((d, i) => (
        <section key={d.date} className={`card ${d.date === today ? "is-today" : ""}`}>
          <div className="section-head">
            <h2>
              {WEEKDAY_LONG[i + 1]}, {ruShortDate(d.date)}
            </h2>
            <span className="pill">
              {d.date > today
                ? "Впереди"
                : `${d.summary.scheduled_completed} из ${d.summary.scheduled_total}`}
            </span>
          </div>
          <ChoreChecklist
            data={{ ...d, items: d.items.filter((x) => x.scheduled || (x.voluntary && x.completed)) }}
            editable={d.date === today}
            onChange={() => void week.reload()}
          />
        </section>
      ))}
    </div>
  );
}

function AllTab() {
  const me = useMe();
  const toast = useToast();
  const list = useApi(() => ep.listActivities(true), [me.acting_child_id]);
  const chores = (list.data?.items ?? []).filter((a) => a.kind === "boolean");

  async function archive(a: Activity, archived: boolean) {
    try {
      await ep.patchActivity(a.id, { revision: a.revision, archived });
      toast(archived ? "Поручение в архиве. История сохранена." : "Поручение возвращено.");
    } catch (e) {
      toast(
        e instanceof ApiError && e.status === 403
          ? "Это поручение может изменить только взрослый."
          : e instanceof ApiError && e.status === 409
            ? "Поручение уже изменилось. Обновили список."
            : errorText(e),
      );
    }
    void list.reload();
  }

  if (list.loading && !list.data) return <Loading />;
  if (list.error && !list.data) return <ErrorState error={list.error} onRetry={list.reload} />;
  if (!chores.length) return <Empty>Поручений пока нет.</Empty>;
  return (
    <section className="card">
      <div className="task-list">
        {chores.map((c) => (
          <div key={c.id} className={`task ${c.archived_at ? "archived" : ""}`}>
            <div className="grow">
              <b>{c.name}</b>
              <small>
                {scheduleName(c.schedule)}
                {c.reward_eligible ? " · учитывается в наградах" : ""}
              </small>
            </div>
            {c.archived_at ? <span className="pill">В архиве</span> : null}
            <button className="ghost" onClick={() => archive(c, !c.archived_at)}>
              {c.archived_at ? "Вернуть" : "В архив"}
            </button>
          </div>
        ))}
      </div>
      <small>Поручения по умолчанию и те, что учитываются в наградах, меняет взрослый. Расписание редактируется в настройках.</small>
    </section>
  );
}
