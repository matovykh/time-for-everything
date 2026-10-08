import { useState, type FormEvent } from "react";
import { useMe, useSession } from "../../app/session";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import { Icon } from "../../shared/ui/Icon";
import { permissionsOf } from "../../shared/permissions";
import { PageTitle, errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";

const ZONES = [
  "Europe/Kaliningrad",
  "Europe/Moscow",
  "Europe/Samara",
  "Asia/Yekaterinburg",
  "Asia/Omsk",
  "Asia/Novosibirsk",
  "Asia/Krasnoyarsk",
  "Asia/Irkutsk",
  "Asia/Yakutsk",
  "Asia/Vladivostok",
  "Asia/Magadan",
  "Asia/Kamchatka",
];

export function ProfilePage() {
  const me = useMe();
  const { updateMe, signOut, switchChild } = useSession();
  const toast = useToast();
  const [name, setName] = useState(me.display_name);
  const [grade, setGrade] = useState(me.grade ?? "");
  const [timezone, setTimezone] = useState(me.timezone);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const zones = ZONES.includes(me.timezone) ? ZONES : [me.timezone, ...ZONES];
  // Changing the zone shifts which calendar day entries belong to; only an adult may do it.
  const { canEditTimezone } = permissionsOf(me);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 40) return setError("Имя — от 1 до 40 символов.");
    setBusy(true);
    try {
      const updated = await ep.patchMe({
        display_name: trimmed,
        grade: grade || null,
        ...(canEditTimezone && timezone !== me.timezone ? { timezone } : {}),
      });
      updateMe(updated);
      toast("Профиль сохранён");
    } catch (err) {
      setError(err instanceof ApiError ? (err.fieldErrors[0]?.message ?? errorText(err)) : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function exit() {
    setLeaving(true);
    try {
      await signOut();
    } catch {
      // signOut always ends the local session; the server clears cookies on 204.
    }
  }

  return (
    <>
      <PageTitle title="Мой профиль" subtitle="Только о тебе — без подключений и настроек приложения." />
      <section className="card profile-card">
        <div className="profile-heading">
          <img src="/logos/user.png" alt="Аватар пользователя" />
          <div>
            <span className="overline">ИССЛЕДОВАТЕЛЬ ОСТРОВОВ</span>
            <h2>{me.display_name}</h2>
            <p className="muted">{me.email}</p>
          </div>
        </div>
        {me.children.length > 0 && (
          <div className="fields child-picker">
            <label>
              Чей профиль открыть?
              <select value={me.acting_child_id} onChange={(e) => switchChild(e.target.value)}>
                {me.children.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name}
                  </option>
                ))}
              </select>
            </label>
            <small>Вы взрослый: можно подтверждать качество уроков и отмечать поручения за прошлые дни выбранного ребёнка.</small>
          </div>
        )}
        <form className="fields" onSubmit={submit} noValidate>
          <label>
            Как тебя зовут?
            <input maxLength={40} value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Класс
            <select value={grade} onChange={(e) => setGrade(e.target.value)}>
              <option value="">Не указан</option>
              {Array.from({ length: 11 }, (_, i) => String(i + 1)).map((n) => (
                <option key={n} value={n}>
                  {n} класс
                </option>
              ))}
            </select>
          </label>
          <label>
            Часовой пояс профиля
            <select value={timezone} onChange={(e) => setTimezone(e.target.value)} disabled={!canEditTimezone}>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
          <small>
            Даты занятий, поручений и наград считаются по этому часовому поясу.
            {!canEditTimezone && " Часовой пояс меняет взрослый."}
          </small>
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить профиль"}
          </button>
        </form>
        <div className="profile-exit">
          <div>
            <b>До следующего открытия!</b>
            <small>При выходе работающие таймеры встанут на паузу. Всё записанное останется на сервере.</small>
          </div>
          <button className="ghost" onClick={exit} disabled={leaving}>
            <Icon name="exit" size={18} /> {leaving ? "Выходим…" : "Sign Out / Выйти"}
          </button>
        </div>
      </section>
    </>
  );
}
