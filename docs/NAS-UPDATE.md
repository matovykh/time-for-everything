# Обновление «Всё успею» на домашнем Synology — восстановительный релиз

> **Исторический документ (13 октября 2026). Не выполняйте его для текущего релиза.**
>
> - Он описывает выкладку **диагностического** коммита `7b86c59` (`recovery/provisioning-diagnostics`) на NAS.
>   Этот шаг пройден: образ `time-for-everything:nas-20261012-181921-7b86c59` собран.
> - Проверка на Mac показала: **без VPN** SQL-запросы к Supabase из домашней сети завершаются таймаутом,
>   **с VPN** тот же образ до базы достучался. Поэтому приложение запускается **на Mac в Docker Desktop** с VPN
>   для домашней сети:
>   `docs/MAC-RUN.md` (первый запуск, ежедневная работа) и `docs/MAC-UPDATE.md` (коммит очистки, сборка,
>   переключение, откат) в deploy-репозитории `time-for-everything_deploy`.
> - Диагностика `login_stage` после этого **удалена** из кода (см. баннер в
>   [LOGIN-DIAGNOSTICS.md](LOGIN-DIAGNOSTICS.md)). Блоки ниже со списком «ровно шесть файлов» и проверкой имён
>   этапов к текущему коду не подходят и остановятся.
> - Конфигурация на NAS (compose, `deploy.env`, `app.env`) этим переходом **не менялась**. Что делать с
>   работающим на NAS контейнером — отдельное решение, в Mac-документах его нет.
> - Раздел «Главные правила» (никаких удалений, самостоятельные блоки в скобках) остаётся образцом и для
>   Mac-документов.

**Релиз:** диагностика этапов создания профиля при входе (`ensure_profile.*`), ветка
`recovery/provisioning-diagnostics`. Установка уже работает: `http://192.168.1.97:18080`, проект Compose
`time-for-everything_deploy`, образ переносится файлом.

Документ описывает **обновление**, а не установку заново. На NAS сохраняется всё, что уже настроено:

- NAS-копия `compose.production.yaml`: адрес **192.168.1.97**, порт **18080** через `TFE_HTTP_PORT`,
  строка `# cpus: 1.0` **закомментирована**;
- в `deploy.env` меняется **только строка `TFE_IMAGE`**;
- секретный `config/app.env` **не меняется, не копируется и не выводится на экран**. В нём остаётся
  `DB_NULL_POOL=true` (раздел 6.3);
- база Supabase не затрагивается: **миграций в этом релизе нет** (раздел 5).

> **Этот документ ничего не выполняет за вас.** Коммит, push, сборку, перенос и переключение на NAS
> выполняете вы сами, по одному блоку.

---

## ⚠ Почему инструкция переписана и главные правила

В прошлой версии этого документа после сканирования стояла строка `rm -rf -- "$EXPORT"`, а следующим
шагом шла команда `git -C "$APP" add -- \ …`. При вставке строки склеились, и `rm` получил в качестве
аргументов `git`, `-C`, **путь репозитория `$APP`** и остальные слова. В результате рабочий репозиторий был
удалён. Нынешняя копия восстановлена по пути
`/Users/fedor/RepoPrompt/ВсёУспею/time-for-everything`.

Поэтому для этого документа действуют жёсткие правила:

1. **Ни одной команды удаления.** Здесь нет `rm`, `rm -rf`, `git clean`, `git reset`, `git checkout -- .`,
   `git stash`, `docker … prune`, `docker image rm`, `tfe down`. Если такая команда «кажется нужной»,
   остановитесь и спросите.
2. **Временные каталоги не удаляются.** Выгрузки для сканирования создаются через `mktemp` в `$TMPDIR`
   (`tfe-scan-index.*`, `tfe-scan-head.*`) и **остаются там**. macOS сама чистит `$TMPDIR`. Блок печатает путь
   к каталогу, этого достаточно.
3. **Каждый блок самостоятелен.** Он начинается с `cd` в существующий каталог, сам заново определяет
   переменные и проверяет их. От переменных, оставшихся от прошлых блоков, ничего не зависит.
4. **Каждый блок выполняется в скобках `( … )`.** При ошибке блок печатает `СТОП: …` и прекращается через
   `exit`, но закрывается только подоболочка, окно терминала остаётся. Копируйте блок **целиком**, от `(`
   до `)`, и вставляйте **по одному**. Дождитесь вывода и прочитайте строку `ОК: …` или `СТОП: …`.
5. **Нет переносов строк через `\`.** Длинные команды записаны одной строкой: склеивание строк, которое
   привело к удалению, здесь невозможно.
6. **Внутри блоков нет комментариев `#` и восклицательных знаков.** zsh по умолчанию не понимает
   комментарии во вставленных командах, а bash в интерактивном режиме воспринимает `!` в кавычках как
   ссылку на историю.
7. **Секреты не выводятся.** Нельзя запускать `cat` для `app.env` или файлов из
   `~/tfe-rescue-20261012-123852`, нельзя показывать `DATABASE_URL`. Сканер секретов печатает только итоговую
   строку, а при находках — только файл и номер строки.
8. **Ничего не отправляется в `main` и ничего не перезаписывается силой.** Коммит и push делаются в ветку
   `recovery/provisioning-diagnostics`, без `--force`.

**На Mac перед первым блоком** откройте новое окно «Терминал» и запустите чистый bash:

```sh
/bin/bash --noprofile --norc
```

Все Mac-блоки ниже рассчитаны на этот bash.

---

## Быстрый путь

