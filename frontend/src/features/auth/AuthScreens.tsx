import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "../../app/session";
import { ApiError } from "../../shared/api/client";
import type { HealthReady } from "../../shared/api/types";
import { errorText } from "../../shared/ui/States";
import { ThemeSwitch } from "../../app/ThemeSwitch";

function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-theme">
        <ThemeSwitch />
      </div>
      <section className="signed-out auth-card">
        <img src="/logos/full-logo.png" alt="Всё успею" />
        {children}
      </section>
    </div>
  );
}

export function LoginScreen({ expired = false }: { expired?: boolean }) {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_credentials")
        setError("Неверная почта или пароль.");
      else if (err instanceof ApiError && err.status === 429)
        setError(
          `Слишком много попыток входа. Подожди${err.retryAfter ? ` ${err.retryAfter} с` : " немного"} и попробуй снова.`,
        );
      else if (err instanceof ApiError && err.status === 503)
        setError(
          "Вход временно недоступен: сервер не подключён к Supabase или базе данных. Попроси взрослого проверить настройку установки.",
        );
      else if (err instanceof ApiError && err.status === 422)
        setError(err.fieldErrors[0]?.message ?? "Проверь почту и пароль.");
      else if (err instanceof ApiError && err.code === "timeout")
        // Not retried automatically: the attempt may have reached the server.
        setError("Сервер не ответил вовремя. Попробуй войти ещё раз чуть позже.");
      else setError(errorText(err));
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  return (
    <AuthFrame>
      <h1>С возвращением!</h1>
      <p className="muted">Твой остров ждёт. Войди, чтобы продолжить свои открытия.</p>
      {expired && <div className="notice">Сессия завершилась. Войди снова — несохранённое время таймеров хранится на сервере.</div>}
      <form className="fields auth-form" onSubmit={submit} noValidate>
        <label>
          Электронная почта
          <input
            type="email"
            name="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={busy || !email.trim() || !password}>
          {busy ? "Входим…" : "Войти"}
        </button>
      </form>
      <p className="muted auth-hint">
        Аккаунт создаёт взрослый в Supabase. Регистрация и восстановление пароля в этой версии
        пока недоступны — обратись к взрослому, который настраивал приложение.
      </p>
    </AuthFrame>
  );
}

export function SignedOutScreen({
  onSignIn,
  warning,
  onRetryLogout,
}: {
  onSignIn: () => void;
  warning?: string;
  onRetryLogout?: () => void;
}) {
  return (
    <AuthFrame>
      <h1>До нового открытия!</h1>
      <p>Твой мир подождёт. Здесь ничего не пропадает.</p>
      {warning ? (
        <div className="notice warn" role="alert">
          {warning}
        </div>
      ) : (
        <div className="notice">
          Ты вышел из аккаунта: сессия завершена на сервере, работающие таймеры поставлены на паузу.
        </div>
      )}
      {onRetryLogout && (
        <button className="ghost" onClick={onRetryLogout}>
          Повторить выход
        </button>
      )}
      <button className="primary" onClick={onSignIn} autoFocus>
        Войти снова
      </button>
    </AuthFrame>
  );
}

const SETUP_HINTS: Record<string, string> = {
  network_error:
    "Браузер не достучался до backend. Запусти сервер FastAPI (по умолчанию http://127.0.0.1:8000) — в режиме разработки Vite проксирует /api на него (переменная VITE_BACKEND_ORIGIN).",
  service_not_configured:
    "Сервер запущен, но не подключён к базе данных или Supabase Auth. Заполни переменные окружения на сервере (не в браузере) и перезапусти его.",
  schema_missing:
    "База данных доступна, но схема не создана или устарела. Примени миграции backend — сервер не создаёт схему автоматически.",
  auth_unavailable: "Сервер не может связаться с Supabase Auth. Проверь адрес проекта и сеть сервера.",
  timeout:
    "Сервер не ответил вовремя. Он может ещё запускаться или долго ждать базу данных или Supabase. Подожди немного и нажми «Проверить снова»; если повторяется — взрослому стоит проверить журнал сервера.",
};

export function SetupScreen({
  error,
  ready,
  onRetry,
}: {
  error: ApiError;
  ready: HealthReady | null;
  onRetry: () => void;
}) {
  const missing = Array.isArray(error.details?.missing) ? (error.details?.missing as string[]) : [];
  // status 0 = the server did not answer (offline or timed out), not a configuration verdict.
  const unreachable = error.status === 0;
  return (
    <AuthFrame>
      <h1>{unreachable ? "Сервер не отвечает" : "Приложение ещё настраивается"}</h1>
      <p className="muted">
        {unreachable
          ? "Это не ошибка ребёнка. Не удалось дождаться ответа сервера — попробуй ещё раз через несколько секунд."
          : "Это не ошибка ребёнка. Взрослому нужно завершить настройку сервера, и тогда здесь появится вход."}
      </p>
      <div className="notice setup-notice" role="alert">
        <b>{SETUP_HINTS[error.code] ?? errorText(error)}</b>
        {missing.length > 0 && (
          <p>
            Не заданы: <code>{missing.join(", ")}</code>
          </p>
        )}
        {ready && Object.keys(ready.checks ?? {}).length > 0 && (
          <ul className="setup-checks">
            {Object.entries(ready.checks).map(([k, v]) => (
              <li key={k}>
                {k}: <b>{v}</b>
              </li>
            ))}
          </ul>
        )}
        {ready?.setup?.length ? (
          <ol>
            {ready.setup.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        ) : null}
        {error.requestId && <small>Код запроса: {error.requestId}</small>}
      </div>
      <p className="muted auth-hint">
        Ключи и пароли вводятся только на сервере установки (файл окружения), никогда в браузере.
      </p>
      <button className="primary" onClick={onRetry}>
        Проверить снова
      </button>
    </AuthFrame>
  );
}

/** After this long on the startup screen, explain the wait and offer a restart. */
export const SLOW_START_HINT_MS = 5_000;

export function Checking({ onRetry }: { onRetry?: () => void }) {
  const [slow, setSlow] = useState(false);
  const [round, setRound] = useState(0); // this screen stays mounted across retries
  useEffect(() => {
    setSlow(false);
    const t = setTimeout(() => setSlow(true), SLOW_START_HINT_MS);
    return () => clearTimeout(t);
  }, [round]);
  return (
    <div className="auth-page">
      <div className="state-box loading boot" role="status" aria-live="polite">
        <img src="/logos/logo.png" alt="" width={64} />
        <span>Открываем твой остров…</span>
        {slow && (
          <>
            <small>
              Сервер отвечает дольше обычного. Если ответа так и не будет, через несколько секунд покажем, что
              случилось.
            </small>
            {onRetry && (
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setRound((r) => r + 1);
                  onRetry();
                }}
              >
                Попробовать снова
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
