# Документация «Всё успею»

## Для кого какой документ

| Документ | Для кого | О чём |
|---|---|---|
| [USER-GUIDE.md](USER-GUIDE.md) | Ребёнок, взрослый | Вход, таймеры, ручной ввод, история, поручения, награды, миры, профиль |
| `docs/` репозитория `time-for-everything_deploy` | Оператор установки | **Отдельный DevOps-репозиторий** (адрес — после публикации): развёртывание, секреты, релизы в Docker Hub, Synology, миграции как шаг оператора. **Текущая домашняя установка — Mac в Docker Desktop**: `MAC-RUN.md`, `MAC-UPDATE.md` |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Разработчик, ревьюер | Модули, БД, аутентификация, безопасность, ограничения MVP |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Разработчик | Локальный запуск, тесты, PostgreSQL-стенд, макет |
| [API.md](API.md) | Разработчик | Точный HTTP-контракт `/api/v1` |

## Справочные и исторические материалы

| Документ | Статус |
|---|---|
| [SPECIFICATION.md](SPECIFICATION.md) | Утверждённая спецификация v0.3 — **целевой дизайн** всего продукта, шире MVP |
| [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | План и границы первой рабочей версии |
| [DEVOPS-HANDOFF.md](DEVOPS-HANDOFF.md) | **Исторический** DevOps-отчёт до разделения репозиториев (2026-10-07): образ, команды, результаты тестов (на английском) |
| [MVP-QA.md](MVP-QA.md) | Исторический отчёт независимого QA (промежуточный, 2026-10-07) с находками QA-01…07 |
| [NAS-UPDATE.md](NAS-UPDATE.md) | **Исторический** (2026-10-12): выкладка диагностической сборки на Synology. Не выполнять для текущего релиза; домашняя установка перенесена на Mac |
| [LOGIN-DIAGNOSTICS.md](LOGIN-DIAGNOSTICS.md) | **Исторический**: как читать строки `login_stage`. Диагностика удалена из кода; документ нужен только для журналов образов `nas-…` до очистки |
| [LIVING-WORLDS.md](LIVING-WORLDS.md) | Концепция живых островов |
| [designs/WORLD-ART-DIRECTION.md](designs/WORLD-ART-DIRECTION.md) | Арт-дирекция четырёх миров |
| [PROTOTYPE-TESTS.md](PROTOTYPE-TESTS.md) | Сценарии проверки исторического макета `prototype/` |
| [licenses/](licenses/) | Лицензии поставляемых Unovis и шрифта Nunito Sans |

## README компонентов

- [backend/README.md](../backend/README.md) — backend: запуск, механизмы, тесты (на английском).
- [frontend/IMPLEMENTATION.md](../frontend/IMPLEMENTATION.md) — frontend: экраны, права, графики, ограничения.
- [supabase/README.md](../supabase/README.md) — схема, миграции, модель доступа (на английском).
- [tests/README.md](../tests/README.md) — независимые QA-тесты.
- [SECURITY.md](../SECURITY.md), [CONTRIBUTING.md](../CONTRIBUTING.md).

## Статус проверки (кратко)

- Проверено локально (2026-10-07): backend и независимый QA на SQLite, frontend, lint, сканер секретов —
  счётчики и их область в [DEVELOPMENT.md §4](DEVELOPMENT.md#4-тесты-и-проверки). Результаты на PostgreSQL 17
  исторические (в последнем раунде не перезапускались). Образ и контейнер проверяются в DevOps-репозитории.
- **Не проверено**: живой Supabase (Auth, JWKS, RLS/Data API), удалённый запуск GitHub Actions,
  публикация образа, Synology NAS, реальный HTTPS reverse proxy.
- Проект — MVP, а не production-ready релиз. Лицензия не выбрана.
