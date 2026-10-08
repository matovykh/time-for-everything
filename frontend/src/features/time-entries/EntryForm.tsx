import { useState, type FormEvent } from "react";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { Activity, TimeEntry, Workload } from "../../shared/api/types";
import { isIsoDate } from "../../shared/dates";
import { errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";
import { WORKLOAD_LABELS } from "./labels";

export const ENTRY_ERRORS: Record<string, string> = {
  future_date: "Будущую дату выбрать нельзя.",
  daily_total_exceeded: "За один день по занятию нельзя записать больше 24 часов.",
  activity_archived: "Занятие в архиве: новые записи недоступны.",
  wrong_activity_kind: "Для поручений время не записывается.",
  forbidden: "Это может изменить только взрослый (например, дату и время проверенной записи).",
};

/** Validates hours+minutes → seconds within the manual-entry range (60–86400). */
export function parseDuration(hours: string, minutes: string): number | null {
  const h = hours.trim() === "" ? 0 : Number(hours);
  const m = minutes.trim() === "" ? 0 : Number(minutes);
  if (!Number.isInteger(h) || !Number.isInteger(m) || h < 0 || m < 0 || m > 1440) return null;
  const s = h * 3600 + m * 60;
  return s >= 60 && s <= 86400 ? s : null;
}

export function ManualEntryForm({
  activity,
  today,
  onCreated,
  canSetWorkload,
}: {
  activity: Activity;
  today: string;
  onCreated: (e: TimeEntry) => void;
  canSetWorkload: boolean;
}) {
  const toast = useToast();
  const [date, setDate] = useState(today);
  const [hours, setHours] = useState("");
  const [minutes, setMinutes] = useState("");
  const [note, setNote] = useState("");
  const [workload, setWorkload] = useState<Workload>("normal");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const disabled = Boolean(activity.archived_at);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    const seconds = parseDuration(hours, minutes);
    if (!isIsoDate(date) || date > today) return setError("Выбери дату не позже сегодняшней.");
    if (date < "2000-01-01") return setError("Слишком давняя дата.");
    if (seconds === null) return setError("Укажи время от 1 минуты до 24 часов.");
    setBusy(true);
    try {
      const entry = await ep.createEntry(activity.id, {
        activity_date: date,
        duration_seconds: seconds,
        note: note.trim(),
        // Workload is an adult's call; a child's entry keeps the server default ("normal").
        ...(canSetWorkload && activity.category === "lesson" ? { workload } : {}),
      });
      setHours("");
      setMinutes("");
      setNote("");
      toast("Запись добавлена. Текущий таймер не изменён.");
      onCreated(entry);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? (ENTRY_ERRORS[err.code] ?? err.fieldErrors[0]?.message ?? errorText(err))
          : errorText(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Добавить время вручную</h2>
      <p className="muted">Если забыл включить таймер — ничего страшного.</p>
      <form className="fields" onSubmit={submit} noValidate>
        <label>
          Дата
          <input type="date" value={date} max={today} min="2000-01-01" required onChange={(e) => setDate(e.target.value)} disabled={disabled} />
        </label>
        <div className="form-row">
          <label>
            Часы
            <input type="number" min={0} max={24} step={1} inputMode="numeric" placeholder="0" value={hours} onChange={(e) => setHours(e.target.value)} disabled={disabled} />
          </label>
          <label>
            Минуты
            <input type="number" min={0} max={1440} step={1} inputMode="numeric" placeholder="Например, 25" value={minutes} onChange={(e) => setMinutes(e.target.value)} disabled={disabled} />
          </label>
        </div>
        {activity.category === "lesson" && canSetWorkload && (
          <label>
            Объём домашнего задания
            <select value={workload} onChange={(e) => setWorkload(e.target.value as Workload)} disabled={disabled}>
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
          <input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} disabled={disabled} />
        </label>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={busy || disabled}>
          {busy ? "Добавляем…" : "Добавить запись"}
        </button>
      </form>
    </section>
  );
}
