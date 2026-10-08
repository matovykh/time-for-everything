import { useState, type FormEvent } from "react";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { Activity, QualityStatus, TimeEntry, Workload } from "../../shared/api/types";
import { duration, isIsoDate, ruDate } from "../../shared/dates";
import { errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";
import { ENTRY_ERRORS, parseDuration } from "./EntryForm";
import { isReviewed, type Permissions } from "../../shared/permissions";
import { QUALITY_LABELS, SOURCE_LABELS, WORKLOAD_LABELS } from "./labels";

export function HistoryTable({
  activity,
  entries,
  totalCount,
  hasMore,
  loadingMore,
  onLoadMore,
  onChanged,
  today,
  permissions,
}: {
  activity: Activity;
  entries: TimeEntry[];
  totalCount: number | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onChanged: () => void;
  today: string;
  permissions: Permissions;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const { canConfirmQuality, canSetWorkload, canDeleteReviewed } = permissions;
  const isLesson = activity.category === "lesson";

  async function remove(e: TimeEntry) {
    if (!window.confirm(`Удалить запись за ${ruDate(e.activity_date)} (${duration(e.duration_seconds)})?`)) return;
    try {
      await ep.deleteEntry(e.id, e.revision);
      toast("Запись удалена.");
    } catch (err) {
      toast(
        err instanceof ApiError && err.status === 409
          ? "Запись уже изменилась. Обновили историю."
          : err instanceof ApiError && err.status === 403
            ? "Проверенную взрослым запись удаляет взрослый."
            : errorText(err),
      );
    }
    onChanged();
  }

  async function setQuality(e: TimeEntry, q: QualityStatus) {
    try {
      await ep.setEntryQuality(e.id, e.revision, q);
      toast("Отметка качества сохранена.");
    } catch (err) {
      toast(errorText(err));
    }
    onChanged();
  }

  return (
    <section className="card history-card">
      <div className="section-head">
        <h2>История за всё время</h2>
        <small>
          {totalCount !== null ? `${totalCount} ${plural(totalCount)}` : `${entries.length} ${plural(entries.length)}`}
        </small>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Дата</th>
              <th>Время</th>
              <th>Источник</th>
              {isLesson && <th>Объём</th>}
              {isLesson && <th>Проверка</th>}
              <th>Заметка</th>
              <th>
                <span className="visually-hidden">Действия</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={isLesson ? 7 : 5}>Пока нет записей. Начнём с первой!</td>
              </tr>
            )}
            {entries.map((e) =>
              editing === e.id ? (
                <EditRow
                  key={e.id}
                  entry={e}
                  isLesson={isLesson}
                  canSetWorkload={canSetWorkload}
                  isAdult={canConfirmQuality}
                  today={today}
                  onDone={(changed) => {
                    setEditing(null);
                    if (changed) onChanged();
                  }}
                />
              ) : (
                <tr key={e.id}>
                  <td>{ruDate(e.activity_date)}</td>
                  <td>{duration(e.duration_seconds)}</td>
                  <td>{SOURCE_LABELS[e.source] ?? e.source}</td>
                  {isLesson && <td>{WORKLOAD_LABELS[e.workload] ?? e.workload}</td>}
                  {isLesson && (
                    <td>
                      {canConfirmQuality ? (
                        <select
                          aria-label={`Качество записи за ${ruDate(e.activity_date)}`}
                          value={e.quality_status}
                          onChange={(ev) => setQuality(e, ev.target.value as QualityStatus)}
                        >
                          {(["pending", "confirmed", "rejected"] as QualityStatus[]).map((q) => (
                            <option key={q} value={q}>
                              {QUALITY_LABELS[q]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        QUALITY_LABELS[e.quality_status] ?? e.quality_status
                      )}
                    </td>
                  )}
                  <td className="note-cell">{e.note || "—"}</td>
                  <td className="row-actions">
                    <button className="text-button" onClick={() => setEditing(e.id)} aria-label={`Изменить запись за ${ruDate(e.activity_date)}`}>
                      {isLesson && isReviewed(e) && !canConfirmQuality ? "Изменить заметку" : "Изменить"}
                    </button>
                    {isReviewed(e) && !canDeleteReviewed ? (
                      <small className="locked-note">Удаляет взрослый</small>
                    ) : (
                      <button className="text-button danger" onClick={() => remove(e)} aria-label={`Удалить запись за ${ruDate(e.activity_date)}`}>
                        Удалить
                      </button>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <button className="ghost load-more" onClick={onLoadMore} disabled={loadingMore}>
          {loadingMore ? "Загружаем…" : "Показать более ранние записи"}
        </button>
      )}
      <small>Изменения и удаления записываются в журнал на сервере.</small>
    </section>
  );
}

function plural(n: number) {
  const a = n % 100;
  const b = n % 10;
  if (a > 10 && a < 20) return "записей";
  if (b === 1) return "запись";
  if (b > 1 && b < 5) return "записи";
  return "записей";
}

function EditRow({
  entry,
  isLesson,
  canSetWorkload,
  isAdult,
  today,
  onDone,
}: {
  entry: TimeEntry;
  isLesson: boolean;
  canSetWorkload: boolean;
  isAdult: boolean;
  today: string;
  onDone: (changed: boolean) => void;
}) {
  const toast = useToast();
  const [date, setDate] = useState(entry.activity_date);
  const totalMin = Math.round(entry.duration_seconds / 60);
  const [hours, setHours] = useState(String(Math.floor(totalMin / 60)));
  const [minutes, setMinutes] = useState(String(totalMin % 60));
  const [note, setNote] = useState(entry.note);
  const [workload, setWorkload] = useState<Workload>(entry.workload);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Date/duration of an adult-reviewed lesson entry are locked for a child (server: 403);
  // the note stays editable.
  const noteOnly = isLesson && !isAdult && isReviewed(entry);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!noteOnly && (!isIsoDate(date) || date > today)) return setError("Дата не может быть в будущем.");
    const durationChanged = Math.round(entry.duration_seconds / 60) !== (Number(hours) || 0) * 60 + (Number(minutes) || 0);
    const seconds = durationChanged && !noteOnly ? parseDuration(hours, minutes) : entry.duration_seconds;
    if (seconds === null) return setError("Время: от 1 минуты до 24 часов.");
    setBusy(true);
    try {
      await ep.patchEntry(entry.id, {
        revision: entry.revision,
        ...(!noteOnly && date !== entry.activity_date ? { activity_date: date } : {}),
        ...(!noteOnly && seconds !== entry.duration_seconds ? { duration_seconds: seconds } : {}),
        ...(note.trim() !== entry.note ? { note: note.trim() } : {}),
        ...(isLesson && canSetWorkload && workload !== entry.workload ? { workload } : {}),
      });
      toast("Запись обновлена.");
      onDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast("Запись уже изменилась на другом устройстве. Обновили историю.");
        onDone(true);
        return;
      }
      setError(err instanceof ApiError ? (ENTRY_ERRORS[err.code] ?? err.fieldErrors[0]?.message ?? errorText(err)) : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="edit-row">
      <td colSpan={isLesson ? 7 : 5}>
        <form className="inline-edit" onSubmit={submit}>
          <label>
            Дата
            <input type="date" value={date} max={today} disabled={noteOnly} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label>
            Часы
            <input type="number" min={0} max={24} value={hours} disabled={noteOnly} onChange={(e) => setHours(e.target.value)} />
          </label>
          <label>
            Минуты
            <input type="number" min={0} max={1440} value={minutes} disabled={noteOnly} onChange={(e) => setMinutes(e.target.value)} />
          </label>
          {isLesson && canSetWorkload && (
            <label>
              Объём
              <select value={workload} onChange={(e) => setWorkload(e.target.value as Workload)}>
                {(Object.keys(WORKLOAD_LABELS) as Workload[]).map((w) => (
                  <option key={w} value={w}>
                    {WORKLOAD_LABELS[w]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="grow">
            Заметка
            <input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="inline-actions">
            <button className="primary" disabled={busy}>
              Сохранить
            </button>
            <button type="button" className="ghost" onClick={() => onDone(false)} disabled={busy}>
              Отмена
            </button>
          </div>
          {noteOnly && (
            <small className="review-hint">
              Взрослый уже проверил эту запись: дату и время меняет только взрослый. Заметку можно изменить.
            </small>
          )}
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
        </form>
      </td>
    </tr>
  );
}
