# Архитектура MVP «Всё успею»

Описание фактической реализации. Целевой дизайн всего продукта — [SPECIFICATION.md](SPECIFICATION.md);
точный HTTP-контракт — [API.md](API.md). Где они расходятся, реализацию описывают этот документ и API.md.

## 1. Обзор

Модульный монолит на Python и SPA на одном origin, поставляемые одним контейнером:

| Слой | Технологии | Каталог |
|---|---|---|
| Frontend | React 19, TypeScript, Vite 7, Unovis 1.7.1, Nunito Sans (локально) | [`frontend/`](../frontend/IMPLEMENTATION.md) |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (sync), psycopg 3, Uvicorn | [`backend/`](../backend/README.md) |
| БД и Auth | Внешний Supabase: PostgreSQL 15+ и Supabase Auth (GoTrue) | [`supabase/`](../supabase/README.md) |
| Миграции и reset | CLI-скрипты, запускаются оператором | `scripts/` |
| Контейнер | Двухэтапный Dockerfile (Node 24 → Python 3.13 slim) | отдельный репозиторий `time-for-everything_deploy` (`docker/Dockerfile`, `compose/`) |
| CI | Source CI (GitHub Actions): backend, postgres, frontend. Сборки образа и деплоя нет | `.github/workflows/ci.yml` |

`prototype/` — отдельный исторический макет без сервера; в рабочее приложение и в образ не входит.
Его CSS и арт-модуль миров скопированы во `frontend/src/`.

## 2. Поток запроса

1. Браузер загружает SPA с того же сервера. Маршрутизация — hash (`#home`, `#activity/<id>` …), поэтому
   серверу достаточно отдавать `index.html`; прочие не-`/api` GET-пути тоже отдают `index.html`.
2. SPA вызывает `GET /api/v1/auth/csrf`, затем `GET /api/v1/me`. Если сессии нет, проверяется
   `GET /api/v1/health/ready`, чтобы показать вход или экран «настраивается».
3. Каждый запрос к данным проходит цепочку зависимостей FastAPI:
   cookie `tfe_at` → проверка JWT → проверка отзыва сессии → провижининг профиля → определение
   «действующего ребёнка» (`X-Child-Id` только для связанного взрослого) → роутер модуля → сервис.
4. Все запросы сервиса фильтруются по `ctx.child_id`. Чужой ресурс неотличим от отсутствующего (404).

## 3. Модули backend

```
backend/app/
  main.py            фабрика приложения, роутеры, SPA fallback, отключение docs в production
  core/              config, clock, errors, security (CSRF, cookies, лимит тела 64 КиБ, заголовки,
                     лимитер входа), deps (сессия → принципал → провижининг → ребёнок),
                     idempotency, audit, общие строгие схемы запросов
  db/                ORM-модели (зеркало SQL-миграций), engine/session, проверка версии схемы
  integrations/      supabase_auth: REST-клиент GoTrue + проверка JWT (JWKS ES256/RS256 или HS256)
  modules/
    accounts         вход/refresh/выход, /me, провижининг, отзыв сессий
    activities       занятия, расписания (версии по датам)
    timers           серверные таймеры: start/pause/reset/save
    entries          записи времени, история, дневные суммы, проверка качества
    chores           отметки поручений, статусы дней прогулки
    analytics        недельные/дневные агрегаты для графиков (только чтение)
    dashboard        сводка главной страницы (только чтение)
    rewards          policy.py — чистые функции политики v1; service — оценка периодов
    wallet           единственный модуль, пишущий журнал кошелька
    world            каталог миров, коллекция, покупки улучшений (только списание)
    administration   health live/ready, read-only /settings
```

Схема «роутер (HTTP) → сервис (доменная логика)». Отдельных репозиториев нет: запросы находятся в
сервисах и всегда фильтруются по владельцу.

## 4. Ключевые механизмы

- **Таймеры.** Одна строка-черновик на занятие (`timer_drafts`). Команды требуют ожидаемую `revision`
  и заголовок `Idempotency-Key`; строка блокируется `SELECT … FOR UPDATE`. Клиент не присылает
  прошедшее время — сервер считает его по `running_since`. Сохранение = заморозка времени + запись в
  `time_entries` + сброс черновика в **одной транзакции**. Правила: дата от `started_on` до сегодня,
  подтверждение > 4 ч, исправление > 24 ч, не более 24 ч в сутки на занятие.
