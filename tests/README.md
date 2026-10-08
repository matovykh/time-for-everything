# Независимые QA-тесты

Владелец — QA. План, матрица рисков и исходные находки: [`docs/MVP-QA.md`](../docs/MVP-QA.md)
(исторический промежуточный отчёт). Все проверки проекта и область каждого
результата: [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md#4-тесты-и-проверки). Исторический полный прогон,
включая PostgreSQL 17, — [`docs/DEVOPS-HANDOFF.md`](../docs/DEVOPS-HANDOFF.md) §3.

Эти тесты никогда не подключаются к внешнему проекту Supabase и не сбрасывают внешние базы.

| Путь | Что | Запуск (из корня репозитория, если не указано иное) | Последний результат (2026-10-07, локально) |
|---|---|---|---|
| `reference/` | Эталон политики наград v1 по спецификации + самотесты | `python3 -I -m unittest discover -s tests/reference -v` | пройден (код 0) |
| `security/scan_secrets.py` | Статический поиск секретов, хранения токенов, утечек `.env`/Docker | `python3 -I tests/security/scan_secrets.py [абсолютный путь…]` | 0 находок по выбранным путям; вся рабочая копия — находки только в игнорируемом локальном `.claude/settings.local.json` |
| `security/test_scan_secrets.py` | Самотесты сканера | `python3 -I -m unittest discover -s tests/security -v` | пройдены (код 0) |
| `backend/` | Внутрипроцессные API-тесты (FastAPI `TestClient`, настоящая цепочка cookie → JWT → отзыв сессии, подменённый HTTP-транспорт Supabase): обход auth/CSRF, изоляция, целостность наград, сверка политики, таймеры/история/миры, защита PG | `backend/.venv/bin/python -m pytest tests/backend -q` | 1714 passed на SQLite. Режим PostgreSQL 17 в последнем раунде не перезапускался (ранее — 1714, исторически) |
| `frontend/` | Vitest + Testing Library (jsdom): маршруты, пустые состояния, ошибки, HTML в именах — с подменёнными ответами API, на зависимостях фронтенда | `npm run test:qa` (в `frontend/`) | 28 passed |

Примечания:

- Из 1714 backend QA-тестов **1600** — параметризованные случаи сверки `backend/app/modules/rewards/policy.py`
  с эталоном из `reference/` (`test_qa_policy_parity.py`: 400 поручения, 600 прогулка, 600 уроки).
  Это не браузерные end-to-end тесты.
- Режим PostgreSQL (удаляет и пересоздаёт схему `public`): добавьте
  `QA_ALLOW_DESTRUCTIVE_TEST_DB=1 QA_TEST_DATABASE_URL=postgresql://postgres:<pw>@127.0.0.1:<port>/tfe_qa`.
  Защита требует loopback-адрес, БД `tfe_qa[_суффикс]` и запрещает переопределения host/port/dbname.
- Сканер разрешает относительные пути от корня репозитория; чтобы проверить сборку, передайте абсолютный
  путь (например, `"$PWD/dist"` из `frontend/`).
