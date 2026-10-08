import type { Activity, TimerState } from "../../shared/api/types";
import { clock } from "../../shared/dates";
import { useMe } from "../../app/session";
import * as ep from "../../shared/api/endpoints";
import { useApi } from "../../shared/api/useApi";
import { Empty, ErrorState, Loading, PageTitle } from "../../shared/ui/States";
import { activityHref } from "./ActivityDetail";

function timerLabel(t: TimerState | null | undefined) {
  if (!t || t.state === "idle") return "Открыть таймер →";
  if (t.state === "running") return "● Таймер идёт";
  return `На паузе · ${clock(t.elapsed_ms)} не сохранено`;
}

export function ActivityTiles({ activities, timers }: { activities: Activity[]; timers?: TimerState[] }) {
  const byId = new Map((timers ?? []).map((t) => [t.activity_id, t]));
  if (!activities.length) return <Empty>Пока нет занятий. Добавь своё в настройках.</Empty>;
  return (
    <div className="lesson-grid">
      {activities.map((a) => {
        const t = byId.get(a.id) ?? a.timer;
        return (
          <a key={a.id} className={`lesson ${t && t.state !== "idle" ? "has-timer" : ""}`} href={activityHref(a)}>
            <span className="icon" aria-hidden="true">
              {a.icon ?? "◷"}
            </span>
            <span>
              {a.name}
              <small>{timerLabel(t)}</small>
            </span>
          </a>
        );
      })}
    </div>
  );
}

export function LessonsPage() {
  const me = useMe();
  const list = useApi(() => ep.listActivities(false), [me.acting_child_id]);
  const timed = (list.data?.items ?? []).filter((a) => a.kind === "timed");
  const lessons = timed.filter((a) => a.category === "lesson");
  const other = timed.filter((a) => a.category === "reading" || a.category === "custom");
  return (
    <>
      <PageTitle title="Мои занятия" subtitle="Выбери урок или занятие, чтобы включить его таймер" />
      {list.loading && !list.data ? (
        <Loading />
      ) : list.error && !list.data ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : (
        <>
          <section className="card">
            <div className="section-head">
              <h2>Уроки</h2>
            </div>
            <ActivityTiles activities={lessons} />
          </section>
          <section className="card" style={{ marginTop: 22 }}>
            <div className="section-head">
              <h2>Другие занятия</h2>
              <a className="text-button" href="#settings">
                + Добавить занятие
              </a>
            </div>
            <ActivityTiles activities={other} />
          </section>
        </>
      )}
    </>
  );
}
