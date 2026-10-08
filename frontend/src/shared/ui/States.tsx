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

/** Human readable error text; never shows raw stack traces. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0)
      return "Нет связи с сервером. Проверь интернет или запусти backend.";
    if (error.status === 401) return "Сессия завершилась. Войди снова.";
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
