import { useCallback, useEffect, useState } from "react";
import { navigate } from "../../app/router";
import { useMe } from "../../app/session";
import { useResolvedTheme } from "../../app/theme";
import * as ep from "../../shared/api/endpoints";
import type { Activity, DailyTotals, TimeEntry } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { ProgressLine } from "../../shared/charts/Charts";
import { duration, fmt, ruLongToday } from "../../shared/dates";
import { Empty, ErrorState, Loading, PageTitle } from "../../shared/ui/States";
import { TimerPanel } from "../timers/TimerPanel";
import { ManualEntryForm } from "../time-entries/EntryForm";
import { HistoryTable } from "../time-entries/HistoryTable";
import { permissionsOf } from "../../shared/permissions";

const PAGE = 100;

export function activityHref(a: Activity) {
  return a.category === "walk" ? "#walk" : `#activity/${encodeURIComponent(a.id)}`;
}

/** Loads the timed activity catalogue for the tab row; `id` may be null (walk). */
export function ActivityDetailPage({ id, walk = false }: { id?: string; walk?: boolean }) {
  const me = useMe();
  const list = useApi(() => ep.listActivities(false), [me.acting_child_id]);
  const timed = (list.data?.items ?? []).filter((a) => a.kind === "timed");
  const resolvedId = walk ? timed.find((a) => a.category === "walk")?.id : id;

  if (list.loading && !list.data) return <Loading />;
  if (list.error && !list.data) return <ErrorState error={list.error} onRetry={list.reload} />;
  if (!resolvedId)
    return (
      <>
        <PageTitle title={walk ? "Прогулка" : "Занятие"} />
        <Empty>{walk ? "Занятие «Прогулка» не найдено. Возможно, оно в архиве — его можно вернуть в настройках." : "Такого занятия нет."}</Empty>
      </>
    );
  return <ActivityDetail key={resolvedId} id={resolvedId} siblings={timed} />;
}

function ActivityDetail({ id, siblings }: { id: string; siblings: Activity[] }) {
  const me = useMe();
  const mode = useResolvedTheme();
  const activity = useApi(() => ep.getActivity(id), [id]);
  const totals = useApi<DailyTotals>(() => ep.getDailyTotals(id), [id]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [entriesState, setEntriesState] = useState<{ loading: boolean; error: unknown }>({ loading: true, error: null });

  const loadEntries = useCallback(
    async (reset: boolean, from: string | null = null) => {
      setEntriesState({ loading: true, error: null });
      try {
        const page = await ep.listEntries(id, reset ? null : from, PAGE);
        setEntries((prev) => (reset ? page.items : [...prev, ...page.items]));
        setCursor(page.next_cursor);
        setEntriesState({ loading: false, error: null });
      } catch (e) {
        setEntriesState({ loading: false, error: e });
      }
    },
    [id],
  );

  useEffect(() => {
    void loadEntries(true);
  }, [loadEntries]);

  const refreshData = useCallback(() => {
    void totals.reload();
    void loadEntries(true);
  }, [totals, loadEntries]);

  if (activity.loading && !activity.data) return <Loading />;
  if (activity.error && !activity.data) return <ErrorState error={activity.error} onRetry={activity.reload} />;
  const a = activity.data!;
  if (a.kind !== "timed")
    return (
      <>
        <PageTitle title={a.name} />
        <Empty>Это поручение отмечается галочкой в разделе «Поручения».</Empty>
      </>
    );

  const points = (totals.data?.points ?? []).map((p) => ({ date: p.date, minutes: p.seconds / 60, entries: p.entries }));
  const totalCount = totals.data ? totals.data.points.reduce((s, p) => s + p.entries, 0) : null;
  const todaySeconds = totals.data?.points.find((p) => p.date === me.today)?.seconds ?? 0;
  const isWalk = a.category === "walk";
  const perms = permissionsOf(me);

  return (
    <>
      <PageTitle
        title={
          <>
            {a.icon ? `${a.icon} ` : ""}
            {a.name}
          </>
        }
        subtitle={a.category === "lesson" ? "Не торопись: понять важнее, чем закончить первым." : "Время для того, что важно тебе"}
        aside={<span className="date">{ruLongToday(me.timezone)}</span>}
      />
      <div className="tab-row" role="navigation" aria-label="Другие занятия">
        <button onClick={() => navigate({ page: "home" })}>← Мой день</button>
        {siblings.map((s) => (
          <button
            key={s.id}
            className={s.id === a.id ? "selected" : ""}
            aria-current={s.id === a.id ? "page" : undefined}
            onClick={() => (location.hash = activityHref(s))}
          >
            {s.name}
          </button>
        ))}
      </div>
      {a.archived_at && <div className="notice">Занятие в архиве. История сохранена.</div>}
      {isWalk && a.target_seconds ? (
        <section className="card walk-goal" aria-label="Цель прогулки на сегодня">
          <div className="stats">
            <div>
              <div className="stat-label">Цель на день</div>
              <div className="stat-value">{fmt(a.target_seconds / 60)} мин</div>
            </div>
            <div>
              <div className="stat-label">Сегодня записано</div>
              <div className="stat-value">{fmt(todaySeconds / 60)} мин</div>
            </div>
            <div>
              <div className="stat-label">{todaySeconds >= a.target_seconds ? "Цель достигнута" : "Осталось до цели"}</div>
              <div className="stat-value">
                {todaySeconds >= a.target_seconds ? "✓" : `${fmt((a.target_seconds - todaySeconds) / 60)} мин`}
              </div>
            </div>
          </div>
          <progress value={Math.min(todaySeconds, a.target_seconds)} max={a.target_seconds} aria-label="Прогресс прогулки" />
          <small>Гулять дольше цели — здорово, но звёзды за это не умножаются. Время таймера учитывается после сохранения.</small>
        </section>
      ) : null}
      <div className="grid">
        <TimerPanel activity={a} today={me.today} onSaved={refreshData} canSetWorkload={perms.canSetWorkload} />
        <ManualEntryForm activity={a} today={me.today} onCreated={refreshData} canSetWorkload={perms.canSetWorkload} />
      </div>
      <section className="card">
        <div className="section-head">
          <h2>Мой прогресс</h2>
          <span className="pill">За всё время</span>
        </div>
        {totals.loading && !totals.data ? (
          <Loading />
        ) : totals.error && !totals.data ? (
          <ErrorState error={totals.error} onRetry={totals.reload} />
        ) : (
          <ProgressLine points={points} mode={mode} />
        )}
        <small>
          Показана вся история. Записи за день суммируются; даты без занятий не считаются нулями. Линия последовательно
          соединяет все записанные даты.
          {points.length > 0 && ` Всего: ${duration(points.reduce((s, p) => s + p.minutes * 60, 0))}.`}
        </small>
      </section>
      <div style={{ marginTop: 22 }}>
        {entriesState.error && entries.length === 0 ? (
          <section className="card">
            <ErrorState error={entriesState.error} onRetry={() => loadEntries(true)} title="Не удалось загрузить историю" />
          </section>
        ) : entriesState.loading && entries.length === 0 ? (
          <section className="card">
            <Loading label="Загружаем историю…" />
          </section>
        ) : (
          <HistoryTable
            activity={a}
            entries={entries}
            totalCount={totalCount}
            hasMore={Boolean(cursor)}
            loadingMore={entriesState.loading}
            onLoadMore={() => loadEntries(false, cursor)}
            onChanged={refreshData}
            today={me.today}
            permissions={perms}
          />
        )}
      </div>
    </>
  );
}
