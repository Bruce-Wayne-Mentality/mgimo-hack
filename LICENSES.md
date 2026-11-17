# Сторонние компоненты и лицензии

Все компоненты используются без изменений. Логотип и иллюстрации — собственные; изображений и логотипов вузов в проекте нет.

## Шрифты

| Компонент | Где | Лицензия |
| --- | --- | --- |
| Onest (Regular, Medium, Bold) | интерфейс (Google Fonts) и PDF-документы (`hse_schedule/assets/fonts`, текст лицензии — `OFL.txt`) | SIL Open Font License 1.1 |

## Фронтенд (`apps/web`)

| Пакет | Версия | Лицензия |
| --- | --- | --- |
| react, react-dom | 19.3 | MIT |
| react-router | 8.5 | MIT |
| @tanstack/react-query | 5.107 | MIT |
| react-hook-form, @hookform/resolvers | 7.92 / 7.0 | MIT |
| zod | 4.6 | MIT |
| tailwindcss, tailwind-merge, clsx | 4.3 / 3.7 / 2.1 | MIT |
| lucide-react (иконки) | 1.72 | ISC |
| motion | 14.14 | MIT |
| vite, vitest, typescript, @testing-library/* (сборка и тесты) | — | MIT / Apache-2.0 |

## Бэкенд (`hse_schedule`)

| Пакет | Версия | Лицензия |
| --- | --- | --- |
| fastapi, pydantic | 0.162 / 2.14 | MIT |
| uvicorn | 0.54 | BSD-3-Clause |
| SQLAlchemy, alembic | 2.1 / 1.20 | MIT |
| asyncpg | 0.32 | Apache-2.0 |
| aiosqlite | 0.22 | MIT |
| argon2-cffi | 25.1 | MIT |
| reportlab (PDF) | 5.1 | BSD |
| segno (QR-коды) | 1.6 | BSD-3-Clause |
| pillow (зависимость reportlab) | 13.0 | MIT-CMU |
| httpx | 0.28 | BSD-3-Clause |
| pywebpush (Web Push) | 2.5 | MPL-2.0 — слабый копилефт: используем без изменений, исходный код библиотеки не модифицируем |

## Инфраструктура

| Компонент | Лицензия |
| --- | --- |
| PostgreSQL 16 | PostgreSQL License |
| Caddy | Apache-2.0 |