- **История.** Записи бессрочные; `daily-totals` возвращает только даты с записями (без заполнения
  нулями), по возрастанию. Удаление — мягкое, с аудитом.
- **Расписания.** Версии с `starts_on/ends_on` и маской дней недели. Изменение создаёт новую версию с
  будущей даты, поэтому знаменатели прошлых периодов не переписываются. Даты считаются в часовом поясе
  ребёнка.
- **Награды (policy v1).** Детерминированные чистые функции с точными дробями. Даты оценки
  `D_k = A + 14 + 7k` (A — дата провижининга). Окно `[D−7, D−1]`, база `[D−14, D−8]`. Категории: уроки
  (до 30 за предмет, всего ≤ 100), прогулка (40/20), поручения (≤ 40). Неполные данные → `deferred`,
  через 7 дней финализация. Оценка запускается при открытии приложения и по
  `POST /rewards/evaluate`; фонового планировщика нет. Уникальность `(child, period_end, category)` +
  ключ идемпотентности кошелька + блокировка строки кошелька исключают двойную выплату. Подробные
  правила — [API.md §8](API.md#8-reward-policy-v1-deterministic-what-the-server-computes).
- **Целостность наград.** Ребёнок не может задать `workload`, сменить часовой пояс, изменить дату/время
  или удалить проверенную запись урока. Ключи идемпотентности ограничены (пользователь, ребёнок, ключ).
  Целые числа в теле запроса строгие (`"600"` → 422).
- **Кошелёк и миры.** Баланс меняется условным `UPDATE … WHERE balance + :x >= 0`; журнал
  `wallet_transactions` только дописывается (триггер), у каждого ребёнка своя последовательность `seq`.
  Покупка — одна транзакция: блокировка кошелька → проверки (коллекция, владение, предпосылка, баланс)
  → запись журнала → баланс → открытие → событие. Цена и предпосылки только с сервера.
- **Провижининг.** При первом аутентифицированном запросе: профиль `child`, 7 занятий с таймером,
  4 поручения, черновики таймеров, кошелёк 0, мир `settlers`. Идемпотентно и устойчиво к гонкам.
  Из `user_metadata` берётся только отображаемое имя.

## 5. Аутентификация и безопасность

- `POST /auth/login` — сервер сам вызывает Supabase `token?grant_type=password` с publishable-ключом.
  Токены живут только в cookies:

  | Cookie | HttpOnly | SameSite | Path |
  |---|---|---|---|
  | `tfe_at` (access JWT) | да | Lax | `/api` |
  | `tfe_rt` (refresh) | да | Strict | `/api/v1/auth` |
  | `tfe_csrf` | нет | Strict | `/` |

  Все — `Secure`, кроме режима `APP_ENV=development` + `COOKIE_SECURE=false`.
- **JWT** проверяется на каждом запросе: подпись (JWKS `/auth/v1/.well-known/jwks.json` или HS256-секрет),
  `exp`, `aud=authenticated`, `iss`, `role=authenticated`.
- **CSRF**: double-submit (`X-CSRF-Token` = cookie `tfe_csrf`) на всех небезопасных методах, включая
  вход, плюс проверка `Origin` против `APP_BASE_URL`. CORS не включён.
- **Выход** (`POST /auth/logout`): (1) запись в `revoked_sessions` ключей `sid:`, `at:` (sha256 access) и
  `rt:` (sha256 refresh); (2) пауза таймеров; (3) best-effort Supabase `/logout`; (4) очистка cookies —
  всегда. `204` — отзыв зафиксирован; `503 logout_incomplete` — отозвать на сервере не удалось (БД или
  JWKS недоступны), cookies всё равно очищены. Каждый запрос и каждый refresh проверяют отзыв, поэтому
  скопированная cookie перестаёт работать сразу.
- **Права.** Роль хранится в `profiles.role` (`child` | `guardian` | `admin`) и назначается только
  оператором. Флаги `me.permissions` (`can_confirm_quality`, `can_set_workload`,
  `can_delete_reviewed_entries`, `can_edit_timezone`, …) истинны только для взрослого, действующего за
  связанного ребёнка. UI использует их лишь для отображения; источник истины — сервер.
- **Логи**: только request id, метод, шаблон маршрута и класс исключения; engine с
  `hide_parameters=True`. Секреты не возвращаются API (`/settings` отдаёт только `configured`).
- **Лимитер входа**: в памяти процесса (10 попыток / 300 с по умолчанию).
- **Заголовки**: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, COOP. HSTS/CSP — на proxy.
- **Контейнер**: uid 10001, read-only root FS, без capabilities, `no-new-privileges`, конфигурация
  read-only, source maps не собираются.

## 6. База данных

Миграции: `supabase/migrations/20261006000001_init.sql`, `20261006000002_session_revocations.sql`.
Все объекты — в схеме `public`; `profiles.id` ссылается на `auth.users(id)`.

| Группа | Таблицы |
|---|---|
| Служебные | `app_schema_migrations`, `audit_events`, `idempotency_requests`, `revoked_sessions` |
| Справочники | `world_themes` (4), `world_catalog` (16 улучшений), `reward_policies` (v1) |
| Аккаунты | `profiles`, `guardian_children` |
| Занятия | `activities`, `schedules`, `chore_completions`, `timer_drafts`, `time_entries`, `day_statuses` |
| Награды и кошелёк | `reward_evaluations`, `wallet_accounts`, `wallet_transactions` |
| Миры | `child_worlds`, `world_unlocks`, `world_events` |

- **RLS включён на всех таблицах.** Роль `anon` не имеет доступа; `authenticated` через Data API может
  только `SELECT` своих строк / строк связанных детей и справочников; записи через Data API нет.
  Служебные таблицы ей не видны.
- Backend подключается по `DATABASE_URL` (обычно владелец таблиц, который обходит RLS) и сам проверяет
  владельца в каждом запросе — это покрыто тестами изоляции.
- Целостность: CHECK-ограничения, составные внешние ключи (ребёнок + ресурс), неизменяемый журнал
  кошелька и финальных оценок (триггеры), неотрицательный баланс.
- Приложение не меняет схему при старте; миграции и reset — только скриптами оператора
  ([supabase/README.md](../supabase/README.md); порядок для оператора — `docs/DEPLOYMENT.md` в `time-for-everything_deploy`).

## 7. Frontend

- `src/app/` — выбор экрана (проверка / настройка / вход / выход / приложение), сессия, тема,
  hash-роутер, оболочка, знакомство.
- `src/shared/api/client.ts` — same-origin `fetch`, CSRF, один refresh и повтор при
  `401 session_expired`, `Idempotency-Key`, `X-Child-Id`.
- `src/features/*` — экраны: dashboard, activities, timers, time-entries, chores, rewards, world,
  onboarding, profile, settings, auth.
- В `localStorage` хранится только тема; в `sessionStorage` — выбранный взрослым ребёнок. Токены и
  данные в Web Storage не попадают. Демо-данных нет.
- Подробности и соответствие экранов API — [frontend/IMPLEMENTATION.md](../frontend/IMPLEMENTATION.md).

## 8. Развёртывание

Один контейнер `docker.io/matovykh/time-for-everything:<version>-rN` (`EXPOSE 8000`, `HEALTHCHECK` = GET
`/api/v1/health/live`, запуск `uvicorn … --no-proxy-headers`), порт только на `127.0.0.1`, HTTPS — на внешнем
reverse proxy, конфигурация — read-only файл по `CONFIG_FILE`. Один worker. Образ, compose, релизы и
инструкции оператора находятся в отдельном DevOps-репозитории `time-for-everything_deploy` (адрес будет
указан после публикации). Ниже описан контракт, который приложение предоставляет любому способу запуска.

### Контракт конфигурации

Источник истины — `Settings` в `backend/app/core/config.py` (pydantic-settings).

- **Источники**: переменные окружения процесса и, если задан `CONFIG_FILE`, файл `KEY=value` в UTF-8.
  Переменные окружения имеют приоритет над файлом. Имена ключей регистронезависимы,
  неизвестные ключи игнорируются. Настройки читаются один раз, при старте процесса.
- **Ключи**: `APP_ENV` (`production` по умолчанию | `development` | `test`), `APP_BASE_URL`,
  `COOKIE_SECURE` (`true`), `DATABASE_URL`, `DB_POOL_SIZE` (1–50, 5), `SUPABASE_URL`,
  `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET` (только legacy HS256), `SUPABASE_JWT_AUDIENCE`
  (`authenticated`), `OPENAI_API_KEY`/`OPENAI_MODEL` (зарезервированы), `FRONTEND_DIST`
  (`../frontend/dist` относительно `backend/`), `LOGIN_RATE_LIMIT` (10), `LOGIN_RATE_WINDOW_SECONDS` (300).
  Шаблоны: `.env.example`, `backend/.env.example`. Production-шаблон лежит в DevOps-репозитории, и
  его ключи сверяются с `Settings` образа при релизе.
- **Ни одна настройка не обязательна для старта.** Без них live = 200, ready = 503 (с перечнем `setup`),
  а маршруты данных отвечают `503 service_not_configured`. Для ready нужны `DATABASE_URL`, `SUPABASE_URL`,
  `SUPABASE_PUBLISHABLE_KEY`, доступная БД и схема `REQUIRED_SCHEMA_VERSION`.
- **Fail closed**: если `CONFIG_FILE` задан, а файла нет, это не обычный файл, он нечитаем, не в UTF-8
  или содержит неверное значение, процесс не стартует. Он пишет одну строку `Configuration error: …`
  с путём, именами ключей и типами ошибок, без значений и traceback.
- **Секреты** (`DATABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`) хранятся
  как `SecretStr`: `repr`/JSON их маскируют, ошибки валидации не повторяют введённые значения, пустая
  строка означает «не задано». `GET /settings` и `/health/ready` отдают только статусы. Записи настроек из
  интерфейса нет.
- `COOKIE_SECURE=false` действует только вместе с `APP_ENV=development`. TLS к БД задаётся в самом `DATABASE_URL`
  (`sslmode=require`), приложение его не добавляет. Пул соединений — до `2 × DB_POOL_SIZE`.
- Контракт с релизом: `APP_VERSION` в `config.py` равен версии git-тега, `REQUIRED_SCHEMA_VERSION` равен
  последней миграции ([CONTRIBUTING.md](../CONTRIBUTING.md)).
- Тесты: `backend/tests/test_config_secrets.py`, `tests/backend/test_qa_security_sweeps.py`.

### Логи и их ограничения

- Собственные логи приложения при ошибке содержат только request id, метод, шаблон маршрута
  и класс исключения. Engine SQLAlchemy работает с `hide_parameters=True`.
- `core/log_redaction.py`: в `uvicorn.access` query string заменяется на `?[query-redacted]`, а traceback
  «Exception in ASGI application» в `uvicorn.error` сводится к имени класса (кроме `APP_ENV=development`).
- **Ограничения**: **путь** запроса в access log не скрывается (production compose поэтому запускает
  uvicorn с `--no-access-log`). Другие логгеры (`asyncio`, сторонние библиотеки) не фильтруются;
  `httpx` на уровне INFO пишет URL запросов к Supabase (ключ передаётся заголовком). В `APP_ENV=development`
  traceback'и видны полностью. Это узкая гигиена, а не общая система редактирования, и она не
  защищает от владельца хоста или скомпрометированного процесса.

## 9. Не реализовано и ограничения

Отложено (возвращается в `GET /api/v1/settings → deferred`): `admin_connections_write`,
`ai_assisted_rewards`, `signup`, `password_recovery`, `guardian_management`, `wallet_adjustments`,
`chore_exceptions`. Подробнее:

- AI-оценка наград и «письмо хранителя»; вызовов OpenAI нет — награды только по политике v1.
- Запись подключений и `.env` из интерфейса (`PATCH /settings`, `/admin/connections` отсутствуют).
- Регистрация, восстановление пароля, вход ребёнка без e-mail.
- API связывания взрослых и детей и управления ролями — только SQL оператора.
- Корректировки кошелька; исключения для поручений (каникулы/болезнь).
- Награды за чтение и свои цели; мгновенные награды за добровольные дела.
- Экспорт и удаление данных через API (удаление — ручная процедура); API чтения аудита.
- Распределённый лимитер и фоновый планировщик; горизонтальное масштабирование.
- Демо-данные/seed для разработки.
- Часовой пояс ребёнка меняет только взрослый — **намеренно** (защита окон наград), это не пробел.

Известная ошибка (низкая важность, не исправлена): `GET` с NUL-байтом в пути SPA (`/some%00route`)
отвечает 500. Причина — `ValueError` в `Path.resolve()` SPA-обработчика в `backend/app/main.py`. Ответ —
JSON-ошибка с `request_id`, без утечки данных (находка QA 2026-10-07).

Ограничения проверки: живой Supabase (Auth, JWKS, RLS/Data API) не проверялся; GitHub Actions удалённо
не запускался; тесты на PostgreSQL 17 в последнем раунде не перезапускались. Счётчики и их
область — [DEVELOPMENT.md §4](DEVELOPMENT.md#4-тесты-и-проверки), исторический отчёт DevOps —
[DEVOPS-HANDOFF.md](DEVOPS-HANDOFF.md) §7.
