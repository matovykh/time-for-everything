# Разработка и проверки

Локальный запуск, тесты и работа с макетом. Правила изменений — [CONTRIBUTING.md](../CONTRIBUTING.md);
устройство системы — [ARCHITECTURE.md](ARCHITECTURE.md); контракт — [API.md](API.md).

## 1. Требования

- Python **3.13** (backend, скрипты, тесты).
- Node.js **24** и npm (сборка и тесты frontend; CI использует 24).
- Docker — только для тестов на одноразовом PostgreSQL (необязательно). Образ приложения собирается в
  отдельном репозитории `time-for-everything_deploy`.
- Для работы с реальными данными — **отдельный dev-проект Supabase**. Демо-данных и seed нет.

## 2. Установка зависимостей

Из корня репозитория:

```sh
python3.13 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
```

Корневые `package.json`/`package-lock.json` относятся только к историческому макету `prototype/`.

## 3. Локальный запуск

### Вариант А: одна точка входа (как в production)

Backend раздаёт собранную SPA из `frontend/dist`:

```sh
npm --prefix frontend run build
cp .env.example .env && chmod 600 .env    # или backend/.env.local — любое имя, указанное в CONFIG_FILE
```

Для локального HTTP в файле конфигурации задайте:

```
APP_ENV=development
COOKIE_SECURE=false
APP_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=…            # dev-проект Supabase, sslmode=require
SUPABASE_URL=…
SUPABASE_PUBLISHABLE_KEY=…
```

```sh
cd backend
CONFIG_FILE="$PWD/../.env" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте <http://127.0.0.1:8000/>. Без настроек (`CONFIG_FILE` не задан) приложение тоже запускается:
live 200, ready 503, в браузере — экран «Приложение ещё настраивается». Если `CONFIG_FILE` задан, но файла
нет, он нечитаем или значения неверны, процесс не стартует и пишет одну строку `Configuration error: …`
без значений. В `APP_ENV=development` traceback'и uvicorn выводятся полностью; в остальных режимах — только
имя класса исключения ([ARCHITECTURE.md → Логи](ARCHITECTURE.md#логи-и-их-ограничения); полный контракт
конфигурации — [ARCHITECTURE.md → Контракт конфигурации](ARCHITECTURE.md#контракт-конфигурации)). OpenAPI-документация доступна на
<http://127.0.0.1:8000/api/v1/docs>, только когда `APP_ENV` не `production`.

Если порт 8000 занят, используйте другой (`--port 8010`) и поменяйте `APP_BASE_URL` на
`http://127.0.0.1:8010`. `APP_BASE_URL` всегда должен совпадать с адресом в браузере, иначе действия
получат `403 csrf_failed`.

Перед первым входом примените миграции к dev-проекту ([supabase/README.md](../supabase/README.md),
`scripts/db_migrate.py`) и создайте пользователя в Supabase Dashboard.

### Вариант Б: Vite dev server с горячей перезагрузкой

Запустите backend как в варианте А, затем:

```sh
cd frontend
npm run dev      # http://127.0.0.1:5173, /api проксируется на VITE_BACKEND_ORIGIN (по умолчанию http://127.0.0.1:8000)
```

Браузер открыт на `127.0.0.1:5173`, поэтому для этого режима задайте в backend
`APP_BASE_URL=http://127.0.0.1:5173` (или оставьте пустым — тогда `Origin` сверяется с заголовком
`Host`). Если backend на другом порту: `VITE_BACKEND_ORIGIN=http://127.0.0.1:8010 npm run dev`.

## 4. Тесты и проверки

Команды совпадают с `.github/workflows/ci.yml`. Результаты — локальные прогоны инженера и QA при
разделении репозиториев (2026-10-07, macOS). Единого итогового прогона всех наборов после последних
правок не было: смотрите область каждой строки. Авторитетный результат — первый зелёный Source CI на GitHub.

| Набор | Команда | Каталог | Последний результат (2026-10-07, если не указано иначе) |
|---|---|---|---|
| Backend (SQLite) | `.venv/bin/python -m pytest` | `backend/` | **140 passed, 3 skipped** (только PostgreSQL), полный повторный прогон после всех правок — **2026-10-08** |
| Lint | `.venv/bin/ruff check --config pyproject.toml app tests ../scripts` | `backend/` | без замечаний, повторно **2026-10-08** |
| Независимый QA (SQLite) | `backend/.venv/bin/python -m pytest tests/backend -q` | корень | 1714 passed |
| Эталон политики наград | `python3 -I -m unittest discover -s tests/reference -v` | корень | пройден (код 0) |
| Самотесты сканера | `python3 -I -m unittest discover -s tests/security -v` | корень | пройдены (код 0) |
| Поиск секретов | `python3 -I tests/security/scan_secrets.py [пути…]` | корень | по выбранным путям (`.github README.md docs backend frontend/src tests scripts supabase` + DevOps-каталог) — 0 находок; без аргументов в рабочей копии — находки только в игнорируемом локальном файле инструмента (см. ниже) |
| Frontend типы | `npm run typecheck` | `frontend/` | OK |
| Frontend unit | `npm test` | `frontend/` | 34 passed |
| Frontend QA | `npm run test:qa` | `frontend/` | 28 passed |
| Сборка | `npm run build` | `frontend/` | OK, без `.map` и `sourceMappingURL` |
| Секреты в бандле | `python3 -I ../tests/security/scan_secrets.py "$PWD/dist"` | `frontend/` | 0 находок |
| Наборы на PostgreSQL 17 | см. ниже | — | в последнем раунде **не перезапускались**; прежние результаты исторические ([DEVOPS-HANDOFF.md §3](DEVOPS-HANDOFF.md)) |

