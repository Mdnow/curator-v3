# ADR-0005 — Деплой: Railway, ручной деплой через CLI

- **Дата:** 06.08.2026
- **Статус:** accepted

## Контекст

Нужен публичный прод для «зеркала», доступный с телефона. Требования:
бесплатно/дёшево, простой деплой, переменные окружения и секреты.

## Решение

- Платформа: **Railway** (`railway.json`, Dockerfile).
- Деплой вручную через CLI: `railway up --detach` / `railway link -p curator-v3`.
- Секреты в переменных Railway (`railway variables --set`): `DATABASE_URL`,
  `OPENROUTER_API_KEY`, `CURATOR_SECRET`, `CURATOR_ENCRYPTION_KEY`, `ZEN_API_KEY`.
- `.railwayignore` исключает тесты/`.env`/`*.png`.
- Прод-домен `curator-v3-production.up.railway.app` захардкожен в CORS.

## Альтернативы

- Docker на VPS (Vercel/Fly/etc.) — отклонено: больше ручного обслуживания.
- Render — рассматривался, выбран Railway по опыту/простоте.

## Последствия

- Деплой = одна команда, откат = повторный деплой предыдущего коммита.
- Секреты живут на Railway; утечка `.env` в git запрещена (.gitignore).
- Прод-URL меняется → правка CORS в `backend/main.py`.
