import { useEffect, useState } from "react";
import { useMe, useSession } from "../../app/session";
import { useResolvedTheme } from "../../app/theme";
import { useTour } from "../../app/tour";
import * as ep from "../../shared/api/endpoints";
import type { Dashboard } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { TimeDonut, WeekStackChart } from "../../shared/charts/Charts";
import { fmt, plural, ruDate, ruLongToday } from "../../shared/dates";
import { Icon } from "../../shared/ui/Icon";
import { ErrorState, Loading, PageTitle } from "../../shared/ui/States";
import { ActivityTiles } from "../activities/ActivityTiles";
import { ChoreChecklist } from "../chores/Chores";
import { WorldScene } from "../world/WorldArt";
import { toCharts } from "./analytics";

export function HomePage() {
  const me = useMe();
  const { setBalance } = useSession();
  const dash = useApi(() => ep.getDashboard(), [me.acting_child_id]);
  const activities = useApi(() => ep.listActivities(true), [me.acting_child_id]);

  useEffect(() => {
    if (dash.data) setBalance(dash.data.balance);
  }, [dash.data, setBalance]);

  if (dash.loading && !dash.data) return <Loading label="Собираем твой день…" />;
  if (dash.error && !dash.data) return <ErrorState error={dash.error} onRetry={dash.reload} />;
  const d = dash.data!;
  const timed = (activities.data?.items ?? []).filter((a) => a.kind === "timed" && !a.archived_at);
  const walkTimer = d.timers.find((t) => t.activity_id === d.walk?.activity_id);

  return (
    <>
      <PageTitle
        title={`Привет, ${d.display_name || me.display_name}!`}
        subtitle="Сегодня — ещё один шаг к большим открытиям"
        aside={<span className="date">{ruLongToday(d.timezone)}</span>}
      />
      <Hero dash={d} />
      <section className="stats" aria-label="Сегодняшние показатели">
        <div className="card stat">
          <span className="icon" aria-hidden="true">
            ✦
          </span>
          <div>
            <div className="stat-label">Предварительно за неделю</div>
            <div className="stat-value">
              {d.rewards.preview_total === null ? "—" : `+${d.rewards.preview_total}`} <small>✦</small>
            </div>
            <small>
              Ещё не начислено
              {d.rewards.next_evaluation_on ? ` · оценка ${ruDate(d.rewards.next_evaluation_on)}` : ""}
            </small>
          </div>
        </div>
        <div className="card stat">
          <span className="icon teal" aria-hidden="true">
            ☀
          </span>
          <div>
            <div className="stat-label">Прогулка сегодня</div>
            {d.walk ? (
              <>
                <div className="stat-value">
                  {fmt(d.walk.today_seconds / 60)} <small>/ {fmt(d.walk.target_seconds / 60)} мин</small>
                </div>
                <small>
                  {d.walk.today_seconds >= d.walk.target_seconds
                    ? "Цель достигнута. Отличная прогулка!"
                    : walkTimer && walkTimer.state === "running"
                      ? "Таймер прогулки идёт"
                      : "Время для воздуха и новых открытий"}
                </small>
              </>
            ) : (
              <div className="stat-value">—</div>
            )}
          </div>
        </div>
        <div className="card stat">
          <span className="icon gold" aria-hidden="true">
            ✓
          </span>
          <div>
            <div className="stat-label">Дела на сегодня</div>
            <div className="stat-value">
              {d.chores.summary.scheduled_completed} <small>из {d.chores.summary.scheduled_total}</small>
            </div>
            <small>
              {d.chores.summary.voluntary_completed
                ? `+ ${d.chores.summary.voluntary_completed} добровольных`
                : "Маленькие дела становятся привычками"}
            </small>
          </div>
        </div>
      </section>
      <div className="grid">
        <section className="card">
          <div className="section-head">
            <h2>Мои дела на сегодня</h2>
            <a className="text-button" href="#chores">
              Все поручения →
            </a>
          </div>
          <ChoreChecklist data={d.chores} editable onlyDue onChange={() => void dash.reload()} />
        </section>
        <section className="card">
          <div className="section-head">
            <h2>Пора позаниматься?</h2>
            <small>Выбери занятие</small>
          </div>
          {activities.error && !activities.data ? (
            <ErrorState error={activities.error} onRetry={activities.reload} />
          ) : activities.loading && !activities.data ? (
            <Loading />
          ) : (
            <ActivityTiles activities={timed.filter((a) => a.category !== "walk")} timers={d.timers} />
          )}
          <div className="walk-strip">
            <div>
              <b>☀ А потом — на прогулку!</b>
              <br />
              <small>
                {walkTimer && walkTimer.state !== "idle"
                  ? walkTimer.state === "running"
                    ? "Таймер прогулки идёт"
                    : "Прогулка на паузе"
                  : d.walk
                    ? `Твоя цель — ${fmt(d.walk.target_seconds / 60)} минут на свежем воздухе`
                    : "Свежий воздух помогает отдохнуть"}
              </small>
            </div>
            <a className="button-link" href="#walk" aria-label="Открыть таймер прогулки">
              →
            </a>
          </div>
        </section>
      </div>
      <TimeCharts />
      <section className="card">
        <div className="section-head">
          <h2>Есть чем гордиться</h2>
          <a className="text-button" href="#rewards">
            Мои награды →
          </a>
        </div>
        <div className="achievement">
          <span className="icon gold" aria-hidden="true">
            ✦
          </span>
          <div>
            <h3>Шаг за шагом — к новым островам</h3>
            <p>
              {d.rewards.preview_total
                ? "Предварительный расчёт по прошедшим 7 дням. Звёзды придут после оценки периода."
                : "Пока знакомимся с твоим ритмом. Записывай время и отмечай дела — первая оценка придёт по расписанию."}
              {d.rewards.next_evaluation_on && ` Следующая оценка: ${ruDate(d.rewards.next_evaluation_on)}.`}
            </p>
          </div>
          <span>{d.rewards.preview_total ? `≈ +${d.rewards.preview_total} ✦` : "—"}</span>
        </div>
      </section>
    </>
  );
}

