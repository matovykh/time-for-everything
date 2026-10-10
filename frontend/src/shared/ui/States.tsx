import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Loading({ label = "Загружаем…" }: { label?: string }) {
  return (
    <div className="state-box loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export const CSRF_FAILED_TEXT =
  "Сервер отклонил запрос защитой от подделки (CSRF): токен безопасности устарел или не совпал. Обнови страницу и попробуй ещё раз. Если ошибка повторяется, адрес в браузере может не совпадать с адресом, настроенным на сервере.";
export const CSRF_COOKIE_MISSING_TEXT =
  "Браузер не сохранил защитный cookie, поэтому сервер отклоняет вход и изменения (CSRF). Обычно так бывает, когда приложение открыто по http://, а сервер выдаёт cookie только для https://, или когда cookie запрещены. Открой приложение по https-адресу установки или попроси взрослого проверить настройку.";

/** Human readable error text; never shows raw stack traces. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "timeout")
      return "Сервер не ответил вовремя. Проверь связь и попробуй ещё раз.";
    if (error.status === 0)
      return "Нет связи с сервером. Проверь интернет или запусти backend.";
    if (error.status === 401) return "Сессия завершилась. Войди снова.";
    // CSRF rejections are not a permissions problem; say what actually happened.
    if (error.code === "csrf_cookie_missing") return CSRF_COOKIE_MISSING_TEXT;
    if (error.code === "csrf_failed") return CSRF_FAILED_TEXT;
    if (error.status === 403) return "Недостаточно прав для этого действия.";
    if (error.status === 404) return "Не нашли такие данные.";
    if (error.status === 409)
      return "Данные изменились на другом устройстве. Мы обновили состояние.";
    if (error.status === 429) return "Слишком много попыток. Подожди немного.";
    if (error.status >= 500)
      return "Сервер временно недоступен. Попробуй ещё раз чуть позже.";
    return error.message || "Не получилось выполнить запрос.";
  }
  return "Что-то пошло не так. Попробуй ещё раз.";
}

export function ErrorState({
  error,
  onRetry,
  title = "Не удалось загрузить",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div className="state-box error" role="alert">
      <b>{title}</b>
      <span>{errorText(error)}</span>
      {requestId && <small>Код запроса: {requestId}</small>}
      {onRetry && (
        <button type="button" className="ghost" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function PageTitle({
  title,
  subtitle,
  aside,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {aside}
    </div>
  );
}
