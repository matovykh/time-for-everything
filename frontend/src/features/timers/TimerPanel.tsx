import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { Activity, TimeEntry, TimerState, Workload } from "../../shared/api/types";
import { addDays, clock, dayNumber, ruDate } from "../../shared/dates";
import { useToast } from "../../shared/ui/Toast";
import { errorText } from "../../shared/ui/States";
import { WORKLOAD_LABELS } from "../time-entries/labels";

const FOUR_HOURS = 4 * 3600_000;
const DAY = 24 * 3600_000;

interface Synced {
  timer: TimerState;
  receivedAt: number;
}

export function liveElapsed(s: Synced, now = Date.now()): number {
  return s.timer.state === "running" ? s.timer.elapsed_ms + Math.max(0, now - s.receivedAt) : s.timer.elapsed_ms;
}

const idleTimer = (activityId: string): TimerState => ({
  activity_id: activityId,
  state: "idle",
  accumulated_ms: 0,
  running_since: null,
  elapsed_ms: 0,
  session_started_at: null,
  started_on: null,
  long_session: "none",
  revision: 0,
  server_now: new Date().toISOString(),
});

export function TimerPanel({
  activity,
  today,
  onSaved,
  canSetWorkload = false,
}: {
  activity: Activity;
  today: string;
  onSaved: (entry: TimeEntry) => void;
  canSetWorkload?: boolean;
}) {
  const toast = useToast();
  const [synced, setSynced] = useState<Synced>(() => ({
    timer: activity.timer ?? idleTimer(activity.id),
    receivedAt: Date.now(),
  }));
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState<string | null>(null);
  const [others, setOthers] = useState<ep.TimerCommandResult["other_running"]>([]);
  const [saving, setSaving] = useState(false);
  const archived = Boolean(activity.archived_at);

  const accept = useCallback((timer: TimerState) => setSynced({ timer, receivedAt: Date.now() }), []);

  // Server is the source of truth: resync when the tab becomes visible again.
  const resync = useCallback(async () => {
    try {
      accept(await ep.getTimer(activity.id));
    } catch {
      /* keep the last known state */
    }
  }, [activity.id, accept]);

  useEffect(() => {
    setSynced({ timer: activity.timer ?? idleTimer(activity.id), receivedAt: Date.now() });
    setOthers([]);
    setSaving(false);
  }, [activity.id, activity.timer]);

  useEffect(() => {
    const onVis = () => document.visibilityState === "visible" && void resync();
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [resync]);

  useEffect(() => {
    if (synced.timer.state !== "running") return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [synced.timer.state]);

  const elapsed = liveElapsed(synced, now);
  const { state } = synced.timer;

  function handleConflict(e: unknown): boolean {
    if (e instanceof ApiError && e.status === 409) {
      const current = e.details?.current as TimerState | undefined;
      if (current) accept(current);
      else void resync();
      if (e.code === "activity_archived") toast("Занятие в архиве: таймер недоступен.");
      else toast("Таймер изменился на другом устройстве. Показываем актуальное состояние.");
      return true;
    }
    return false;
  }

  async function run(cmd: "start" | "pause" | "reset") {
    if (busy) return;
    if (cmd === "reset" && !window.confirm("Сбросить несохранённое время этого занятия?")) return;
    setBusy(cmd);
    try {
      const res = await ep.timerCommand(activity.id, cmd, synced.timer.revision);
      accept(res.timer);
      if (cmd === "start") setOthers(res.other_running ?? []);
      else setOthers([]);
      if (cmd === "reset") {
        setSaving(false);
        toast("Таймер сброшен. Несохранённое время удалено.");
      }
    } catch (e) {
      if (!handleConflict(e)) toast(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function pauseOther(activityId: string) {
    try {
      const t = await ep.getTimer(activityId);
      if (t.state === "running") await ep.timerCommand(activityId, "pause", t.revision);
      setOthers((o) => o.filter((x) => x.activity_id !== activityId));
      toast("Другой таймер на паузе.");
    } catch (e) {
      toast(errorText(e));
    }
  }

  const status =
    state === "running"
      ? "● Таймер идёт"
      : state === "paused"
        ? "Ⅱ На паузе · время не пропадёт"
        : "Таймер готов";

  return (
    <section className="card timer" aria-labelledby="timer-heading">
      <h2 id="timer-heading" className="visually-hidden">
        Таймер: {activity.name}
      </h2>
      <span className="pill" id="timer-status">
        {status}
      </span>
      <div className="timer-number" role="timer" aria-live="off" aria-label={`Накоплено ${clock(elapsed)}`}>
        {clock(elapsed)}
      </div>
      {elapsed > FOUR_HOURS && (
        <div className="notice warn" role="status">
          {elapsed > DAY
            ? "Таймер идёт больше суток — похоже, его забыли. При сохранении укажи настоящее время занятия."
            : "Таймер идёт больше 4 часов. Перед сохранением подтвердим, что всё верно."}
        </div>
      )}
      <p className="muted">Проверка и перерыв? Поставь на паузу.</p>
      {archived ? (
        <div className="notice">Занятие в архиве. История сохранена, но новые записи и таймер недоступны.</div>
      ) : (
        <div className="timer-actions">
          {state === "running" ? (
            <button className="primary" onClick={() => run("pause")} disabled={!!busy}>
              Ⅱ Пауза
            </button>
          ) : (
            <button className="primary" onClick={() => run("start")} disabled={!!busy}>
              ▶ {state === "paused" ? "Продолжить" : "Начать"}
            </button>
          )}
          <button
            className="gold"
            onClick={() => setSaving(true)}
            disabled={!!busy || state === "idle" || saving}
          >
            ✓ Сохранить
          </button>
          <button className="ghost" onClick={() => run("reset")} disabled={!!busy || state === "idle"}>
            Сбросить
          </button>
        </div>
      )}
      {busy && <small role="status">Отправляем на сервер…</small>}
      {others.length > 0 && (
        <div className="notice overlap" role="alert">
          <b>Сейчас идут и другие таймеры:</b>
          <ul>
            {others.map((o) => (
              <li key={o.activity_id}>
                {o.name} · {clock(o.elapsed_ms)}{" "}
                <button className="text-button" onClick={() => pauseOther(o.activity_id)}>
                  Поставить на паузу
                </button>
              </li>
            ))}
          </ul>
          <button className="text-button" onClick={() => setOthers([])}>
            Пусть идут вместе
          </button>
        </div>
      )}
      {saving && state !== "idle" && (
        <SaveForm
          activity={activity}
          canSetWorkload={canSetWorkload}
          synced={synced}
          elapsed={elapsed}
          today={today}
          onCancel={() => setSaving(false)}
          onConflict={handleConflict}
          onDone={(timer, entry) => {
            accept(timer);
            setSaving(false);
            setOthers([]);
            toast(`Время записано за ${ruDate(entry.activity_date)}. Таймер обнулён.`);
            onSaved(entry);
          }}
        />
      )}
      <small>У каждого занятия свой таймер. Время хранится на сервере и не пропадёт при переходе.</small>
    </section>
  );
}

function SaveForm({
  activity,
  canSetWorkload,
  synced,
  elapsed,
  today,
  onCancel,
  onConflict,
  onDone,
}: {
  activity: Activity;
  canSetWorkload: boolean;
  synced: Synced;
  elapsed: number;
  today: string;
  onCancel: () => void;
  onConflict: (e: unknown) => boolean;
  onDone: (timer: TimerState, entry: TimeEntry) => void;
}) {
  const toast = useToast();
  const startedOn = synced.timer.started_on ?? today;
  const span = Math.max(0, Math.min(31, dayNumber(today) - dayNumber(startedOn)));
  const dates = Array.from({ length: span + 1 }, (_, i) => addDays(startedOn, i));
  const [date, setDate] = useState(startedOn);
  const [confirmLong, setConfirmLong] = useState(false);
  const needsCorrection = elapsed > DAY || synced.timer.long_session === "correct";
  const needsConfirm = !needsCorrection && (elapsed > FOUR_HOURS || synced.timer.long_session === "confirm");
  const [hours, setHours] = useState("");
  const [minutes, setMinutes] = useState("");
  const [note, setNote] = useState("");
  const [workload, setWorkload] = useState<Workload>("normal");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    let duration: number | null = null;
    if (needsCorrection || hours || minutes) {
      duration = (Number(hours) || 0) * 3600 + (Number(minutes) || 0) * 60;
      if (!Number.isInteger(duration) || duration < 1 || duration > 86400) {
        setError("Укажи реальное время занятия: от 1 минуты до 24 часов.");
        return;
      }
      if (duration * 1000 > elapsed) {
        setError("Исправленное время не может быть больше, чем показал таймер.");
        return;
      }
    }
    if (needsConfirm && !confirmLong) {
      setError("Подтверди, что занятие действительно длилось так долго.");
      return;
    }
    setBusy(true);
    try {
      const res = await ep.saveTimer(activity.id, {
        revision: synced.timer.revision,
        activity_date: date,
        confirm_long_session: needsConfirm ? confirmLong : false,
        duration_seconds: duration,
        note: note.trim(),
        ...(canSetWorkload && activity.category === "lesson" ? { workload } : {}),
      });
      onDone(res.timer, res.entry);
    } catch (err) {
      if (onConflict(err)) {
        onCancel();
        return;
      }
      if (err instanceof ApiError) {
        const map: Record<string, string> = {
          duration_too_short: "Таймер шёл меньше секунды — сохранять пока нечего.",
          long_session_confirmation_required: "Подтверди длинное занятие (больше 4 часов).",
          session_too_long: "Таймер шёл больше суток. Укажи настоящее время занятия.",
          date_not_allowed: "Эту дату выбрать нельзя: только от начала сессии до сегодня.",
          daily_total_exceeded: "За один день по занятию нельзя записать больше 24 часов.",
          forbidden: "Это может изменить только взрослый.",
        };
        setError(map[err.code] ?? err.fieldErrors[0]?.message ?? errorText(err));
        // Draft keeps its time on any failure; nothing to roll back locally.
      } else toast(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="fields save-form" onSubmit={submit} aria-label="Сохранение времени таймера">
      <label>
        За какой день записать?
        {dates.length > 1 ? (
          <select value={date} onChange={(e) => setDate(e.target.value)}>
            {dates.map((d) => (
              <option key={d} value={d}>
                {ruDate(d)}
                {d === startedOn ? " · день начала" : ""}
                {d === today ? " · сегодня" : ""}
              </option>
            ))}
          </select>
        ) : (
          <output className="save-date">{ruDate(date)}{date === today ? " · сегодня" : ""}</output>
        )}
      </label>
      {needsCorrection ? (
        <fieldset className="duration-fields">
          <legend>Сколько длилось занятие на самом деле?</legend>
          <label>
            Часы
            <input type="number" min={0} max={24} inputMode="numeric" value={hours} onChange={(e) => setHours(e.target.value)} />
          </label>
          <label>
            Минуты
            <input type="number" min={0} max={59} inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </label>
        </fieldset>
      ) : (
        needsConfirm && (
          <label className="check-row">
            <input type="checkbox" checked={confirmLong} onChange={(e) => setConfirmLong(e.target.checked)} />
            Да, я занимался больше 4 часов
          </label>
        )
      )}
      {activity.category === "lesson" && canSetWorkload && (
        <label>
          Объём домашнего задания
          <select value={workload} onChange={(e) => setWorkload(e.target.value as Workload)}>
            {(Object.keys(WORKLOAD_LABELS) as Workload[]).map((w) => (
              <option key={w} value={w}>
                {WORKLOAD_LABELS[w]}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Заметка (необязательно)
        <input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="timer-actions">
        <button className="gold" disabled={busy}>
          {busy ? "Сохраняем…" : "✓ Записать время"}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
      </div>
    </form>
  );
}