function Hero({ dash }: { dash: Dashboard }) {
  const { balance } = useSession();
  const openTour = useTour();
  const w = dash.world;
  const next = w.next_upgrade;
  const have = balance ?? dash.balance;
  return (
    <section className="hero living-hero">
      <div className="hero-copy">
        <span className="tag">{(w.name ?? "Твой остров").toUpperCase()} · ТВОЙ ЖИВОЙ МИР</span>
        <h2>
          Маленькие старания.
          <br />
          Большая жизнь.
        </h2>
        <p>
          {w.level
            ? `На острове уже ${w.level} из 4 открытий. Жители заняты новыми делами — загляни к ним.`
            : "Два друга у костра, а за туманом — неизведанные земли. Твои звёзды помогут им открыть новый мир."}
        </p>
        <a className="button-link gold" href="#world">
          На мой остров <Icon name="arrow" size={18} />
        </a>
        <button className="hero-tour" onClick={() => openTour()}>
          Как оживает мир?
        </button>
        <div className="hero-progress">
          <span>{next ? `Следом: ${next.title}` : "Все открытия этого острова — твои!"}</span>
          {next && (
            <>
              <progress value={Math.min(have, next.cost)} max={next.cost} aria-label="Звёзды до следующего открытия" />
              <span>
                {have} / {next.cost} ✦
              </span>
            </>
          )}
        </div>
      </div>
      <WorldScene code={w.active_world ?? "settlers"} level={w.level} motion={false} />
    </section>
  );
}

const WEEK_OPTIONS = [4, 8, 12] as const;

function TimeCharts() {
  const me = useMe();
  const mode = useResolvedTheme();
  const [weeks, setWeeks] = useState<number>(4);
  const [groupBy, setGroupBy] = useState<"category" | "activity">("category");
  const data = useApi(() => ep.getWeeklyAnalytics(weeks, groupBy), [weeks, groupBy, me.acting_child_id]);
  const catalogue = useApi(() => ep.listActivities(true), [me.acting_child_id]);
  const charts = data.data ? toCharts(data.data, mode, catalogue.data?.items ?? []) : null;

  const filters = (
    <div className="chart-filters">
      <div className="segmented" role="group" aria-label="Период">
        {WEEK_OPTIONS.map((n) => (
          <button key={n} aria-pressed={weeks === n} onClick={() => setWeeks(n)}>
            {n} нед.
          </button>
        ))}
      </div>
      <div className="segmented" role="group" aria-label="Группировка">
        <button aria-pressed={groupBy === "category"} onClick={() => setGroupBy("category")}>
          Категории
        </button>
        <button aria-pressed={groupBy === "activity"} onClick={() => setGroupBy("activity")}>
          Предметы
        </button>
      </div>
    </div>
  );

  return (
    <>
      {filters}
      <div className="grid">
        <section className="card">
          <div className="section-head">
            <h2>Как проходит моё время</h2>
            <span className="pill">{weeks} {plural(weeks, ["неделя", "недели", "недель"])} · пн–вс</span>
          </div>
          {data.loading && !data.data ? (
            <Loading />
          ) : data.error && !data.data ? (
            <ErrorState error={data.error} onRetry={data.reload} />
          ) : charts && data.data!.total_seconds > 0 ? (
            <WeekStackChart weeks={charts.weeks} series={charts.series} />
          ) : (
            <p className="empty">Здесь появятся недели, когда ты запишешь первое время.</p>
          )}
        </section>
        <section className="card">
          <div className="section-head">
            <h2>Баланс занятий</h2>
            <span className="pill">{weeks} {plural(weeks, ["неделя", "недели", "недель"])}</span>
          </div>
          {data.loading && !data.data ? (
            <Loading />
          ) : data.error && !data.data ? (
            <ErrorState error={data.error} onRetry={data.reload} />
          ) : charts ? (
            <TimeDonut slices={charts.slices} subLabel={`минут за ${weeks} нед.`} />
          ) : null}
          <small>Только записанное время, а не весь день</small>
        </section>
      </div>
    </>
  );
}
