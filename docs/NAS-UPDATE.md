# Обновление «Всё успею» на домашнем Synology

**Для уже работающей установки** из [NAS-FIRST-INSTALL.md](NAS-FIRST-INSTALL.md):
`http://192.168.1.97:18080`, проект Compose `time-for-everything_deploy`, образ переносится файлом.

Этот документ описывает **обновление**, а не установку заново. Он сохраняет всё, что уже настроено на NAS:

- NAS-копию `compose.production.yaml` с портом **18080** через `TFE_HTTP_PORT`, привязкой к
  `192.168.1.97` и **закомментированным** `# cpus: 1.0`;
- `deploy.env`, в котором меняется **только строка `TFE_IMAGE`**;
- секретный `config/app.env` — его не пересоздаём, не перезаписываем и не выводим на экран;
- базу Supabase: никаких `db_reset.py`. **В этом релизе миграций нет** (подтверждается командой в шаге 3
  быстрого пути); общий порядок для будущих релизов с миграциями вынесен в [раздел 5](#5-миграции-базы--в-этом-релизе-не-требуются).

Каждая сборка получает **новый тег**. Старый образ остаётся на NAS для отката.

> **Этот документ ничего не выполняет за вас.** Коммит, push, сборку и перенос выполняете вы сами.
> Команды ниже не вызывают `git add .`, `git push --force`, `docker system prune` и не копируют поверх
> ваших файлов на NAS.

---

## Быстрый путь для этого обновления

Короткая последовательность. Подробности, ожидаемый вывод и что делать при ошибках — по ссылкам.
Первые четыре шага выполняются при работающем старом контейнере, без простоя.

| # | Где | Что сделать | Подробно |
|---|---|---|---|
| 1 | NAS | Узнать **фактический** работающий образ — это образ для отката. Сохранить копии `deploy.env` и compose; убедиться, что в compose порт 18080 и `# cpus` | [4.1–4.3](#41-записать-что-работает-сейчас) |
| 2 | Mac | Коммит документации отдельно; коммит функциональности **точным списком файлов**; скан секретов выгрузки индекса/`HEAD`; `push origin main`; зелёный Source CI | [1.2](#12-проверка-на-секреты--именно-того-что-пойдёт-в-git), [1.3–1.5](#13-коммит-документации--отдельно-по-желанию) |
| 3 | Mac | Проверить: `schema_version=20261006000002` → **миграций нет**. Другое значение — остановиться | [2.1](#21-проверить-версию-схемы) |
| 4 | Mac | Собрать `linux/amd64` с новым тегом `nas-<дата>-<sha7>`, `docker save`, `shasum`, `scp -O` | [2.2](#22-сборка), [3](#3-сохранить-архив-и-перенести-на-nas) |
| 5 | NAS | `sha256sum -c` → `docker load` → проверка `linux/amd64` | [4.4](#44-проверить-архив-и-загрузить-образ) |
| 6 | NAS | `app.env` **не менять**: новые `DB_*` необязательны, действуют значения по умолчанию; HTTP-настройки остаются | [6.4](#64-новые-настройки-appenv--необязательные) |
| 7 | NAS | Заменить только `TFE_IMAGE` → `tfe config -q` → `tfe up -d --no-build --pull never` | [6.1–6.3](#61-заменить-только-tfe_image) |
| 8 | NAS + браузер | `healthy`, `ready`, запущен новый образ; вход, одно действие (таймер), новая функция | [7](#7-проверка-после-обновления) |
| 9 | NAS | При проблеме — вернуть старый `TFE_IMAGE` из шага 1 и `tfe up -d --no-build --pull never` | [8](#8-откат-на-предыдущий-образ) |

Всё, что ниже, — подробное приложение к этим шагам.

---

## 0. Что уже известно и на чём основаны команды

Проверено по локальным файлам на Mac 9 октября 2026 года. **Состояние NAS отсюда не видно:** что
фактически запущено, узнаём на самом NAS через `docker inspect` (раздел 4.1).


| Параметр | Значение |
|---|---|
| Репозиторий приложения | `/Users/fedor/RepoPrompt/time-for-everything`, ветка `main`, remote `origin` → `github.com/matovykh/time-for-everything` |
| Deploy-репозиторий | `/Users/fedor/RepoPrompt/time-for-everything/time-for-everything_deploy`, **отдельный** Git-репозиторий, ветка `main`, remote → `github.com/matovykh/time-for-everything_deploy` |
| Почему deploy не виден в Git приложения | В `.gitignore` приложения есть `/time-for-everything_deploy/`. Коммиты в двух репозиториях делаются отдельно |
| Что попадает в образ | `git archive` **закоммиченного** SHA приложения: только `frontend/`, `backend/app/`, `backend/requirements.txt` (`scripts/stage-context.sh`) |
| Откуда Dockerfile | `time-for-everything_deploy/docker/Dockerfile` и `time-for-everything_deploy/.dockerignore` (рабочие файлы deploy-каталога) |
| Скрипт сборки | `time-for-everything_deploy/scripts/build-local.sh` → `stage-context.sh` → `docker buildx build --load` |
| Базовые образы | `node:24-bookworm-slim` (сборка интерфейса), `python:3.13-slim-bookworm` (запуск); без кэша Docker скачает их из интернета |
| Builder на Mac | `desktop-linux` (звёздочка в `docker buildx ls` стоит у чужого `pdf-book-splitter-builder` — его не трогаем) |
| Платформа NAS | `x86_64` → собираем `linux/amd64` |
| Образ из первой установки (исторически) | По [NAS-FIRST-INSTALL.md](NAS-FIRST-INSTALL.md): `time-for-everything:nas-20261009-114259`, приложение `028fbb75…`. **Это запись в инструкции, а не наблюдение сегодня** — истина на NAS: `docker inspect` контейнера (раздел 4.1) |
| Версия схемы, которую требует код | `20261006000002` (`REQUIRED_SCHEMA_VERSION` в `backend/app/db/session.py`; последняя миграция `20261006000002_session_revocations.sql`) |
| Миграции в этом релизе | **Нет.** В `supabase/migrations/` только две исходные миграции, `REQUIRED_SCHEMA_VERSION` не изменился. На собранном коммите это проверяет раздел 2.1 |
| Новые настройки в этом релизе | Параметры подключения к базе `DB_*`, **все необязательные**, со значениями по умолчанию (раздел 6.4) |
| Миграции | `supabase/migrations/*.sql` + `scripts/db_migrate.py` приложения; сервер **сам миграции не применяет** |
| Неизвестные ключи в `app.env` | Игнорируются (`extra="ignore"` в `backend/app/core/config.py`) — старый образ не сломается от новых ключей |

Файлы, нужные для сборки, найдены все: `frontend/package.json`, `frontend/package-lock.json`,
`backend/requirements.txt`, `backend/app/main.py`, Dockerfile, `.dockerignore`. `frontend/dist/`
игнорируется Git и собирается внутри Docker — это нормально.

**Важно: в образ попадает только закоммиченное.** Новый файл, который не добавлен в коммит
(например, новый компонент или новая миграция), в образ **не попадёт**, даже если лежит на диске.

### Особенности именно вашего Mac

- `pg_dump` **не установлен**. Для этого релиза он не нужен (миграций нет); понадобится в будущем
  релизе с миграциями (раздел 5).
- `gh` (GitHub CLI) не установлен: результат CI смотрите на сайте GitHub, вкладка **Actions**.
- В `~/tfe-transfer` лежит старый архив с неверсионированным именем `time-for-everything.tar`.
  Новые архивы ниже получают имя с тегом, чтобы их нельзя было перепутать.
- **В рабочей копии deploy-репозитория изменён `compose/compose.production.yaml`:** там жёстко записано
  `"192.168.1.97:8000:8000"` и активный `cpus: 1.0`. **Эта версия не подходит для вашего NAS**
  (порт 8000 занят, `cpus` не поддерживается ядром). Её **не копируем на NAS** и не используем как
  образец. Рабочая конфигурация — копия, которая уже лежит на NAS.

---

## 1. Сохранить изменения в Git (на Mac)

**Где: новое окно «Терминал» на Mac.**

```sh
cd /Users/fedor/RepoPrompt/time-for-everything
/bin/bash --noprofile --norc
APP=/Users/fedor/RepoPrompt/time-for-everything
DEPLOY="$APP/time-for-everything_deploy"
```

### 1.1. Посмотреть, что изменено

```sh
git -C "$APP" status --short
git -C "$APP" diff --stat
```

Буквы слева: `M` — изменён, `??` — новый, ещё не отслеживаемый файл, `D` — удалён.

Изменения в приложении делятся на три группы.

**А. Ваши предыдущие изменения документации** — были до начала этих работ:

```text
 M README.md
 M docs/ARCHITECTURE.md
 M docs/README.md
 M supabase/README.md
?? docs/NAS-FIRST-INSTALL.md
?? docs/RELOCATION-AUDIT.md
?? docs/SETUP-SUPABASE-SYNOLOGY.md
```

**Б. Эта инструкция** — новый файл, создан в рамках текущего обновления:

```text
?? docs/NAS-UPDATE.md
```

**В. Новая функциональность** (backend, frontend, тесты, шаблоны настроек) — точный список
в разделе 1.4.

**Каждый файл в `status` должен попасть в одну из групп.** Если видите что-то сверх этого,
в том числе `.env`, `app.env`, `*.tar`, `*.dump`, ключи, — не добавляйте и остановитесь.
Исключение: шаблоны `.env.example` и `backend/.env.example` — в них только заглушки, они
входят в группу В.

### 1.2. Проверка на секреты — именно того, что пойдёт в Git

Сканер `tests/security/scan_secrets.py` без аргументов проверяет **все файлы на диске**,
включая игнорируемые Git. На вашем Mac такой полный запуск **не проходит**: он находит HIGH
`postgres_dsn_with_password` в `.claude/settings.local.json` — локальном файле настроек инструментов,
который игнорируется Git. **Не открывайте и не выводите этот файл в терминал или чат.**
Чистить его для коммита не нужно; нужно лишь гарантировать, что он никогда не попадёт в Git.
(Удалить из него пароли и, если они настоящие, сменить их — разумно, но это отдельное решение.)

Поэтому сканируем **точную выгрузку** того, что будет закоммичено. Сам сканер и его правила
не меняем и не обходим.

**А. Перед каждым `git commit`** (после `git add` в 1.3 и 1.4) — выгрузка индекса, то есть
всех отслеживаемых файлов в том виде, в котором они попадут в коммит:

```sh
git -C "$APP" diff --cached --name-only -- .claude
git -C "$APP" ls-files -- .claude/settings.local.json
git -C "$APP" check-ignore -v .claude/settings.local.json

EXPORT=$(mktemp -d "${TMPDIR:-/tmp}/tfe-scan.XXXXXX")
git -C "$APP" checkout-index -a --prefix="$EXPORT/"
"$APP/backend/.venv/bin/python" -I "$APP/tests/security/scan_secrets.py" "$EXPORT"; echo "exit=$?"
rm -rf -- "$EXPORT"
```

- Первые две команды — **пустой вывод**: из `.claude/` ничего не добавлено, `settings.local.json`
  не отслеживается. Если что-то выведено — `git -C "$APP" restore --staged -- .claude` и не коммитьте.
- Третья печатает правило `.gitignore`, которое скрывает файл. Никогда не используйте `git add -f`.
- Сканер должен завершиться с **`exit=0`** и без строк `HIGH`. Любая HIGH в выгрузке — блокер,
  в том числе в тестах: например, поддельная строка подключения с паролем в `backend/tests/…` тоже
  исправляется в тесте, а не обходится. Сканер показывает файл и строку, сам секрет —
  только в сокращённом виде.

**Б. Перед `git push`** — выгрузка ровно того коммита, который уйдёт на GitHub и будет собран:

```sh
EXPORT=$(mktemp -d "${TMPDIR:-/tmp}/tfe-scan.XXXXXX")
git -C "$APP" archive HEAD | tar -x -C "$EXPORT"
"$APP/backend/.venv/bin/python" -I "$APP/tests/security/scan_secrets.py" "$EXPORT"; echo "exit=$?"
rm -rf -- "$EXPORT"
```

Ожидается `exit=0`. В CI (Source CI) тот же сканер запускается по чистому checkout — это
независимая вторая проверка. Полный запуск по диску без аргументов можно делать для справки,
но считать его пройденным нельзя, пока в `.claude/settings.local.json` лежат строки с паролями.

### 1.3. Коммит документации — отдельно (по желанию)

Группы А и Б удобно сохранить **отдельным коммитом**, чтобы документация не смешивалась
с кодом. Решение за вами: группу А можно закоммитить и отдельно от Б. Добавляем **явные пути**,
не `git add .`:

```sh
git -C "$APP" add -- README.md docs/ARCHITECTURE.md docs/README.md supabase/README.md \
  docs/NAS-FIRST-INSTALL.md docs/RELOCATION-AUDIT.md docs/SETUP-SUPABASE-SYNOLOGY.md docs/NAS-UPDATE.md
git -C "$APP" diff --cached --stat
```

Убедитесь, что в списке `--cached` только эти файлы. Затем:

```sh
git -C "$APP" commit -m "docs: NAS first install, relocation audit and update runbook"
```

Документация не попадает в образ, поэтому этот коммит на сборку не влияет. Он нужен, чтобы рабочая
копия была чистой, а `HEAD`, из которого собирается релиз, содержал и инструкции.
Если агенты ещё правят `README.md` или `docs/*`, сделайте этот коммит **после** их завершения.

### 1.4. Коммит новой функциональности

Сначала снова посмотрите оставшиеся изменения, включая новые файлы во вложенных папках:

```sh
git -C "$APP" status --short --untracked-files=all
```

Добавляйте **только поименно перечисленные файлы**, не папки целиком (`backend/app`, `frontend/src`,
`tests` и т. п. могут захватить случайные файлы).

> **Итоговый список исправлений проверен 10 октября 2026 года.** Перед коммитом
> сверьте его с `status`: более поздние или посторонние изменения не добавляйте автоматически.

```sh
git -C "$APP" add -- \
  .env.example \
  backend/.env.example \
  backend/app/core/config.py \
  backend/app/core/deps.py \
  backend/app/core/errors.py \
  backend/app/db/errors.py \
  backend/app/db/session.py \
  backend/app/modules/administration/router.py \
  backend/tests/test_db_robustness.py \
  docs/API.md \
  frontend/src/app/App.tsx \
  frontend/src/app/session.tsx \
  frontend/src/features/auth/AuthScreens.tsx \
  frontend/src/shared/api/client.ts \
  frontend/src/shared/api/endpoints.ts \
  frontend/src/shared/ui/States.tsx \
  frontend/src/test/mockApi.ts \
  frontend/src/test/resilience.test.tsx
```

- `backend/app/db/errors.py`, `backend/tests/test_db_robustness.py`, `frontend/src/test/resilience.test.tsx` —
  **новые** файлы (`??`). Особенно важен `backend/app/db/errors.py`: Без него сборка из коммита получится без
  модуля, который импортирует код, и не запустится. Проверяйте каждый `??` в итоговом списке.
- Шаблоны `.env.example` и `backend/.env.example` коммитятся вместе с кодом настроек.
  Перед добавлением убедитесь через `git -C "$APP" diff -- .env.example backend/.env.example`, что там
  только заглушки и числа по умолчанию, без настоящих адресов и ключей.
- Новые или изменённые тесты (`backend/tests/…`, `tests/…`, `frontend/src/test/…`) добавляются
  так же поименно — в образ они не попадают, но нужны CI.
- В этом релизе **нет** файлов `supabase/migrations/…`. Если такой файл появился в `status`,
  это уже другой релиз: остановитесь и перечитайте раздел 5.
- Если изменился `frontend/package.json`, добавляйте его вместе с `frontend/package-lock.json`.

Проверьте, что именно уйдёт в коммит:

```sh
git -C "$APP" diff --cached --stat
git -C "$APP" status --short
```

В выводе `status` строки с буквой в **первой** колонке будут закоммичены; строки `??` и ` M`
(буква во второй колонке) — нет. После коммита в `status` не должно остаться ничего из
`backend/app/`, `frontend/` из списка исправлений — иначе исправления не попадут в образ.
Посторонние изменения документации можно оставить незакоммиченными: сборка использует выбранный SHA.

```sh
git -C "$APP" commit -m "<короткое описание изменений>"
```

### 1.5. Отправить на GitHub

Сначала выполните проверку **Б** из раздела 1.2 (выгрузка `HEAD`) — `exit=0`. Затем:

```sh
git -C "$APP" push origin main
git -C "$APP" fetch origin
git -C "$APP" status -sb
```

Первая строка должна быть `## main...origin/main` **без** `[ahead …]` или `[behind …]`.
Если push отклонён (`rejected`, `non-fast-forward`) — остановитесь. Не используйте `--force`:
сначала выясните, откуда на GitHub взялись чужие коммиты.

Откройте `https://github.com/matovykh/time-for-everything/actions` и дождитесь зелёного
**Source CI** для этого коммита. Красный CI — повод не выкатывать сборку на NAS.

### 1.6. Deploy-репозиторий

Сборка использует `docker/Dockerfile`, `.dockerignore` и `scripts/` **из рабочего каталога** deploy.
Они должны совпадать с закоммиченной версией:

```sh
git -C "$DEPLOY" status --short -- docker .dockerignore scripts
```

**Ожидается пустой вывод.** Если там что-то есть — остановитесь: сборка была бы невоспроизводимой.

Остальные изменения deploy-репозитория (`README.md`, `docs/*`, `compose/compose.production.yaml`)
на сборку не влияют. Коммитить их для этого обновления **не требуется**. Если решите сохранить их
отдельно, учтите: изменённый compose с `192.168.1.97:8000:8000` и активным `cpus: 1.0` не
соответствует вашему NAS — обдумайте это до коммита. Push deploy-репозитория:
`git -C "$DEPLOY" push origin main`, тоже без `--force`.

---

## 2. Собрать новый образ (на Mac)

**Где: тот же Bash. Docker Desktop запущен.**

```sh
APP_SHA=$(git -C "$APP" rev-parse HEAD)
APP_SHORT=$(git -C "$APP" rev-parse --short=7 HEAD)
DEPLOY_SHA=$(git -C "$DEPLOY" rev-parse HEAD)
TFE_TAG="nas-$(date +%Y%m%d-%H%M%S)-$APP_SHORT"
TFE_IMAGE="time-for-everything:$TFE_TAG"
printf 'APP_SHA=%s\nDEPLOY_SHA=%s\nTFE_IMAGE=%s\n' "$APP_SHA" "$DEPLOY_SHA" "$TFE_IMAGE"
```

Перед этим убедитесь, что рабочая копия чиста (всё нужное закоммичено) и `HEAD` уже отправлен:
`git -C "$APP" status -sb` → только строка `## main...origin/main`.

Запишите `TFE_IMAGE` — например `time-for-everything:nas-20261010-101500-abc1234`.
Тег содержит дату и начало SHA: по нему всегда видно, какая версия кода внутри.

### 2.1. Проверить версию схемы

```sh
bash "$DEPLOY/scripts/source-schema-version.sh" "$APP"
git -C "$APP" ls-tree --name-only "$APP_SHA" -- supabase/migrations/
```

**Ожидается для этого релиза:**

```text
schema_version=20261006000002
supabase/migrations/20261006000001_init.sql
supabase/migrations/20261006000002_session_revocations.sql
```

Это та же версия схемы, что у сейчас работающей установки (её `ready` показывает
`schema: ok` именно для `20261006000002`). Значит, **базу в этом обновлении не трогаем**,
раздел 5 пропускается.

Если вывод другой (другой `schema_version`, лишний файл миграции, ошибка скрипта) —
**остановитесь**: это уже не тот релиз, под который написан быстрый путь.

### 2.2. Сборка

```sh
cd "$DEPLOY"
BUILD_BUILDER=desktop-linux BUILD_PLATFORM=linux/amd64 \
  sh scripts/build-local.sh --app-dir "$APP" --sha "$APP_SHA" --tag "$TFE_IMAGE"
```

Успешное завершение:

```text
Built time-for-everything:nas-…-… (local test image, not a release).
```

- Сборка берёт **закоммиченный** `$APP_SHA`, а не файлы на диске.
- Если видите `Tag … already exists` — заново задайте `TFE_TAG`/`TFE_IMAGE` (раздел 2), **не удаляйте**
  существующие образы.
- Пароли Supabase для сборки не нужны и не передаются.

Проверьте архитектуру:

```sh
docker image inspect --format '{{.Os}}/{{.Architecture}}' "$TFE_IMAGE"
```

Ожидается **`linux/amd64`**. Если `linux/arm64` — образ не запустится на NAS (`exec format error`).

### 2.3. Дополнительная проверка (необязательно, но полезно)

Строит **отдельный** одноразовый образ с поддельными «секретами-приманками» и проверяет, что они нигде
не утекают; базу не трогает. Порт 18080 на Mac может быть занят, поэтому задан 18081:

```sh
SMOKE_BUILDER=desktop-linux SMOKE_PLATFORM=linux/amd64 SMOKE_PORT=18081 \
  sh tests/container_secret_smoke.sh --app-dir "$APP" --sha "$APP_SHA"
```

---

## 3. Сохранить архив и перенести на NAS

### 3.1. На Mac

```sh
umask 077
mkdir -p "$HOME/tfe-transfer"
chmod 700 "$HOME/tfe-transfer"
TAR="time-for-everything-$TFE_TAG.tar"
docker save -o "$HOME/tfe-transfer/$TAR" "$TFE_IMAGE"
cd "$HOME/tfe-transfer"
shasum -a 256 "$TAR" > "$TAR.sha256"
printf 'APP_SHA=%s\nDEPLOY_SHA=%s\nTFE_IMAGE=%s\nSCHEMA=%s\n' "$APP_SHA" "$DEPLOY_SHA" "$TFE_IMAGE" \
  "$(bash "$DEPLOY/scripts/source-schema-version.sh" "$APP")" > "build-info-$TFE_TAG.txt"
ls -l "$TAR" "$TAR.sha256" "build-info-$TFE_TAG.txt"
```

Архив около 80 МБ. Он содержит код приложения, но не пароли — всё равно не публикуйте его.

### 3.2. Перенос — `scp -O` (буква O)

```sh
scp -O "$HOME/tfe-transfer/$TAR" "$HOME/tfe-transfer/$TAR.sha256" \
  "$HOME/tfe-transfer/build-info-$TFE_TAG.txt" \
  fedor.matovykh@192.168.1.97:/volume1/docker/tfe-transfer/
```

Предупреждение `Could not chdir to home directory…` ожидаемо и не мешает.

**Не переносите** `compose.production.yaml`, `install-config.sh` и `app.env.example`: на NAS они уже
настроены, а копия с Mac затёрла бы порт 18080 и отключённый лимит CPU. Новые настройки
этого релиза вписываются вручную и только при необходимости (раздел 6.4).

---

## 4. Подготовить NAS: снимок текущего состояния и загрузка образа

Приложение продолжает работать на старом образе всё это время.

```sh
ssh fedor.matovykh@192.168.1.97
```

**Дальше — на NAS.** Вставьте блок целиком (функция живёт до конца SSH-сессии):

```sh
D=/volume1/docker/time-for-everything_deploy
T=/volume1/docker/tfe-transfer
tfe() {
  sudo docker compose --project-name time-for-everything_deploy \
    --env-file "$D/compose/deploy.env" \
    -f "$D/compose/compose.production.yaml" "$@"
}
```

### 4.1. Записать, что работает сейчас

Источник истины — **запущенный контейнер**, а не документация и не память:

```sh
tfe ps
OLD_CID=$(tfe ps -q app)
sudo docker inspect --format '{{.Config.Image}}' "$OLD_CID"
sudo docker inspect --format '{{.Image}}' "$OLD_CID"
sudo cat "$D/compose/deploy.env"
curl -sS http://192.168.1.97:18080/api/v1/health/ready
```

- Первая `inspect` показывает имя образа, с которым контейнер реально создан. **Это и есть образ для
  отката** — запишите его. По NAS-FIRST-INSTALL это был бы `time-for-everything:nas-20261009-114259`,
  но верите выводу команды.
- Вторая — ID этого образа (`sha256:…`), тоже запишите.
- `TFE_IMAGE` в `deploy.env` должен совпадать с первой строкой. Если не совпадает — файл меняли
  без пересоздания контейнера; остановитесь и разберитесь, прежде чем продолжать.
- `ready` до обновления должен быть `ready` с `schema: ok`. Если уже сейчас что-то не так,
  запишите ответ: так вы сможете отличить прежнюю проблему от новой.

В `deploy.env` нет секретов, его можно показывать. `app.env` на экран не выводим.

### 4.2. Резервные копии файлов конфигурации на NAS

```sh
TS=$(date +%Y%m%d-%H%M%S)
sudo cp -p "$D/compose/deploy.env" "$D/compose/deploy.env.bak-$TS"
sudo cp -p "$D/compose/compose.production.yaml" "$D/compose/compose.production.yaml.bak-$TS"
sudo ls -l "$D/compose/"
echo "$TS"
```

Запишите значение `TS`. `-p` сохраняет владельца и права. Резервную копию `app.env` делаем только если
он будет меняться (раздел 6.4).

### 4.3. Убедиться, что NAS-compose сохранил ваши правки

```sh
sudo grep -nE 'ports:|192\.168\.1\.97|cpus|mem_limit|pids_limit' "$D/compose/compose.production.yaml"
sudo grep -n 'TFE_HTTP_PORT' "$D/compose/deploy.env"
```

Ожидается примерно:

```text
      - "192.168.1.97:${TFE_HTTP_PORT:-8000}:8000"
    mem_limit: 512m
    # cpus: 1.0
    pids_limit: 128
TFE_HTTP_PORT=18080
```

Если `cpus` **без** `#` или порт другой — **ничего не меняйте вслепую**: значит, compose на NAS уже
не тот, что описан в NAS-FIRST-INSTALL, сначала разберитесь.

### 4.4. Проверить архив и загрузить образ

Задайте **своё** имя тега из раздела 2 (замените пример):

```sh
TFE_TAG=nas-20261010-101500-abc1234
NEW_IMAGE="time-for-everything:$TFE_TAG"
TAR="time-for-everything-$TFE_TAG.tar"
```

```sh
df -h /volume1
cd "$T"
cat "build-info-$TFE_TAG.txt"
sha256sum -c "$TAR.sha256"
```

Ожидается `time-for-everything-nas-…tar: OK`. **Только после `OK`:**

```sh
sudo docker load -i "$T/$TAR"
sudo docker image inspect --format '{{.Os}}/{{.Architecture}}' "$NEW_IMAGE"
sudo docker image ls time-for-everything
```

Нужны `Loaded image: time-for-everything:nas-…` с вашим тегом и `linux/amd64`. В списке образов
должны быть **оба**: образ для отката из раздела 4.1 и новый.

---

## 5. Миграции базы — в этом релизе не требуются

**Для этого обновления раздел пропускается целиком.** Раздел 2.1 показывает
`schema_version=20261006000002` и только две исходные миграции; базу не трогаем, `DATABASE_URL` на Mac
не вводим, `pg_dump` не нужен. Переходите к разделу 6.

Ниже — общий порядок для **будущих** релизов, в которых появятся новые файлы
`supabase/migrations/`. Это единственное место обновления, которое меняет данные Supabase.
**Откат образа после миграций не откатывает базу.**

### 5.0. Какие миграции новые — только от проверенной установленной версии

Сравнивать нужно с версией кода, **действительно работающей на NAS**, а не с SHA из документации.

1. На NAS в разделе 4.1 вы записали имя образа запущенного контейнера (`docker inspect`).
2. Полный SHA этой версии берём из `build-info-<тот-же-тег>.txt` (на Mac в `~/tfe-transfer` или на NAS
   в `/volume1/docker/tfe-transfer`). Первые 7 символов этого SHA должны совпадать с окончанием
   тега `nas-<дата>-<sha7>`.
3. **Если SHA нельзя подтвердить** (нет `build-info`, тег без SHA — как у образа первой установки
   `nas-20261009-114259`, несовпадение sha7) — **остановитесь**. Не подставляйте SHA из инструкции
   по памяти. В такой ситуации список допустимо определить только по самой базе — пробным
   запуском из 5.2, без `--apply`, и с пониманием каждой ожидающей миграции.

```sh
INSTALLED_SHA=<полный SHA из build-info установленного тега>
git -C "$APP" cat-file -e "$INSTALLED_SHA^{commit}" && \
  git -C "$APP" diff --name-status "$INSTALLED_SHA" "$APP_SHA" -- supabase/migrations
```

- Только строки `A supabase/migrations/…sql` — новые миграции, продолжайте с 5.1.
- `M` или `D` у старых миграций — остановитесь: уже применённые миграции менять нельзя.
- `cat-file` с ошибкой (коммита нет в репозитории) — остановитесь.

Окончательная истина о том, что будет применено, — список `Pending migrations` пробного запуска
в 5.2: он читает журнал версий из самой базы. Он должен совпасть со списком `A` выше.

### 5.1. Проверка на Mac без подключения

**На Mac** (второе окно терминала; NAS-сессию не закрывайте). Рабочая копия должна точно
соответствовать собранному коммиту:

```sh
cd /Users/fedor/RepoPrompt/time-for-everything
/bin/bash --noprofile --norc
git rev-parse HEAD
git status --short -- supabase scripts backend/app/db
backend/.venv/bin/python -I scripts/db_migrate.py --offline
```

`HEAD` должен совпадать с `APP_SHA` из `build-info`, `status` — пустой. Иначе миграции и образ будут от
разных версий — остановитесь.

### 5.2. Резервная копия — обязательна

На Mac нет `pg_dump`. Нужен клиент PostgreSQL **не старше** версии сервера Supabase. Установка — ваше
решение (например, `libpq` через Homebrew); проверьте `pg_dump --version`. **Без резервной копии
миграцию не применяйте.**

```sh
read -r -s -p 'Вставьте DATABASE_URL и нажмите Enter: ' DATABASE_URL
printf '\n'
export DATABASE_URL
backend/.venv/bin/python -I scripts/db_migrate.py
```

Проверьте строку `Target:` — **ваш** проект и pooler, и что в `Pending migrations` перечислены
**только** новые файлы из раздела 5.0. Что-то другое — `unset DATABASE_URL` и остановитесь.

**На NAS** остановите приложение, чтобы копия была согласованной:

```sh
tfe stop
```

**На Mac:**

```sh
mkdir -p "$HOME/.tfe-admin/backups"
chmod 700 "$HOME/.tfe-admin/backups"
umask 077
PGDATABASE="$DATABASE_URL" pg_dump --schema=public -Fc \
  -f "$HOME/.tfe-admin/backups/public-$(date +%Y%m%d-%H%M%S).dump"
ls -l "$HOME/.tfe-admin/backups/"
```

Файл должен быть ненулевого размера. Это копия схемы `public` — **не** полная копия Supabase Auth.

### 5.3. Применить

```sh
backend/.venv/bin/python -I scripts/db_migrate.py --apply
backend/.venv/bin/python -I scripts/db_migrate.py
unset DATABASE_URL
```

Ожидается `Applied …` для каждой новой миграции, затем `Schema is up to date.`
При ошибке: **не запускайте старый контейнер вслепую и не используйте `db_reset.py`**.
Каждая миграция идёт в своей транзакции; ошибочная откатывается целиком, но предыдущие уже применены.
Остановитесь и разберите сообщение.

Переходите к разделу 6 (приложение на NAS пока остановлено).

---

## 6. Переключить NAS на новый образ

**На NAS**, в той же SSH-сессии (`tfe`, `D`, `NEW_IMAGE` заданы). Если подключение обрывалось,
снова выполните блоки из начала раздела 4 и 4.4 (только переменные, без `docker load`).

### 6.1. Заменить только TFE_IMAGE

```sh
sudo sed -i "s|^TFE_IMAGE=.*|TFE_IMAGE=$NEW_IMAGE|" "$D/compose/deploy.env"
sudo cat "$D/compose/deploy.env"
```

Ожидается ровно три строки, изменилась только первая:

```dotenv
TFE_IMAGE=time-for-everything:nas-…-…
TFE_HTTP_PORT=18080
TFE_CONFIG_FILE=/volume1/docker/time-for-everything_deploy/config/app.env
```

Если результат другой — верните копию:
`sudo cp -p "$D/compose/deploy.env.bak-$TS" "$D/compose/deploy.env"` и отредактируйте через
`sudo vi -n "$D/compose/deploy.env"` (как в NAS-FIRST-INSTALL, шаг 11).

### 6.2. Проверить конфигурацию до запуска

```sh
tfe config -q
tfe config | grep -nE 'image:|host_ip|published|target: 8000|cpus'
```

- `config -q` — без вывода и без ошибки.
- Должны быть `image: time-for-everything:nas-…` (новый), `host_ip: 192.168.1.97`,
  `published: "18080"`. Строки `cpus` быть **не должно**.

`tfe config` выводит только compose-настройки; содержимое `app.env` в него не попадает.

### 6.3. Пересоздать контейнер

```sh
tfe up -d --no-build --pull never
```

Compose видит, что образ изменился, и пересоздаёт только контейнер `app`.
`--pull never` — образ берётся из загруженного, Docker Hub не используется.
Предупреждение `PIDs limit discarded` для этого NAS ожидаемо; **другие ошибки не игнорируйте**.

Если в разделе 5 приложение было остановлено, эта же команда его запустит.

### 6.4. Новые настройки `app.env` — необязательные

**Для обновления в `app.env` ничего добавлять не нужно.** Релиз добавляет параметры
подключения к базе; если строки нет, действует значение по умолчанию из кода
(`backend/app/core/config.py`; список с комментариями — `backend/.env.example`).

**Существующие строки не меняйте**, особенно согласованный HTTP-вариант:
`APP_ENV=development`, `APP_BASE_URL=http://192.168.1.97:18080`, `COOKIE_SECURE=false`. Шаблоны
`backend/.env.example` и `config/app.env.example` используют `production`/HTTPS-значения — из них **нельзя**
копировать файл целиком поверх вашего `app.env`.

| Ключ | По умолчанию | Допустимо | Что делает |
|---|---|---|---|
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | 1–60 | libpq `connect_timeout`: ограничивает **только установление соединения**, не длительность запроса |
| `DB_TCP_KEEPALIVES` | `true` | true/false | TCP keepalive: замечает «молча умершее» сетевое соединение |
| `DB_TCP_KEEPALIVES_IDLE_SECONDS` | `30` | 1–7200 | libpq `keepalives_idle` |
| `DB_TCP_KEEPALIVES_INTERVAL_SECONDS` | `10` | 1–600 | libpq `keepalives_interval` |
| `DB_TCP_KEEPALIVES_COUNT` | `3` | 1–30 | libpq `keepalives_count` |
| `DB_TCP_USER_TIMEOUT_MS` | `30000` | 0–600000 | libpq `tcp_user_timeout` (действует на Linux, то есть в контейнере на NAS); `0` — значение ОС |
| `DB_MAX_OVERFLOW` | пусто = как `DB_POOL_SIZE` | 0–50 | Дополнительные соединения сверх пула |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | 1–300 | Сколько ждать свободное соединение из пула |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | 60–86400 | Переоткрывать соединения старше этого срока |
| `DB_POOL_PRE_PING` | `true` | true/false | Проверять соединение перед выдачей из пула |
| `DB_NULL_POOL` | `false` | true/false | **Только диагностика**: новое соединение на каждый запрос, настройки пула игнорируются, медленнее |
| `DB_READY_TIMEOUT_SECONDS` | `10` | 0.1–120 | Сколько `/api/v1/health/ready` ждёт проверку базы, потом отвечает `database: timeout` |

Важные особенности:

- **Параметры соединения перекрывают одноимённые параметры внутри `DATABASE_URL`.** `connect_timeout`,
  `keepalives`, `keepalives_idle`, `keepalives_interval`, `keepalives_count`, `tcp_user_timeout` всегда
  передаются из настроек `DB_*`, включая значения по умолчанию. Если такой параметр
  когда-то дописывали в строку подключения, теперь задавайте его **явно** через `DB_*`. В строке из
  NAS-FIRST-INSTALL был только `?sslmode=require` — он не затрагивается.
  Во время диагностики в ваш URL добавлялись keepalive-параметры. Чтобы сохранить именно
  те значения, задайте в `app.env` отдельные строки (без изменения пароля или URL):

  ```dotenv
  DB_TCP_KEEPALIVES=true
  DB_TCP_KEEPALIVES_IDLE_SECONDS=10
  DB_TCP_KEEPALIVES_INTERVAL_SECONDS=5
  DB_TCP_KEEPALIVES_COUNT=3
  DB_TCP_USER_TIMEOUT_MS=15000
  ```

  Это не гарантирует восстановление связи с БД. Проверяйте настройки в редакторе,
  а не выводом `app.env` на экран.
- Ни один из этих параметров не ограничивает общую длительность запроса: keepalive и
  `tcp_user_timeout` лишь обнаруживают мёртвый сетевой путь, медленный, но живой сервер они не обрывают.
- `DB_NULL_POOL=true` — инструмент диагностики (исключить «зависшие» соединения пула), **не
  гарантированное исправление**. Включайте его только на время разбора проблемы и
  затем верните `false` (или удалите строку).
- Значение вне допустимого диапазона — `ConfigError` при старте, контейнер не запустится
  (в сообщении — имя настройки, без значения).

**Рекомендуемый порядок:** сначала обновите образ с неизменным `app.env` и пройдите
раздел 7. Меняйте `DB_*` потом, **по одной настройке** и только если есть причина,
чтобы было понятно, что именно повлияло.

Если решили задать настройку (на NAS):

```sh
sudo cp -p "$D/config/app.env" "$D/config/app.env.bak-$TS"
sudo vi -n "$D/config/app.env"
```

В `vi`: `i` → допишите **новую** строку в конец, например `DB_READY_TIMEOUT_SECONDS=10` → **Esc** →
`:wq` → Enter. Старые строки не трогайте. Затем:

```sh
sudo chown 10001:10001 "$D/config/app.env"
sudo chmod 600 "$D/config/app.env"
sudo ls -ln "$D/config/app.env"
tfe up -d --no-build --pull never --force-recreate
```

Ожидается `-rw-------` и `10001 10001`. `--force-recreate` нужен: само изменение `app.env` Compose
не замечает. После этого — снова раздел 7.1. `install-config.sh` для существующего
файла **не запускайте** — он откажется перезаписывать, и это правильно.

При откате на старый образ новые строки `DB_*` мешать не будут: неизвестные ключи
игнорируются (`extra="ignore"`).

---

## 7. Проверка после обновления

### 7.1. Контейнер и база (на NAS)

```sh
tfe ps
```

Сначала `health: starting`; через 20–30 секунд повторите — нужно `(healthy)` и
`192.168.1.97:18080->8000/tcp`.

Убедитесь, что запущен **именно новый** образ:

```sh
NEW_CID=$(tfe ps -q app)
sudo docker inspect --format '{{.Config.Image}}' "$NEW_CID"
sudo docker inspect --format '{{.Image}}' "$NEW_CID"
sudo docker image inspect --format '{{.Id}}' "$NEW_IMAGE"
```

Первая строка — новый тег; вторая и третья должны совпадать. (ID сравнивайте только на NAS: на Mac
Docker Desktop может показывать другой формат ID.)

```sh
curl -sS http://192.168.1.97:18080/api/v1/health/live
curl -sS http://192.168.1.97:18080/api/v1/health/ready
```

Ожидается:

```json
{"status":"ok"}
{"status":"ready","checks":{"database":"ok","schema":"ok","auth":"configured"},"setup":[]}
```

| Ответ | Значение |
|---|---|
| `schema: outdated` / `missing` | В этом релизе не ожидается (схема не менялась). Не запускайте миграции вслепую — откат (раздел 8) и разбор |
| `database: timeout` | База не ответила за `DB_READY_TIMEOUT_SECONDS` (10 с). Повторите через минуту; если сохраняется — сеть/TLS до Supabase |
| `database: unreachable` | Сеть, TLS или учётные данные. Если `app.env` не трогали, сравните с ответом `ready` до обновления (раздел 4.1) |
| `database: error` | Ошибка проверки БД (права, схема) — см. поле `diagnostics` и лог |
| поле `diagnostics` | Содержит только категорию, имя класса ошибки и SQLSTATE, без паролей — им можно делиться при разборе |
| нет ответа / контейнер перезапускается | `tfe logs --tail 50 app`; ищите `ConfigError` (например, недопустимое значение `DB_*`), `Traceback` |

```sh
tfe logs --tail 50 app
```

Нормально: `Application startup complete`. Лог не содержит паролей, но перед отправкой кому-либо
просмотрите его.

### 7.2. Вход и работа (в браузере)

1. Откройте **http://192.168.1.97:18080/** и обновите без кэша: **Command ⌘ + Shift + R**
   (браузер мог запомнить старые файлы интерфейса).
2. До входа красные `401` для `/api/v1/me` и `/api/v1/auth/refresh` в консоли — **норма**.
3. Войдите **тестовым** аккаунтом. Должен открыться ваш профиль с прежними данными: звёзды, история,
   занятия — они хранятся в Supabase и обновлением не затрагиваются.
4. Выполните **одно изменяющее действие**, например запуск и остановку таймера. Это проверяет cookies и
   CSRF: при неправильном адресе получили бы `403 csrf_failed`.
5. Обновите страницу (⌘ + R) — сессия и запись сохранились.
6. Проверьте новую функциональность этого обновления.
7. Выйдите и войдите снова. Если есть взрослый аккаунт — войдите им и убедитесь, что ребёнок виден.

Chrome/Brave с `ERR_ADDRESS_UNREACHABLE` — это разрешение «Локальная сеть» в macOS
(NAS-FIRST-INSTALL, шаг 14), не ошибка обновления.

**Обновление завершено**, когда пройдены 7.1 и 7.2. Сохраните `build-info-<тег>.txt` (на Mac и на NAS):
в следующий раз он подтвердит SHA установленной версии (раздел 5.0).

---

## 8. Откат на предыдущий образ

### Когда откат безопасен

| Ситуация | Можно просто вернуть образ? |
|---|---|
| Новых миграций не было — **случай этого релиза** | **Да** |
| Миграции были | **Нет, не вслепую.** Старый `ready` покажет `schema: ok`, даже если новая схема ему не подходит. Варианты: исправить ошибку новой сборкой (предпочтительно) или восстановить БД из копии раздела 5.2 — данные, созданные после миграции, будут потеряны. Миграций «вниз» нет |
| В `app.env` добавлены новые ключи | Да — старый образ их игнорирует. Если менялись **существующие** значения — верните `app.env.bak-…` |

### Как откатить (на NAS)

```sh
OLD_IMAGE=<имя образа из docker inspect в разделе 4.1>
sudo docker image inspect --format '{{.Id}}' "$OLD_IMAGE"
sudo sed -i "s|^TFE_IMAGE=.*|TFE_IMAGE=$OLD_IMAGE|" "$D/compose/deploy.env"
sudo cat "$D/compose/deploy.env"
tfe config -q
tfe up -d --no-build --pull never
```

Подставьте в `OLD_IMAGE` имя, которое **показал `docker inspect`** в разделе 4.1 (не из документации).
ID из второй команды должен совпасть с записанным там же `sha256:…`. Вместо `sed` можно вернуть всю копию:
`sudo cp -p "$D/compose/deploy.env.bak-$TS" "$D/compose/deploy.env"`.

Затем проверка как в разделе 7: `tfe ps` → `(healthy)`, `ready`, вход, одно действие.
Если меняли `app.env`: `sudo cp -p "$D/config/app.env.bak-$TS" "$D/config/app.env"` и
`tfe up -d --no-build --pull never --force-recreate`.

---

## 9. Уборка (через несколько дней, когда новая версия устоялась)

- **Оставьте на NAS текущий и хотя бы один предыдущий образ.** Не используйте
  `docker image prune -a` и `docker system prune` — они могут удалить образ для отката или образы
  других приложений на NAS.
- Удалять старые образы — только по точному имени:
  `sudo docker image rm time-for-everything:<старый-тег>`, и только не тот, что указан в `deploy.env`.
- Архивы в `/volume1/docker/tfe-transfer` можно удалить по точному имени после успешной проверки:
  `sudo rm -- /volume1/docker/tfe-transfer/time-for-everything-<тег>.tar`. Старый
  `time-for-everything.tar` от первой установки — аналогично. Копии на Mac в `~/tfe-transfer`
  храните приватно, пока версия может понадобиться.
- Файлы `*.bak-<TS>` в `compose/` удаляйте, когда откат к этим настройкам точно не нужен.
  `app.env.bak-*` содержит секреты — не оставляйте его надолго.
- Дампы базы в `~/.tfe-admin/backups` содержат личные данные: храните зашифрованно.

---

## 10. Чего не делать при обновлении

- `git add .`, `git commit -a`, `git push --force`.
- Сборку из незакоммиченных файлов, `--worktree` или `docker build .` из корня репозитория.
- Повторно использовать старый тег или удалять работающий образ, чтобы «освободить» имя.
- Копировать `compose.production.yaml` с Mac поверх NAS-копии; менять порт 18080; раскомментировать
  `cpus`; трогать `user`, `read_only`, `cap_drop`, `security_opt`, монтирование `app.env`.
- Запускать `install-config.sh` повторно, удалять `app.env`, выводить его через `cat`.
- `scripts/db_reset.py` — это удаление данных, не обновление.
- `--apply` миграций без резервной копии и проверки строки `Target`.
- `tfe down -v`, `tfe pull`, `docker system prune`, `docker image prune -a`.

---

## Краткая шпаргалка

| Где | Шаг | Команда / действие |
|---|---|---|
| Mac | Git | `status` → явный `git add -- <пути>` → `commit` → `push origin main` → CI зелёный |
| Mac | Схема не менялась | `source-schema-version.sh` → `schema_version=20261006000002` (иначе стоп) |
| Mac | Сборка | `BUILD_BUILDER=desktop-linux BUILD_PLATFORM=linux/amd64 sh scripts/build-local.sh --app-dir "$APP" --sha "$APP_SHA" --tag "$TFE_IMAGE"` |
| Mac | Архив | `docker save` → `shasum -a 256` → `scp -O` в `/volume1/docker/tfe-transfer/` |
| NAS | Снимок | записать `TFE_IMAGE`, `cp -p` для `deploy.env` и compose |
| NAS | Загрузка | `sha256sum -c` → `docker load` → проверка `linux/amd64` |
| — | Миграции | **В этом релизе нет.** Будущие — раздел 5, только от подтверждённого установленного SHA |
| NAS | Настройки `DB_*` | Необязательны; `app.env` не меняем (раздел 6.4) |
| NAS | Переключение | `sed` только `TFE_IMAGE` → `tfe config -q` → `tfe up -d --no-build --pull never` |
| NAS+браузер | Проверка | `healthy`, `ready`, вход, одно действие, новая функция |
| NAS | Откат | вернуть старый `TFE_IMAGE` → `tfe up -d --no-build --pull never` (только при той же схеме) |
