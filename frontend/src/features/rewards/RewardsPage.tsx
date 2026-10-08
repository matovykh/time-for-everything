import { useEffect, useState } from "react";
import { useMe, useSession } from "../../app/session";
import * as ep from "../../shared/api/endpoints";
import type { CategoryResult, DateRange, RewardStatus, WalletItem } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { duration, ruDate, ruDateTime } from "../../shared/dates";
import { Empty, ErrorState, Loading, PageTitle, errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";

const CATEGORY_META: Record<string, { icon: string; title: string }> = {
  lessons: { icon: "↗", title: "Уроки" },
  walk: { icon: "☀", title: "Прогулки" },
  chores: { icon: "✓", title: "Поручения" },
};

const STATUS_LABEL: Record<RewardStatus, string> = {
  eligible: "Есть результат",
  no_reward: "Пока без звёзд",
  insufficient_data: "Пока знакомимся с твоим ритмом",
  awaiting_data: "Ждём данные",
};

const REASON_LABEL: Record<string, string> = {
  reward_lessons: "Награда за уроки",
  reward_walk: "Награда за прогулки",
  reward_chores: "Награда за поручения",
  world_purchase: "Открытие в мире",
  adjustment: "Корректировка взрослым",
};

const range = (r: DateRange) => `${ruDate(r.start)} – ${ruDate(r.end)}`;

export function RewardsPage() {
  const me = useMe();
  const { setBalance, balance } = useSession();
  const rewards = useApi(() => ep.getRewards(), [me.acting_child_id]);

  return (
    <>
      <PageTitle title="Твои маленькие победы" subtitle="Звёзды за привычки, которые остаются с тобой" />
      {rewards.loading && !rewards.data ? (
        <Loading />
      ) : rewards.error && !rewards.data ? (
        <ErrorState error={rewards.error} onRetry={rewards.reload} />
      ) : (
        (() => {
          const r = rewards.data!;
          const p = r.preview;
          return (
            <>
              <div className="stats">
                <div className="card">
                  <small>Можно потратить</small>
                  <div className="stat-value">{balance ?? "—"} ✦</div>
                </div>
                <div className="card">
                  <small>Предварительно за последние 7 дней</small>
                  <div className="stat-value">{p ? `≈ +${p.total} ✦` : "—"}</div>
                  <small>Не добавляется к балансу до оценки</small>
                </div>
                <div className="card">
                  <small>Следующая оценка</small>
                  <div className="stat-value">{ruDate(r.next_evaluation_on)}</div>
                  <small>
                    {r.first_evaluation_on === r.next_evaluation_on
                      ? "Первая оценка — после 14 дней наблюдения"
                      : "Оценка проходит раз в 7 дней"}
                  </small>
                </div>
              </div>
              <div className="grid">
                <section className="card">
                  <h2>За что приходят звёзды</h2>
                  {p ? (
                    <>
                      <p className="muted">
                        Предварительный расчёт на {ruDate(p.as_of)}: окно {range(p.window)}, сравниваем с {range(p.baseline)}.
                        Сегодняшний день не учитывается — он ещё не закончился.
                      </p>
                      {p.categories.map((c) => (
                        <CategoryCard key={c.category} result={c} onChanged={rewards.reload} />
                      ))}
                    </>
                  ) : (
                    <Empty>Пока знакомимся с твоим ритмом. Предварительный расчёт появится, когда накопятся записи.</Empty>
                  )}
                  <p className="notice">
                    Нет улучшения времени уроков — нет звёзд за скорость. Но награды за прогулки и поручения остаются доступными.
                  </p>
                </section>
                <section className="card">
                  <h2>Как считаются звёзды</h2>
                  <p>
                    Правила одинаковые и понятные: сервер сравнивает два окна по 7 завершённых дней. Расчёт идёт
                    {r.mode === "deterministic" ? " по фиксированным правилам" : " с помощью AI в пределах правил"} (версия {r.policy_version}).
                  </p>
                  <ul className="rules">
                    <li>Уроки: только подтверждённые взрослым дни обычного объёма; минимум 3 дня в каждом окне.</li>
                    <li>Прогулки: цель достигнута в 5 из 7 дней — 40 звёзд; заметный рост — 20.</li>
                    <li>Поручения: от 60% выполненных запланированных дел, максимум 40 звёзд.</li>
                  </ul>
                  <p className="muted">
                    Письмо хранителя острова с AI-объяснением появится на следующем этапе. Сейчас объяснения — шаблонные и
                    одинаково понятные.
                  </p>
                  <a className="button-link gold" href="#world">
                    Потратить звёзды →
                  </a>
                </section>
              </div>
              {r.evaluations.length > 0 && (
                <section className="card" style={{ marginBottom: 22 }}>
                  <h2>Итоги прошлых периодов</h2>
                  <ul className="period-list">
                    {r.evaluations.map((ev) => (
                      <li key={ev.period_end} className="period-card">
                        <div className="period-head">
                          <b>{range(ev.window)}</b>
                          <span className="period-total">+{ev.total_awarded} ✦</span>
                        </div>
                        <div className="period-cats">
                          {(["lessons", "walk", "chores"] as const).map((cat) => {
                            const c = ev.categories.find((x) => x.category === cat);
                            return (
                              <span key={cat} className="pill">
                                {CATEGORY_META[cat].title}:{" "}
                                {c ? `${c.amount ? `+${c.amount} ✦` : "0"}${c.state === "deferred" ? " · ждёт данных" : ""}` : "—"}
                              </span>
                            );
                          })}
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          );
        })()
      )}
      <WalletLedger onBalance={setBalance} />
    </>
  );
}

function CategoryCard({ result: c, onChanged }: { result: CategoryResult; onChanged: () => void }) {
  const meta = CATEGORY_META[c.category] ?? { icon: "✦", title: c.category };
  const subjects = c.facts.subjects ?? [];
  const missing = c.facts.missing_dates ?? [];
  return (
    <div className={`achievement reward-${c.status}`}>
      <span className="icon" aria-hidden="true">
        {meta.icon}
      </span>
      <div>
        <h3>
          {meta.title} · <span className="status-text">{STATUS_LABEL[c.status] ?? c.status}</span>
        </h3>
        <p>{c.explanation}</p>
        {c.category === "lessons" && subjects.length > 0 && (
          <details>
            <summary>По предметам</summary>
            <ul className="facts">
              {subjects.map((s) => (
                <li key={s.activity_id}>
                  {s.name}: {s.baseline_median_seconds !== null ? duration(s.baseline_median_seconds) : "—"} →{" "}
                  {s.current_median_seconds !== null ? duration(s.current_median_seconds) : "—"}
                  {s.progress_percent !== null ? ` (${s.progress_percent > 0 ? "−" : "+"}${Math.abs(Math.round(s.progress_percent))}%)` : ""} · дней{" "}
                  {s.baseline_days}/{s.current_days}
                  {s.amount ? ` · +${s.amount} ✦` : ""}
                </li>
              ))}
            </ul>
          </details>
        )}
        {c.category === "walk" && typeof c.facts.goal_days === "number" && (
          <p className="facts">
            Цель достигнута в {c.facts.goal_days} из {c.facts.included_days ?? 0} учтённых дней
            {c.facts.required_goal_days ? ` (нужно ${c.facts.required_goal_days})` : ""}.
          </p>
        )}
        {c.category === "chores" && typeof c.facts.scheduled === "number" && (
          <p className="facts">
            Выполнено {c.facts.completed ?? 0} из {c.facts.scheduled}; дней с отметками: {c.facts.completion_days ?? 0}
            {c.facts.required_days ? ` (нужно ${c.facts.required_days})` : ""}.
          </p>
        )}
        {c.category === "walk" && missing.length > 0 && <MissingWalkDays dates={missing} onChanged={onChanged} />}
      </div>
      <span>{c.amount ? `+${c.amount} ✦` : "0 ✦"}</span>
    </div>
  );
}

function MissingWalkDays({ dates, onChanged }: { dates: string[]; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  async function mark(date: string) {
    setBusy(date);
    try {
      await ep.setWalkStatus(date, "no_walk");
      toast(`${ruDate(date)}: отмечено «без прогулки».`);
      onChanged();
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="missing-days">
      <small>
        Нет данных о прогулке за эти дни. Если прогулки не было — отметь это, а если была — добавь время на странице «Прогулка».
      </small>
      <ul>
        {dates.map((d) => (
          <li key={d}>
            {ruDate(d)}{" "}
            <button className="text-button" disabled={busy === d} onClick={() => mark(d)}>
              Не гулял
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WalletLedger({ onBalance }: { onBalance: (b: number) => void }) {
  const me = useMe();
  const [items, setItems] = useState<WalletItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<{ loading: boolean; error: unknown }>({ loading: true, error: null });

  async function load(from: string | null, reset: boolean) {
    setState({ loading: true, error: null });
    try {
      const page = await ep.getWallet(from);
      setItems((prev) => (reset ? page.items : [...prev, ...page.items]));
      setCursor(page.next_cursor);
      onBalance(page.balance);
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }

  useEffect(() => {
    void load(null, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.acting_child_id]);

  return (
    <section className="card">
      <h2>История кошелька</h2>
      {state.error && !items.length ? (
        <ErrorState error={state.error} onRetry={() => load(null, true)} />
      ) : state.loading && !items.length ? (
        <Loading />
      ) : !items.length ? (
        <Empty>Пока звёзд не было. Они появятся после первой оценки периода — а потратить их можно в «Моём мире».</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Событие</th>
                <th>Звёзды</th>
                <th>Баланс после</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td>{ruDateTime(i.created_at)}</td>
                  <td className="wrap-cell">
                    {i.description || REASON_LABEL[i.reason_code] || i.reason_code}
                    {i.period_end ? <small> · период до {ruDate(i.period_end)}</small> : null}
                  </td>
                  <td className={i.amount >= 0 ? "positive" : ""}>
                    {i.amount >= 0 ? "+" : "−"}
                    {Math.abs(i.amount)} ✦
                  </td>
                  <td>{i.balance_after} ✦</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cursor && (
        <button className="ghost load-more" disabled={state.loading} onClick={() => load(cursor, false)}>
          {state.loading ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </section>
  );
}