Что важно знать о наборах:

- **1714 тестов QA** — это внутрипроцессные API-тесты через FastAPI `TestClient` с настоящей цепочкой
  cookie → JWT → отзыв сессии и подменённым HTTP-транспортом Supabase. Из них **1600** — параметризованные
  случаи сверки политики наград с независимым эталоном (`test_qa_policy_parity.py`: 400 поручения +
  600 прогулка + 600 уроки). Это **не** браузерные end-to-end тесты.
- Frontend-тесты (unit и QA) работают в jsdom с подменёнными ответами API, без настоящего backend.
- Ни один набор не обращается к живому Supabase. Auth, JWKS, RLS/Data API реального проекта
  не проверены.
- Сканер секретов принимает абсолютный путь: относительный аргумент разрешается от корня репозитория.
  В рабочей копии он может находить локальные файлы инструментов, которые игнорируются git (например,
  `.claude/settings.local.json` — такие находки были 2026-10-07; содержимое не открывалось, в Git и CI
  файла нет). Поэтому локально сканируйте конкретные пути или чистый checkout. В CI сканируется весь
  checkout.
- Единственное предупреждение в тестах — устаревание `httpx` в Starlette `TestClient` (только тесты).

### Тесты на PostgreSQL 17

Тесты в режиме PostgreSQL **удаляют и пересоздают схему `public`**. Защита fail-closed: нужна явная
переменная-разрешение, адрес loopback, имя БД `tfe_test[_суффикс]` (backend) или `tfe_qa[_суффикс]`
(QA) и отсутствие Supabase в URL. Никогда не указывайте реальную БД.

```sh
docker run -d --name tfe-pg-local -e POSTGRES_PASSWORD=<local-only> -e POSTGRES_DB=tfe_test \
  -p 127.0.0.1:55450:5432 postgres:17-alpine
docker exec tfe-pg-local createdb -U postgres tfe_qa

# backend (каталог backend/): все тесты, включая только-PostgreSQL, без skipped
TFE_ALLOW_DESTRUCTIVE_TEST_DB=1 \
TEST_DATABASE_URL=postgresql://postgres:<local-only>@127.0.0.1:55450/tfe_test .venv/bin/python -m pytest

# независимый QA (корень)
QA_ALLOW_DESTRUCTIVE_TEST_DB=1 \
QA_TEST_DATABASE_URL=postgresql://postgres:<local-only>@127.0.0.1:55450/tfe_qa \
backend/.venv/bin/python -m pytest tests/backend -q

docker rm -f tfe-pg-local
```

Выберите свободный порт и имя контейнера; не используйте контейнеры и БД, с которыми одновременно
работает кто-то ещё. Миграции на стенде с заглушкой `auth` (`backend/tests/sql/supabase_stub.sql`)
CI проверяет так: `scripts/db_migrate.py --offline`, dry run, `--apply` и повторный `--apply` →
«Schema is up to date.» (задание `postgres` в CI).

### CI

`.github/workflows/ci.yml` (Source CI) содержит задания `backend`, `postgres`, `frontend`; сборки образа
и деплоя в нём нет. Release workflow репозитория `time-for-everything_deploy` публикует образ только для
коммита с успешным push-прогоном этого workflow, поэтому имя файла `ci.yml` менять нельзя без правки там.
Workflow **ни разу не запускался на GitHub**; первый удалённый прогон нужно проконтролировать.

Образ, контейнерные smoke-тесты и запуск через compose — в `time-for-everything_deploy`.

## 5. Изменение схемы

Новая миграция — файл `supabase/migrations/<timestamp>_<name>.sql` (только вперёд, без `begin/commit`,
только объекты `public`), соответствующие ORM-модели в `backend/app/db/models.py`, новая
`REQUIRED_SCHEMA_VERSION` в `backend/app/db/session.py`, тесты на SQLite и PostgreSQL. Приложение не
должно менять схему при старте. Подробнее — [supabase/README.md](../supabase/README.md).

## 6. Исторический макет `prototype/`

Интерактивный HTML/CSS/JS-макет v0.3 — визуальный эталон для `frontend/`. Он **не** подключается к
backend: данные в `localStorage`, демо-профиль «Алексей», 145 демо-звёзд, имитация выхода, заблокированные
поля ключей. Не вводите туда реальные данные и ключи. В Docker-образ макет не входит.

Просмотр (из корня репозитория, нужен только Python):

```sh
python3 -m http.server 8080 --bind 127.0.0.1
# открыть http://127.0.0.1:8080/prototype/ ; остановить — Ctrl+C
```

Сброс демо-данных — в макете «Настройки → Восстановить исходный макет».

Пересборка и smoke-тест (корневой npm-пакет, нужен Chrome или браузер Playwright):

```sh
npm ci
npm run build          # esbuild → prototype/assets/
npm run serve          # тот же http.server на 8080
# в другом терминале (macOS с Chrome):
CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm test
```

`PROTOTYPE_URL` переопределяет адрес тестируемого сервера. Сценарии — [PROTOTYPE-TESTS.md](PROTOTYPE-TESTS.md),
концепция миров — [LIVING-WORLDS.md](LIVING-WORLDS.md), арт — [designs/WORLD-ART-DIRECTION.md](designs/WORLD-ART-DIRECTION.md).
Сборка макета включает source maps (`prototype/assets/*.map`); к рабочему frontend это не относится.