| # | Где | Что сделать | Раздел |
|---|---|---|---|
| 1 | Mac | Проверить окружение: каталог, ветку, deploy-репозиторий | [1.1](#11-проверка-окружения-только-чтение) |
| 2 | Mac | Посмотреть изменения, прогнать тесты | [1.2–1.3](#12-что-изменено) |
| 3 | Mac | Добавить в индекс **ровно шесть файлов**, затем сканировать выгрузку индекса: `0 finding(s), 0 HIGH`, `exit=0` | [1.4–1.5](#14-добавить-в-индекс-ровно-шесть-файлов) |
| 4 | Mac | Сделать коммит в `recovery/provisioning-diagnostics`. Блок коммита сам заново сканирует дерево индекса и сверяет `write-tree` с `HEAD^{tree}`. Затем сканировать выгрузку `HEAD`: `exit=0` | [1.6–1.7](#16-коммит) |
| 5 | Mac | Сделать push **этой ветки** (не `main`) и дождаться зелёного Source CI | [1.8](#18-push-ветки-восстановления) |
| 6 | Mac | Проверки перед сборкой: схема `20261006000002`, deploy `bcb583c` чист, имена этапов есть в коммите | [2.1](#21-проверки-перед-сборкой-только-чтение) |
| 7 | Mac | Собрать **закоммиченный** SHA с новым тегом `nas-<дата>-<sha7>`, затем `docker save` и `shasum` | [2.2](#22-сборка-архив-и-контрольная-сумма) |
| 8 | Mac | Перенести архив через `scp -O` | [3](#3-перенос-на-nas) |
| 9 | NAS | Записать работающий образ (ожидается `…nas-20261010-210507-620e834`), сделать копии конфигов, проверить compose | [4.1–4.3](#41-снимок-текущего-состояния-только-чтение) |
| 10 | NAS | Выполнить `sha256sum -c`, затем `docker load` и убедиться, что образ `linux/amd64` | [4.4](#44-проверить-архив-и-загрузить-образ) |
| 11 | NAS | Заменить только `TFE_IMAGE`, затем `tfe config -q` и `tfe up -d --no-build --pull never`. `app.env` не трогать | [6](#6-переключить-nas-на-новый-образ) |
| 12 | NAS + браузер | Убедиться в `healthy` и `ready` и что запущен новый образ; одна попытка входа; лог по [LOGIN-DIAGNOSTICS.md](LOGIN-DIAGNOSTICS.md) | [7](#7-проверка-после-обновления) |
| 13 | NAS | При проблеме вернуть прежний `TFE_IMAGE` | [8](#8-откат) |

---

## 0. Исходные данные (проверено на Mac 12 октября 2026 года)

Состояние NAS отсюда не видно. Что фактически запущено, проверяется на NAS командой `docker inspect`
(раздел 4.1).

| Параметр | Значение |
|---|---|
| Репозиторий приложения (`APP`) | `/Users/fedor/RepoPrompt/ВсёУспею/time-for-everything` — восстановленная копия. Remote `origin` указывает на `https://github.com/matovykh/time-for-everything.git` |
| Буква «ё» в пути | macOS может хранить имя каталога в разложенном виде (`е` + знак `¨`). Файловая система находит каталог в любом варианте, но **строки** могут не совпасть. Поэтому блоки делают `cd` по пути, а значение `APP` берут из `git rev-parse --show-toplevel` и не сравнивают его с набранным текстом. Если `cd` не находит каталог, наберите `cd ` (с пробелом), перетащите папку из Finder в окно терминала и нажмите Enter |
| Ветка | `recovery/provisioning-diagnostics`, основана на `620e834` (`main` и `origin/main` тоже указывают на `620e834`). Upstream у ветки ещё нет |
| Deploy-репозиторий (`DEPLOY`) | `$APP/time-for-everything_deploy`. Это **отдельный** вложенный Git-репозиторий (в `.gitignore` приложения: `/time-for-everything_deploy/`) на коммите `bcb583c`, remote `matovykh/time-for-everything_deploy` |
| Compose в deploy-репозитории | Там записаны `127.0.0.1:${TFE_HTTP_PORT:-8000}:8000` и **активный** `cpus: 1.0`. **Для NAS он не подходит: на NAS его не копировать.** Рабочая конфигурация — копия, которая уже лежит на NAS |
| Что попадает в образ | `git archive` **закоммиченного** SHA: только `frontend/`, `backend/app/`, `backend/requirements.txt` (`scripts/stage-context.sh`). Незакоммиченные файлы в образ не попадают |
| Сейчас на NAS (ожидается) | `time-for-everything:nas-20261010-210507-620e834`: приложение `620e834`, deploy `bcb583c`. Так записано в `~/tfe-transfer/build-info-nas-20261010-210507-620e834.txt`. Окончательно подтверждается командой `docker inspect` в разделе 4.1 |
| Архивы на Mac | `~/tfe-transfer` (права `drwx------`): прежние архивы и `build-info`. Их не трогаем |
| Резервные копии секретов | `~/tfe-rescue-20261012-123852` (права `drwx------`) содержит копию NAS-конфигурации с `app.env`. Каталог **вне репозитория**. Не открывать, не выводить через `cat`, не копировать в репозиторий, не прикладывать к сообщениям. Допустима только проверка прав командой `ls -ld` |
| Версия схемы | `20261006000002` (`REQUIRED_SCHEMA_VERSION`). Миграций две: `…0001_init.sql` и `…0002_session_revocations.sql` |
| Миграции в этом релизе | **Нет** |
| Новые настройки | **Нет.** `app.env` не меняется |
| `NAS-FIRST-INSTALL.md` | Был в старом репозитории, в восстановленной копии его нет. Все нужные факты повторены здесь |

### Состав восстановительного патча — ровно шесть файлов

| Файл | Что изменено |
|---|---|
| `backend/app/core/login_stages.py` | Фиксированный список имён этапов, поле `index=N`, функция `optional_stage` |
| `backend/app/modules/accounts/provisioning.py` | Подэтапы `ensure_profile.*` вокруг **уже существующих** вызовов `get`/`add`/`flush`/`commit`/`rollback`. Новых `flush` не добавлено |
| `backend/app/modules/accounts/router.py` | Вход передаёт свой `request_id` в `ensure_profile` |
| `backend/tests/test_login_diagnostics.py` | Тесты: порядок и число вызовов, отсутствие персональных данных в логе |
| `docs/NAS-UPDATE.md` | Эта инструкция |
| `docs/LOGIN-DIAGNOSTICS.md` | Как читать лог |

`backend/app/db/session.py` в этом патче **не меняется** (он уже изменён в `620e834`).

---

## 1. Git на Mac

Начало каждого Mac-блока одинаковое: `cd` в каталог приложения, вычисление `APP` и проверки. Это
повторение сделано намеренно.

### 1.1. Проверка окружения (только чтение)

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: каталог не является Git-репозиторием"; exit 1; }
DEPLOY="$APP/time-for-everything_deploy"
[ "$(basename "$APP")" = "time-for-everything" ] || { echo "СТОП: неожиданный APP=$APP"; exit 1; }
[ -f "$APP/backend/app/main.py" ] && [ -f "$APP/tests/security/scan_secrets.py" ] || { echo "СТОП: в APP нет файлов приложения"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: текущая ветка не recovery/provisioning-diagnostics"; exit 1; }
[ "$(git -C "$APP" config --get remote.origin.url)" = "https://github.com/matovykh/time-for-everything.git" ] || { echo "СТОП: неожиданный origin"; exit 1; }
[ -d "$DEPLOY" ] || { echo "СТОП: нет deploy-каталога"; exit 1; }
[ "$(git -C "$DEPLOY" config --get remote.origin.url)" = "https://github.com/matovykh/time-for-everything_deploy.git" ] || { echo "СТОП: неожиданный origin deploy"; exit 1; }
echo "APP=$APP"
git -C "$APP" log -1 --format='app    %h %s'
git -C "$DEPLOY" log -1 --format='deploy %h %s'
ls -ld "$HOME/tfe-rescue-20261012-123852" "$HOME/tfe-transfer"
echo "ОК: окружение проверено"
)
```

Ожидается (если коммит из раздела 1.6 ещё не сделан):

```text
APP=/Users/fedor/RepoPrompt/ВсёУспею/time-for-everything
app    620e834 diagnostics: trace login stages safely
deploy bcb583c Initial commit
drwx------ … /Users/fedor/tfe-rescue-20261012-123852
drwx------ … /Users/fedor/tfe-transfer
ОК: окружение проверено
```

Если у `tfe-rescue-…` права шире, чем `drwx------`, выполните `chmod 700 "$HOME/tfe-rescue-20261012-123852"`.
Эта команда меняет только права и ничего не удаляет.

### 1.2. Что изменено

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
git -C "$APP" status --short --untracked-files=all
git -C "$APP" diff --stat
)
```

Ожидаются только шесть файлов из таблицы выше (` M` — изменён). Если видите что-то ещё, особенно `.env`,
`app.env`, `*.tar`, `*.dump`, `*.bak`, ключи, файлы из `.claude/` или `tfe-rescue`, **не добавляйте** это в
коммит. Посторонние незакоммиченные файлы на сборку не влияют, потому что собирается коммит, а не диск.

### 1.3. Тесты (на рабочих файлах)

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything/backend" || { echo "СТОП: нет каталога backend"; exit 1; }
[ -x .venv/bin/python ] || { echo "СТОП: нет backend/.venv"; exit 1; }
.venv/bin/python -m pytest -q || { echo "СТОП: pytest завершился с ошибкой, коммит не делать"; exit 1; }
echo "ОК: pytest"
.venv/bin/ruff check --config pyproject.toml app tests ../scripts || { echo "СТОП: ruff нашёл ошибки, коммит не делать"; exit 1; }
echo "ОК: ruff"
)
```

Ожидаются `ОК: pytest` (у backend-агента было `205 passed, 4 skipped`; пропущены тесты, которым нужна
отдельная PostgreSQL) и `ОК: ruff`. Любой сбой тестов или ruff останавливает блок на строке `СТОП: …`.
Дальше не идите.

### 1.4. Добавить в индекс ровно шесть файлов

`git add` получает только явные пути. Блок проверяет, что в индексе **ровно** эти шесть файлов и ничего
больше. Команда `git add` записана одной строкой.

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(basename "$APP")" = "time-for-everything" ] && [ -f "$APP/backend/app/main.py" ] || { echo "СТОП: неожиданный APP=$APP"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
git -C "$APP" add -- backend/app/core/login_stages.py backend/app/modules/accounts/provisioning.py backend/app/modules/accounts/router.py backend/tests/test_login_diagnostics.py docs/LOGIN-DIAGNOSTICS.md docs/NAS-UPDATE.md || { echo "СТОП: git add не выполнен"; exit 1; }
EXPECTED=$(printf '%s\n' backend/app/core/login_stages.py backend/app/modules/accounts/provisioning.py backend/app/modules/accounts/router.py backend/tests/test_login_diagnostics.py docs/LOGIN-DIAGNOSTICS.md docs/NAS-UPDATE.md)
ACTUAL=$(git -C "$APP" diff --cached --name-only) || { echo "СТОП: не удалось прочитать индекс"; exit 1; }
git -C "$APP" diff --cached --stat
if [ "$ACTUAL" = "$EXPECTED" ]; then echo "ОК: в индексе ровно шесть файлов"; else echo "СТОП: состав индекса отличается. В индексе:"; printf '%s\n' "$ACTUAL"; exit 1; fi
)
```

- Если в индексе есть **лишний** файл, уберите его из индекса командой
  `git -C "$HOME/RepoPrompt/ВсёУспею/time-for-everything" restore --staged -- <точный-путь>`. Команда меняет
  только индекс, содержимое файла на диске остаётся прежним. Затем повторите блок.
- Если какого-то из шести файлов **нет** в списке (он не изменён), остановитесь и выясните почему. Не
  коммитьте неполный патч.
- Никогда не используйте `git add .`, `git add -A`, `git add -f`, `git commit -a`.

### 1.5. Сканирование выгрузки индекса на секреты

Сканируется именно то, что войдёт в коммит: все отслеживаемые файлы в том виде, в каком они лежат в
индексе. Выгрузка проверяется **до** запуска сканера. Временный каталог остаётся на месте.

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(basename "$APP")" = "time-for-everything" ] && [ -f "$APP/tests/security/scan_secrets.py" ] || { echo "СТОП: неожиданный APP=$APP"; exit 1; }
PY="$APP/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "СТОП: нет $PY"; exit 1; }
CLAUDE_TRACKED=$(git -C "$APP" ls-files -- .claude) || { echo "СТОП: git ls-files"; exit 1; }
[ -z "$CLAUDE_TRACKED" ] || { echo "СТОП: в индексе есть файлы из .claude"; exit 1; }
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tfe-scan-index.XXXXXX") || { echo "СТОП: mktemp не сработал"; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "СТОП: временный каталог не создан"; exit 1; }
mkdir "$WORK/tree" || { echo "СТОП: mkdir"; exit 1; }
git -C "$APP" checkout-index --all --prefix="$WORK/tree/" || { echo "СТОП: выгрузка индекса не удалась"; exit 1; }
[ -f "$WORK/tree/backend/app/modules/accounts/provisioning.py" ] && [ -f "$WORK/tree/docs/NAS-UPDATE.md" ] || { echo "СТОП: выгрузка неполная"; exit 1; }
"$PY" -I "$APP/tests/security/scan_secrets.py" "$WORK/tree" > "$WORK/scan.txt" 2>&1
RC=$?
tail -n 1 "$WORK/scan.txt"
echo "exit=$RC"
grep -q -F 'scan_secrets: 0 finding(s), 0 HIGH,' "$WORK/scan.txt" && [ "$RC" -eq 0 ] || { echo "СТОП: есть находки. Файл и строка, без значений:"; awk '$1=="HIGH"||$1=="MEDIUM"{print $1, $2, $3}' "$WORK/scan.txt"; exit 1; }
echo "ОК: выгрузка индекса чиста. Временный каталог оставлен: $WORK"
)
```

Ожидается:

```text
scan_secrets: 0 finding(s), 0 HIGH, scanned /var/folders/…/tfe-scan-index.XXXXXX/tree
exit=0
ОК: выгрузка индекса чиста. Временный каталог оставлен: …
```

- Любая находка (`HIGH` или `MEDIUM`) — **блокер**. Сканер и его правила не меняем и не обходим. Сам секрет
  блок не печатает, только тип, файл и строку.
- Полный запуск сканера без аргументов проверяет и файлы, которые Git игнорирует. Это справочная проверка,
  она не заменяет сканирование выгрузки.

### 1.6. Коммит

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
EXPECTED=$(printf '%s\n' backend/app/core/login_stages.py backend/app/modules/accounts/provisioning.py backend/app/modules/accounts/router.py backend/tests/test_login_diagnostics.py docs/LOGIN-DIAGNOSTICS.md docs/NAS-UPDATE.md)
ACTUAL=$(git -C "$APP" diff --cached --name-only) || { echo "СТОП: не удалось прочитать индекс"; exit 1; }
[ "$ACTUAL" = "$EXPECTED" ] || { echo "СТОП: состав индекса изменился, повторите 1.4"; exit 1; }
PY="$APP/backend/.venv/bin/python"
[ -x "$PY" ] && [ -f "$APP/tests/security/scan_secrets.py" ] || { echo "СТОП: нет python или сканера"; exit 1; }
CLAUDE_TRACKED=$(git -C "$APP" ls-files -- .claude) || { echo "СТОП: git ls-files"; exit 1; }
[ -z "$CLAUDE_TRACKED" ] || { echo "СТОП: в индексе есть файлы из .claude"; exit 1; }
TREE=$(git -C "$APP" write-tree) || { echo "СТОП: git write-tree не выполнен"; exit 1; }
[ -n "$TREE" ] || { echo "СТОП: пустой идентификатор дерева"; exit 1; }
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tfe-scan-commit.XXXXXX") || { echo "СТОП: mktemp не сработал"; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "СТОП: временный каталог не создан"; exit 1; }
git -C "$APP" archive --format=tar -o "$WORK/index-tree.tar" "$TREE" || { echo "СТОП: выгрузка дерева индекса не удалась"; exit 1; }
[ -s "$WORK/index-tree.tar" ] || { echo "СТОП: архив пустой"; exit 1; }
mkdir "$WORK/tree" || { echo "СТОП: mkdir"; exit 1; }
tar -xf "$WORK/index-tree.tar" -C "$WORK/tree" || { echo "СТОП: распаковка не удалась"; exit 1; }
[ -f "$WORK/tree/backend/app/modules/accounts/provisioning.py" ] && [ -f "$WORK/tree/docs/NAS-UPDATE.md" ] || { echo "СТОП: выгрузка неполная"; exit 1; }
"$PY" -I "$APP/tests/security/scan_secrets.py" "$WORK/tree" > "$WORK/scan.txt" 2>&1
RC=$?
tail -n 1 "$WORK/scan.txt"
echo "exit=$RC TREE=$TREE"
grep -q -F 'scan_secrets: 0 finding(s), 0 HIGH,' "$WORK/scan.txt" && [ "$RC" -eq 0 ] || { echo "СТОП: есть находки, коммит не создан. Файл и строка, без значений:"; awk '$1=="HIGH"||$1=="MEDIUM"{print $1, $2, $3}' "$WORK/scan.txt"; exit 1; }
TREE_NOW=$(git -C "$APP" write-tree) || { echo "СТОП: git write-tree не выполнен"; exit 1; }
[ "$TREE_NOW" = "$TREE" ] || { echo "СТОП: индекс изменился после сканирования, коммит не создан. Повторите блок"; exit 1; }
git -C "$APP" commit -m "diagnostics: trace ensure_profile provisioning sub-stages" || { echo "СТОП: коммит не создан"; exit 1; }
HEAD_TREE=$(git -C "$APP" rev-parse --verify 'HEAD^{tree}') || { echo "СТОП: нет HEAD"; exit 1; }
[ "$HEAD_TREE" = "$TREE" ] || { echo "СТОП: дерево коммита не совпадает с просканированным. Push не делать, сообщите"; exit 1; }
git -C "$APP" log -1 --stat --format='%H %s'
echo "ОК: коммит создан из просканированного дерева $TREE. Временный каталог оставлен: $WORK"
)
```

Как блок связывает сканирование и коммит:

- `git write-tree` выдаёт идентификатор **точного содержимого индекса**. Выгружается и сканируется именно
  это дерево (`git archive <TREE>`), а не просто проверяется список имён файлов.
- Перед коммитом `write-tree` вызывается ещё раз. Если индекс успел измениться (кто-то добавил файл или
  правку), идентификатор будет другим, и коммит **не создаётся**.
- После коммита `HEAD^{tree}` сравнивается с просканированным деревом. Совпадение значит, что в коммите ровно
  то, что проверено сканером.
- Раздел 1.5 остаётся ранней проверкой, а решающая проверка — этот блок. Временный каталог
  `tfe-scan-commit.*` не удаляется.

Ожидается: `scan_secrets: 0 finding(s), 0 HIGH, …`, `exit=0`, `6 files changed` и `ОК: коммит создан
из просканированного дерева …`. Коммит ложится на ветку `recovery/provisioning-diagnostics`, а `main` не
меняется.

### 1.7. Сканирование выгрузки `HEAD`

Сканируется ровно тот коммит, который уйдёт на GitHub и будет собран. Архив сначала пишется в файл
(без конвейера `|`, который может скрыть ошибку `git archive`). Затем проверяется, что он не пустой, после
этого распаковывается и только потом сканируется.

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(basename "$APP")" = "time-for-everything" ] && [ -f "$APP/tests/security/scan_secrets.py" ] || { echo "СТОП: неожиданный APP=$APP"; exit 1; }
PY="$APP/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "СТОП: нет $PY"; exit 1; }
SHA=$(git -C "$APP" rev-parse --verify 'HEAD^{commit}') || { echo "СТОП: нет HEAD"; exit 1; }
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tfe-scan-head.XXXXXX") || { echo "СТОП: mktemp не сработал"; exit 1; }
[ -n "$WORK" ] && [ -d "$WORK" ] || { echo "СТОП: временный каталог не создан"; exit 1; }
git -C "$APP" archive --format=tar -o "$WORK/head.tar" "$SHA" || { echo "СТОП: git archive не удался"; exit 1; }
[ -s "$WORK/head.tar" ] || { echo "СТОП: архив пустой"; exit 1; }
mkdir "$WORK/tree" || { echo "СТОП: mkdir"; exit 1; }
tar -xf "$WORK/head.tar" -C "$WORK/tree" || { echo "СТОП: распаковка не удалась"; exit 1; }
[ -f "$WORK/tree/backend/app/modules/accounts/provisioning.py" ] && [ -f "$WORK/tree/docs/NAS-UPDATE.md" ] || { echo "СТОП: выгрузка неполная"; exit 1; }
"$PY" -I "$APP/tests/security/scan_secrets.py" "$WORK/tree" > "$WORK/scan.txt" 2>&1
RC=$?
tail -n 1 "$WORK/scan.txt"
echo "exit=$RC SHA=$SHA"
grep -q -F 'scan_secrets: 0 finding(s), 0 HIGH,' "$WORK/scan.txt" && [ "$RC" -eq 0 ] || { echo "СТОП: есть находки. Файл и строка, без значений:"; awk '$1=="HIGH"||$1=="MEDIUM"{print $1, $2, $3}' "$WORK/scan.txt"; exit 1; }
echo "ОК: HEAD чист. Временный каталог оставлен: $WORK"
)
```

Ожидается `scan_secrets: 0 finding(s), 0 HIGH, …`, `exit=0` и SHA нового коммита. Запишите SHA.

### 1.8. Push ветки восстановления

В `main` ничего не отправляется. Push выполняется явной ссылкой на ветку, без `--force`. После push блок
проверяет, что на GitHub лежит тот же SHA.

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
SHA=$(git -C "$APP" rev-parse --verify 'HEAD^{commit}') || { echo "СТОП: нет HEAD"; exit 1; }
git -C "$APP" push origin refs/heads/recovery/provisioning-diagnostics:refs/heads/recovery/provisioning-diagnostics || { echo "СТОП: push отклонён, --force не использовать"; exit 1; }
REMOTE=$(git -C "$APP" ls-remote origin refs/heads/recovery/provisioning-diagnostics) || { echo "СТОП: ls-remote"; exit 1; }
REMOTE_SHA=${REMOTE%%[[:space:]]*}
[ "$REMOTE_SHA" = "$SHA" ] || { echo "СТОП: на GitHub другой SHA: $REMOTE_SHA"; exit 1; }
echo "ОК: на GitHub ветка recovery/provisioning-diagnostics = $SHA"
)
```

- Если push отклонён (`rejected`, `non-fast-forward`), остановитесь и выясните, откуда на GitHub чужие
  коммиты. `--force` не используйте.
- Откройте `https://github.com/matovykh/time-for-everything/actions` и дождитесь **зелёного Source CI** для
  этого SHA (workflow запускается при push в любую ветку). Если CI красный, сборку на NAS не выкатывайте.
- Слияние в `main` — отдельное решение после проверки на NAS, через обычный pull request. В этом документе
  его нет.

---

## 2. Сборка образа на Mac

### 2.1. Проверки перед сборкой (только чтение)

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
DEPLOY="$APP/time-for-everything_deploy"
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
APP_SHA=$(git -C "$APP" rev-parse --verify 'HEAD^{commit}') || { echo "СТОП: нет HEAD"; exit 1; }
REMOTE=$(git -C "$APP" ls-remote origin refs/heads/recovery/provisioning-diagnostics) || { echo "СТОП: ls-remote"; exit 1; }
[ "${REMOTE%%[[:space:]]*}" = "$APP_SHA" ] || { echo "СТОП: HEAD не совпадает с веткой на GitHub, сначала 1.8"; exit 1; }
DIRTY=$(git -C "$APP" status --short -- supabase backend/app/db/session.py) || { echo "СТОП: git status"; exit 1; }
[ -z "$DIRTY" ] || { echo "СТОП: незакоммиченные изменения в supabase или session.py"; exit 1; }
SCHEMA=$(bash "$DEPLOY/scripts/source-schema-version.sh" "$APP") || { echo "СТОП: проверка схемы не прошла"; exit 1; }
echo "$SCHEMA"
[ "$SCHEMA" = "schema_version=20261006000002" ] || { echo "СТОП: схема изменилась, это другой релиз"; exit 1; }
git -C "$APP" ls-tree --name-only "$APP_SHA" -- supabase/migrations/
MISSING=0
for n in ensure_profile.profile_get ensure_profile.email_commit ensure_profile.profile_add ensure_profile.profile_flush ensure_profile.activity_add ensure_profile.activity_flush ensure_profile.activity_children_add ensure_profile.wallet_world_add ensure_profile.final_flush ensure_profile.active_world_flush ensure_profile.commit ensure_profile.integrity_rollback ensure_profile.integrity_reread; do git -C "$APP" grep -q -F "\"$n\"" "$APP_SHA" -- backend/app/core/login_stages.py || { echo "НЕТ в коммите: $n"; MISSING=1; }; done
[ "$MISSING" -eq 0 ] || { echo "СТОП: в коммите нет диагностических этапов"; exit 1; }
[ "$(git -C "$DEPLOY" rev-parse --short=7 HEAD)" = "bcb583c" ] || { echo "СТОП: deploy не на bcb583c"; exit 1; }
DDIRTY=$(git -C "$DEPLOY" status --short -- docker .dockerignore scripts) || { echo "СТОП: git status deploy"; exit 1; }
[ -z "$DDIRTY" ] || { echo "СТОП: в deploy изменены docker, .dockerignore или scripts"; exit 1; }
echo "ОК: можно собирать APP_SHA=$APP_SHA"
)
```

Ожидается:

```text
schema_version=20261006000002
supabase/migrations/20261006000001_init.sql
supabase/migrations/20261006000002_session_revocations.sql
ОК: можно собирать APP_SHA=<40 символов нового коммита>
```

Схема та же, что у работающей установки, поэтому **базу не трогаем** (раздел 5).

### 2.2. Сборка, архив и контрольная сумма

Docker Desktop должен быть запущен. Тег **вычисляется**: `nas-<дата-время>-<первые 7 символов SHA>`.
Старые и придуманные теги не используются. Если образ с таким тегом уже есть, блок останавливается и
ничего не удаляет.

```sh
(
cd "$HOME/RepoPrompt/ВсёУспею/time-for-everything" || { echo "СТОП: каталог приложения не найден"; exit 1; }
APP=$(git rev-parse --show-toplevel) || { echo "СТОП: не Git"; exit 1; }
DEPLOY="$APP/time-for-everything_deploy"
[ -f "$DEPLOY/scripts/build-local.sh" ] || { echo "СТОП: нет build-local.sh"; exit 1; }
[ "$(git -C "$APP" symbolic-ref --short HEAD)" = "recovery/provisioning-diagnostics" ] || { echo "СТОП: не та ветка"; exit 1; }
APP_SHA=$(git -C "$APP" rev-parse --verify 'HEAD^{commit}') || { echo "СТОП: нет HEAD"; exit 1; }
REMOTE=$(git -C "$APP" ls-remote origin refs/heads/recovery/provisioning-diagnostics) || { echo "СТОП: ls-remote"; exit 1; }
[ "${REMOTE%%[[:space:]]*}" = "$APP_SHA" ] || { echo "СТОП: коммит не отправлен на GitHub"; exit 1; }
APP_SHORT=$(git -C "$APP" rev-parse --short=7 "$APP_SHA") || { echo "СТОП: short SHA"; exit 1; }
DEPLOY_SHA=$(git -C "$DEPLOY" rev-parse HEAD) || { echo "СТОП: deploy SHA"; exit 1; }
SCHEMA=$(bash "$DEPLOY/scripts/source-schema-version.sh" "$APP") || { echo "СТОП: схема"; exit 1; }
[ "$SCHEMA" = "schema_version=20261006000002" ] || { echo "СТОП: схема изменилась"; exit 1; }
TFE_TAG="nas-$(date +%Y%m%d-%H%M%S)-$APP_SHORT"
TFE_IMAGE="time-for-everything:$TFE_TAG"
if docker image inspect "$TFE_IMAGE" >/dev/null 2>&1; then echo "СТОП: тег уже существует, запустите блок заново"; exit 1; fi
cd "$DEPLOY" || { echo "СТОП: нет DEPLOY"; exit 1; }
BUILD_BUILDER=desktop-linux BUILD_PLATFORM=linux/amd64 sh "$DEPLOY/scripts/build-local.sh" --app-dir "$APP" --sha "$APP_SHA" --tag "$TFE_IMAGE" || { echo "СТОП: сборка не удалась"; exit 1; }
ARCH=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$TFE_IMAGE") || { echo "СТОП: образ не найден"; exit 1; }
[ "$ARCH" = "linux/amd64" ] || { echo "СТОП: платформа $ARCH, нужна linux/amd64"; exit 1; }
umask 077
mkdir -p "$HOME/tfe-transfer" || { echo "СТОП: нет tfe-transfer"; exit 1; }
cd "$HOME/tfe-transfer" || { echo "СТОП: cd tfe-transfer"; exit 1; }
TAR="time-for-everything-$TFE_TAG.tar"
if [ -e "$TAR" ]; then echo "СТОП: файл $TAR уже есть"; exit 1; fi
docker save -o "$TAR" "$TFE_IMAGE" || { echo "СТОП: docker save не удался"; exit 1; }
[ -s "$TAR" ] || { echo "СТОП: архив пустой"; exit 1; }
shasum -a 256 "$TAR" > "$TAR.sha256" || { echo "СТОП: shasum"; exit 1; }
printf 'APP_SHA=%s\nAPP_BRANCH=recovery/provisioning-diagnostics\nDEPLOY_SHA=%s\nTFE_IMAGE=%s\nSCHEMA=%s\n' "$APP_SHA" "$DEPLOY_SHA" "$TFE_IMAGE" "$SCHEMA" > "build-info-$TFE_TAG.txt" || { echo "СТОП: build-info"; exit 1; }
ls -l "$TAR" "$TAR.sha256" "build-info-$TFE_TAG.txt"
echo "ОК: TFE_TAG=$TFE_TAG"
)
```

- **Запишите значение `TFE_TAG`** из последней строки. Оно нужно в разделах 3, 4.4, 6.1 и 7.1.
- Сборка берёт закоммиченный `APP_SHA` через `git archive`, файлы с диска в образ не идут. Пароли Supabase
  для сборки не нужны.
- Сам `build-local.sh` после сборки убирает **собственный** временный каталог контекста сборки, который
  создал через `mktemp`. Это внутренняя логика скрипта, вы такую команду не вводите.
- Архив весит около 80 МБ. Паролей в нём нет, но публиковать его не нужно.

---

## 3. Перенос на NAS

Подставьте свой `TFE_TAG` вместо `ВСТАВЬТЕ_TFE_TAG`.

```sh
(
TFE_TAG='ВСТАВЬТЕ_TFE_TAG'
cd "$HOME/tfe-transfer" || { echo "СТОП: нет ~/tfe-transfer"; exit 1; }
TAR="time-for-everything-$TFE_TAG.tar"
[ -s "$TAR" ] && [ -s "$TAR.sha256" ] && [ -s "build-info-$TFE_TAG.txt" ] || { echo "СТОП: нет файлов для тега $TFE_TAG"; exit 1; }
shasum -a 256 -c "$TAR.sha256" || { echo "СТОП: контрольная сумма не совпала"; exit 1; }
scp -O "$TAR" "$TAR.sha256" "build-info-$TFE_TAG.txt" fedor.matovykh@192.168.1.97:/volume1/docker/tfe-transfer/ || { echo "СТОП: scp не удался"; exit 1; }
echo "ОК: перенесено"
)
```

- `-O` (заглавная буква O) переключает `scp` на классический протокол: с SFTP-режимом на DSM он может не
  работать. Предупреждение `Could not chdir to home directory…` ожидаемо.
- **Не переносите** `compose.production.yaml`, `install-config.sh`, `app.env.example` и ничего из
  `~/tfe-rescue-20261012-123852`. Конфигурация остаётся на NAS.

---

## 4. Подготовка NAS

```sh
ssh fedor.matovykh@192.168.1.97
```

**Дальше всё выполняется на NAS.** Функция `tfe` существует **только внутри блока, где она определена**.
Поэтому каждый NAS-блок, которому она нужна, сам определяет `D`, делает `cd`, проверки и определение
`tfe`. Приложение продолжает работать на старом образе до раздела 6.

### 4.1. Снимок текущего состояния (только чтение)

```sh
(
D=/volume1/docker/time-for-everything_deploy
cd "$D" || { echo "СТОП: нет каталога $D"; exit 1; }
sudo test -f "$D/compose/deploy.env" && sudo test -f "$D/compose/compose.production.yaml" && sudo test -f "$D/config/app.env" || { echo "СТОП: нет deploy.env, compose или app.env"; exit 1; }
tfe() { sudo docker compose --project-name time-for-everything_deploy --env-file "$D/compose/deploy.env" -f "$D/compose/compose.production.yaml" "$@"; }
tfe ps
CID=$(tfe ps -q app)
[ -n "$CID" ] || { echo "СТОП: контейнер app не найден"; exit 1; }
sudo docker inspect --format 'image={{.Config.Image}} id={{.Image}} started={{.State.StartedAt}} restarts={{.RestartCount}}' "$CID"
sudo cat "$D/compose/deploy.env"
echo "строк DB_NULL_POOL=true в app.env: $(sudo grep -c '^DB_NULL_POOL=true$' "$D/config/app.env")"
sudo ls -ln "$D/config/app.env"
curl -sS http://192.168.1.97:18080/api/v1/health/ready
echo
)
```

- `image=` показывает образ, с которым контейнер реально создан. **Это образ для отката, запишите его**,
  вместе с `id=sha256:…`. Ожидается `time-for-everything:nas-20261010-210507-620e834`. Если там другое
  значение, верьте выводу команды, а не документации, и прежде чем продолжать, разберитесь.
- `TFE_IMAGE` в `deploy.env` должен совпадать с `image=`. Если не совпадает, остановитесь.
- `deploy.env` секретов не содержит. Из `app.env` выводится **только число** строк `DB_NULL_POOL=true`
  (ожидается `1`), а также владелец и права (ожидаются `-rw-------` и `10001 10001`). Содержимое
  `app.env` не выводится.
- `ready` до обновления сохраните, чтобы потом отличить прежнюю проблему от новой.

### 4.2. Резервные копии `deploy.env` и compose

```sh
(
D=/volume1/docker/time-for-everything_deploy
cd "$D/compose" || { echo "СТОП: нет $D/compose"; exit 1; }
TS=$(date +%Y%m%d-%H%M%S)
sudo test -e "deploy.env.bak-$TS" && { echo "СТОП: копия с таким TS уже есть, повторите через секунду"; exit 1; }
sudo cp -p deploy.env "deploy.env.bak-$TS" || { echo "СТОП: копия deploy.env не создана"; exit 1; }
sudo cp -p compose.production.yaml "compose.production.yaml.bak-$TS" || { echo "СТОП: копия compose не создана"; exit 1; }
sudo ls -l "deploy.env.bak-$TS" "compose.production.yaml.bak-$TS"
echo "ОК: TS=$TS"
)
```

**Запишите `TS`.** Копию `app.env` не делаем: файл не меняется. Его прежняя копия лежит в
`~/tfe-rescue-20261012-123852` на Mac.

### 4.3. Проверить, что NAS-compose сохранил ваши правки (только чтение)

```sh
(
D=/volume1/docker/time-for-everything_deploy
cd "$D" || { echo "СТОП: нет $D"; exit 1; }
sudo grep -nE 'ports:|192\.168\.1\.97|cpus|mem_limit|pids_limit' "$D/compose/compose.production.yaml"
sudo grep -n 'TFE_HTTP_PORT' "$D/compose/deploy.env"
ACTIVE_CPUS=$(sudo grep -cE '^[[:space:]]*cpus:' "$D/compose/compose.production.yaml")
[ "$ACTIVE_CPUS" = "0" ] || { echo "СТОП: cpus не закомментирован"; exit 1; }
sudo grep -qF '"192.168.1.97:${TFE_HTTP_PORT:-8000}:8000"' "$D/compose/compose.production.yaml" || { echo "СТОП: привязка к 192.168.1.97 не найдена"; exit 1; }
sudo grep -qx 'TFE_HTTP_PORT=18080' "$D/compose/deploy.env" || { echo "СТОП: TFE_HTTP_PORT не 18080"; exit 1; }
echo "ОК: compose и порт как ожидалось"
)
```

Ожидается примерно:

```text
      - "192.168.1.97:${TFE_HTTP_PORT:-8000}:8000"
    mem_limit: 512m
    # cpus: 1.0
    pids_limit: 128
TFE_HTTP_PORT=18080
ОК: compose и порт как ожидалось
```

Если что-то не совпало, **ничего не правьте вслепую**: значит, compose на NAS уже другой.

### 4.4. Проверить архив и загрузить образ

```sh
(
TFE_TAG='ВСТАВЬТЕ_TFE_TAG'
T=/volume1/docker/tfe-transfer
cd "$T" || { echo "СТОП: нет $T"; exit 1; }
NEW_IMAGE="time-for-everything:$TFE_TAG"
TAR="time-for-everything-$TFE_TAG.tar"
[ -s "$TAR" ] && [ -s "$TAR.sha256" ] && [ -s "build-info-$TFE_TAG.txt" ] || { echo "СТОП: нет файлов для тега $TFE_TAG"; exit 1; }
df -h /volume1
cat "build-info-$TFE_TAG.txt"
sha256sum -c "$TAR.sha256" || { echo "СТОП: контрольная сумма не совпала, образ не загружаем"; exit 1; }
sudo docker load -i "$T/$TAR" || { echo "СТОП: docker load не удался"; exit 1; }
ARCH=$(sudo docker image inspect --format '{{.Os}}/{{.Architecture}}' "$NEW_IMAGE") || { echo "СТОП: образ $NEW_IMAGE не найден после загрузки"; exit 1; }
[ "$ARCH" = "linux/amd64" ] || { echo "СТОП: платформа $ARCH"; exit 1; }
sudo docker image ls time-for-everything
echo "ОК: загружен $NEW_IMAGE"
)
```

- В `build-info` должна быть строка `APP_SHA=` с SHA из раздела 1.7 и строка
  `APP_BRANCH=recovery/provisioning-diagnostics`.
- В списке образов должны быть **оба**: образ для отката из раздела 4.1 и новый.

---

## 5. Миграции базы — в этом релизе не требуются

Раздел 2.1 показывает `schema_version=20261006000002` и только две исходные миграции. Работающая установка
отвечает `schema: ok` на ту же версию. Значит:

- `scripts/db_migrate.py` **не запускается**, `DATABASE_URL` на Mac не вводится, `pg_dump` не нужен;
- `scripts/db_reset.py` **не запускается никогда**: он удаляет данные;
- диагностический патч не добавляет новых SQL-операций. Он только замеряет время уже существующих
  `get`, `flush`, `commit` и `rollback`.

Если в 2.1 схема другая, это другой релиз. Остановитесь: порядок для миграций сюда сознательно не включён.

---

## 6. Переключить NAS на новый образ

### 6.1. Заменить только `TFE_IMAGE`

```sh
(
TFE_TAG='ВСТАВЬТЕ_TFE_TAG'
TS='ВСТАВЬТЕ_TS_ИЗ_4.2'
D=/volume1/docker/time-for-everything_deploy
cd "$D/compose" || { echo "СТОП: нет $D/compose"; exit 1; }
NEW_IMAGE="time-for-everything:$TFE_TAG"
sudo docker image inspect "$NEW_IMAGE" >/dev/null || { echo "СТОП: образ $NEW_IMAGE не загружен"; exit 1; }
sudo test -f "deploy.env.bak-$TS" || { echo "СТОП: нет резервной копии deploy.env.bak-$TS"; exit 1; }
sudo sed -i "s|^TFE_IMAGE=.*|TFE_IMAGE=$NEW_IMAGE|" deploy.env || { echo "СТОП: sed не выполнен"; exit 1; }
CUR=$(sudo grep '^TFE_IMAGE=' deploy.env)
[ "$CUR" = "TFE_IMAGE=$NEW_IMAGE" ] || { echo "СТОП: TFE_IMAGE не тот. Верните копию: sudo cp -p $D/compose/deploy.env.bak-$TS $D/compose/deploy.env"; exit 1; }
sudo grep -qx 'TFE_HTTP_PORT=18080' deploy.env || { echo "СТОП: пропал TFE_HTTP_PORT=18080, верните копию"; exit 1; }
sudo cat deploy.env
echo "ОК: TFE_IMAGE заменён"
)
```

Ожидаются три строки, изменилась только первая:

```dotenv
TFE_IMAGE=time-for-everything:nas-…-<sha7>
TFE_HTTP_PORT=18080
TFE_CONFIG_FILE=/volume1/docker/time-for-everything_deploy/config/app.env
```

Возврат копии командой `sudo cp -p …bak-$TS …deploy.env` перезаписывает `deploy.env` его же прежней
версией. Это не удаление.

### 6.2. Проверить конфигурацию и пересоздать контейнер

```sh
(
TFE_TAG='ВСТАВЬТЕ_TFE_TAG'
D=/volume1/docker/time-for-everything_deploy
cd "$D" || { echo "СТОП: нет $D"; exit 1; }
tfe() { sudo docker compose --project-name time-for-everything_deploy --env-file "$D/compose/deploy.env" -f "$D/compose/compose.production.yaml" "$@"; }
NEW_IMAGE="time-for-everything:$TFE_TAG"
[ "$(sudo grep '^TFE_IMAGE=' "$D/compose/deploy.env")" = "TFE_IMAGE=$NEW_IMAGE" ] || { echo "СТОП: в deploy.env не новый TFE_IMAGE, сначала 6.1"; exit 1; }
sudo grep -qx 'TFE_HTTP_PORT=18080' "$D/compose/deploy.env" || { echo "СТОП: TFE_HTTP_PORT не 18080"; exit 1; }
sudo grep -qF '"192.168.1.97:${TFE_HTTP_PORT:-8000}:8000"' "$D/compose/compose.production.yaml" || { echo "СТОП: привязка к 192.168.1.97 не найдена"; exit 1; }
ACTIVE_CPUS=$(sudo grep -cE '^[[:space:]]*cpus:' "$D/compose/compose.production.yaml")
[ "$ACTIVE_CPUS" = "0" ] || { echo "СТОП: cpus не закомментирован"; exit 1; }
sudo grep -nE '^[[:space:]]*image:|192\.168\.1\.97|cpus' "$D/compose/compose.production.yaml"
tfe config -q || { echo "СТОП: compose-конфигурация с ошибкой"; exit 1; }
tfe up -d --no-build --pull never || { echo "СТОП: tfe up завершился с ошибкой"; exit 1; }
tfe ps
echo "ОК: контейнер пересоздан"
)
```

- Итоговую конфигурацию (`tfe config` без `-q`) **не выводим**: в ней собраны все подставленные значения,
  и печатать её незачем. Проверка правильности — только `tfe config -q`: без вывода и без ошибки.
- Порт, адрес и `cpus` проверяются по **исходным** файлам `deploy.env` и `compose.production.yaml`. Секретов
  в них нет. Ожидается строка `image: ${TFE_IMAGE:?…}`, строка с `"192.168.1.97:${TFE_HTTP_PORT:-8000}:8000"`
  и `# cpus: 1.0`.
- Compose пересоздаёт только контейнер `app`. `--pull never` означает, что Docker Hub не используется.
  Предупреждение `PIDs limit discarded` на этом NAS ожидаемо.
- `--force-recreate` не нужен: образ изменился, а `app.env` нет.

### 6.3. `app.env` не меняется, `DB_NULL_POOL=true` остаётся

- В этом релизе новых настроек нет. **Не редактируйте `app.env`**, не запускайте `install-config.sh` и
  не копируйте шаблоны поверх файла.
- `DB_NULL_POOL=true` был включён раньше для диагностики. В этом режиме каждый запрос открывает **новое**
  соединение с базой, а настройки пула не действуют. Режим оставлен, чтобы условия совпадали с теми, в
  которых наблюдался таймаут входа, и диагностика их не меняла. Учтите это при чтении лога: время на
  установку соединения (TCP, TLS, аутентификация в Supabase) попадает в подэтап
  `ensure_profile.profile_get` (подробнее в [LOGIN-DIAGNOSTICS.md](LOGIN-DIAGNOSTICS.md)).
- Вернуть пул (`false` или удалить строку) — **отдельное решение после разбора лога**, не часть этого
  обновления.
- Согласованный HTTP-вариант (`APP_ENV=development`, `APP_BASE_URL=http://192.168.1.97:18080`,
  `COOKIE_SECURE=false`) не меняется.

---

## 7. Проверка после обновления

### 7.1. Контейнер, образ, база (на NAS)

```sh
(
TFE_TAG='ВСТАВЬТЕ_TFE_TAG'
D=/volume1/docker/time-for-everything_deploy
cd "$D" || { echo "СТОП: нет $D"; exit 1; }
tfe() { sudo docker compose --project-name time-for-everything_deploy --env-file "$D/compose/deploy.env" -f "$D/compose/compose.production.yaml" "$@"; }
NEW_IMAGE="time-for-everything:$TFE_TAG"
tfe ps
CID=$(tfe ps -q app)
[ -n "$CID" ] || { echo "СТОП: контейнер app не найден"; exit 1; }
RUN_IMAGE=$(sudo docker inspect --format '{{.Config.Image}}' "$CID")
RUN_ID=$(sudo docker inspect --format '{{.Image}}' "$CID")
WANT_ID=$(sudo docker image inspect --format '{{.Id}}' "$NEW_IMAGE")
echo "image=$RUN_IMAGE"
[ "$RUN_IMAGE" = "$NEW_IMAGE" ] && [ -n "$WANT_ID" ] && [ "$RUN_ID" = "$WANT_ID" ] || { echo "СТОП: запущен не новый образ"; exit 1; }
curl -sS http://192.168.1.97:18080/api/v1/health/live
echo
curl -sS http://192.168.1.97:18080/api/v1/health/ready
echo
tfe logs --tail 30 app
echo "ОК: запущен $NEW_IMAGE"
)
```

Сначала `tfe ps` покажет `health: starting`. Через 20–30 секунд повторите блок: должно быть `(healthy)` и
`192.168.1.97:18080->8000/tcp`. Ожидаются ответы:

```json
{"status":"ok"}
{"status":"ready","checks":{"database":"ok","schema":"ok","auth":"configured"},"setup":[]}
```

| Ответ | Что значит |
|---|---|
| `schema: outdated` / `missing` | В этом релизе не ожидается. Миграции вслепую не запускать: откат (раздел 8) и разбор |
| `database: timeout` / `unreachable` | Сравните с `ready` до обновления (4.1). `app.env` не менялся, поэтому скорее всего это та же сетевая проблема, а не новый образ |
| Контейнер перезапускается | Смотрите `tfe logs --tail 50 app`, ищите `ConfigError` и `Traceback` |

В логе должна быть строка `Application startup complete`. Паролей лог не содержит, но перед отправкой
кому-либо просмотрите его.

### 7.2. Вход (в браузере)

1. Откройте **http://192.168.1.97:18080/** и обновите страницу без кэша: **⌘ + Shift + R**.
2. Сделайте **одну** попытку входа тестовым аккаунтом и запишите время.
3. Прочитайте лог этой попытки по [LOGIN-DIAGNOSTICS.md](LOGIN-DIAGNOSTICS.md). Это главная цель релиза.
4. Если вход удался, выполните одно изменяющее действие (запуск и остановка таймера) и обновите страницу.

Красные `401` для `/api/v1/me` и `/api/v1/auth/refresh` до входа — норма. Ошибка
`ERR_ADDRESS_UNREACHABLE` в Chrome или Brave означает, что в macOS не выдано разрешение «Локальная сеть»;
к обновлению это не относится.

**Помните:** релиз **диагностирует**, а не исправляет таймаут входа. Если вход по-прежнему не успевает за
20 секунд, это ожидаемо, а результат обновления — строки лога.

---

## 8. Откат

Миграций не было, `app.env` не менялся, поэтому откат — это просто возврат прежнего `TFE_IMAGE`.

```sh
(
OLD_IMAGE='ВСТАВЬТЕ_ОБРАЗ_ИЗ_4.1'
D=/volume1/docker/time-for-everything_deploy
cd "$D/compose" || { echo "СТОП: нет $D/compose"; exit 1; }
tfe() { sudo docker compose --project-name time-for-everything_deploy --env-file "$D/compose/deploy.env" -f "$D/compose/compose.production.yaml" "$@"; }
sudo docker image inspect --format '{{.Id}}' "$OLD_IMAGE" || { echo "СТОП: образа $OLD_IMAGE нет на NAS"; exit 1; }
sudo sed -i "s|^TFE_IMAGE=.*|TFE_IMAGE=$OLD_IMAGE|" deploy.env || { echo "СТОП: sed не выполнен"; exit 1; }
[ "$(sudo grep '^TFE_IMAGE=' deploy.env)" = "TFE_IMAGE=$OLD_IMAGE" ] || { echo "СТОП: TFE_IMAGE не тот"; exit 1; }
sudo grep -qx 'TFE_HTTP_PORT=18080' deploy.env || { echo "СТОП: пропал TFE_HTTP_PORT"; exit 1; }
tfe config -q || { echo "СТОП: compose-конфигурация с ошибкой"; exit 1; }
tfe up -d --no-build --pull never || { echo "СТОП: tfe up с ошибкой"; exit 1; }
tfe ps
echo "ОК: возвращён $OLD_IMAGE"
)
```

- `OLD_IMAGE` берите из вывода `image=` в разделе 4.1. Ожидается
  `time-for-everything:nas-20261010-210507-620e834`. ID, который печатает первая команда, должен совпасть
  с записанным `id=sha256:…`.
- Вместо `sed` можно вернуть всю копию: `sudo cp -p "$D/compose/deploy.env.bak-<TS>" "$D/compose/deploy.env"`.
- Затем проверьте, как в 7.1: `(healthy)` и `ready`. В блоке 7.1 подставьте прежний тег
  (`nas-20261010-210507-620e834`).

---

## 9. Уборка — не выполняется

В рамках этого обновления **ничего не удаляется**:

- временные выгрузки `tfe-scan-*` остаются в `$TMPDIR` (macOS очищает его сама);
- архивы в `~/tfe-transfer` и `/volume1/docker/tfe-transfer` остаются;
- старые образы на NAS остаются: среди них образ для отката;
- файлы `*.bak-<TS>` на NAS остаются;
- `~/tfe-rescue-20261012-123852` остаётся (приватно, `drwx------`).

Если когда-нибудь понадобится место, это отдельное решение. Его принимают отдельно, вручную и не по этой
инструкции.

---

## 10. Чего не делать

- `rm`, `rm -rf`, `git clean`, `git reset`, `git checkout -- .`, `git restore` без `--staged`, `git stash`.
- `git add .`, `git add -A`, `git add -f`, `git commit -a`, `git push --force`, push в `main`.
- Вставлять несколько блоков сразу, вставлять блок частично, дописывать `\`-переносы.
- Собирать из незакоммиченных файлов (`--worktree`, `docker build .`); повторно использовать старый тег.
- Копировать `compose.production.yaml` с Mac на NAS; менять порт 18080; раскомментировать `cpus`.
- Редактировать, выводить или копировать `app.env`; запускать `install-config.sh`; выводить содержимое
  `~/tfe-rescue-20261012-123852`.
- `scripts/db_reset.py`, `scripts/db_migrate.py --apply`.
- `tfe down`, `tfe down -v`, `tfe pull`, `docker system prune`, `docker image prune`, `docker image rm`.

---

## Краткая шпаргалка

| Где | Шаг | Ожидаемый результат |
|---|---|---|
| Mac | 1.1 окружение | ветка `recovery/provisioning-diagnostics`, deploy `bcb583c` |
| Mac | 1.3 тесты | `pytest exit=0`, `ruff exit=0` |
| Mac | 1.4 индекс | `ОК: в индексе ровно шесть файлов` |
| Mac | 1.5 / 1.6 / 1.7 скан | `scan_secrets: 0 finding(s), 0 HIGH`, `exit=0`; в 1.6 — `ОК: коммит создан из просканированного дерева …` |
| Mac | 1.8 push | `ОК: на GitHub ветка … = <SHA>`, Source CI зелёный |
| Mac | 2.1 перед сборкой | `schema_version=20261006000002`, все 13 имён этапов найдены |
| Mac | 2.2 сборка | `ОК: TFE_TAG=nas-<дата>-<sha7>`, `linux/amd64` |
| NAS | 4.1 снимок | `image=…nas-20261010-210507-620e834`, `DB_NULL_POOL=true` — 1 строка |
| NAS | 4.4 загрузка | `…tar: OK`, `ОК: загружен …` |
| NAS | 6.1–6.2 | только `TFE_IMAGE` изменён; `ОК: контейнер пересоздан` |
| NAS | 7.1 | `(healthy)`, `ready`, `ОК: запущен <новый образ>` |
| NAS | 8 откат | прежний `TFE_IMAGE`, `tfe up -d --no-build --pull never` |
