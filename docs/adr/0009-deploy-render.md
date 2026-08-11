# ADR-0009 — Деплой: Render (параллельно Railway)

- **Дата:** 11.08.2026
- **Статус:** accepted
- **Заменён на:** —

## Контекст

Триал Railway подходит к концу; оплата зарубежных сервисов из РФ невозможна.
Railway без VPN из РФ недоступен. Нужен бесплатный хостинг приложения
(БД уже отдельно — Neon).

## Решение

- Приложение развёрнуто на **Render** (`https://curator-v3.onrender.com`),
  runtime docker, plan free, регион frankfurt — параллельно Railway.
- Критерии выбора: free tier без карты, работает из РФ без VPN, Docker +
  секреты, git-деплой.
- В репо добавлены `render.yaml` (blueprint) и `.dockerignore` (секреты
  не попадают в образ; Render читает `.dockerignore`, а не `.railwayignore`).
- CORS расширен доменом из `RENDER_EXTERNAL_URL` (Render задаёт его сам).
- Прод по умолчанию остаётся Railway; решение о миграции — после
  стабильной проверки Render.

## Альтернативы

- Koyeb — риск ID-верификации/блокировки для РФ-аккаунтов.
- Hugging Face Spaces — Docker-пространства только за PRO (с 2026).
- Fly.io / Oracle / Cloud Run — free tier требует зарубежную карту.
- Apploy (РФ) — план Б: молодой сервис, 256MB RAM впритык.

## Последствия

- Render free спит через 15 мин без трафика (cold start ~5-30с);
  при необходимости держать тёплым — UptimeRobot-пинг.
- Смена прод-URL → правка CORS в `backend/main.py` (см. ADR-0005).
- Расход памяти подтверждён (~60MB idle) — 512MB хватает с запасом.
