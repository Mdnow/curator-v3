# ADR-0010 — Переход: Render — основной деплой всех проектов

- **Дата:** 11.08.2026
- **Статус:** accepted
- **Заменяет:** ADR-0005 (Railway)

## Контекст

Триал Railway подходит к концу, оплата зарубежных сервисов из РФ невозможна,
Railway без VPN из РФ недоступен (оператор режет CDN `69.46.46.x`).
Проекты семейства нуждаются в бесплатном и доступном из РФ хостинге.

## Решение

- **Render — основной деплой** для curator-v3 и tiktok-watcher
  (plan free, регион frankfurt, runtime docker).
  - curator-v3: `https://curator-v3.onrender.com`
  - tiktok-watcher: `https://tiktok-watcher-b7lr.onrender.com`
- **ADR-0005 признан superseded** (заменён ADR-0010).
- Клиенты куратора обновлены на Render-домен:
  - tiktok-watcher `CURATOR_URL` → `https://curator-v3.onrender.com`
  - daily-os `CURATOR_URL` → `https://curator-v3.onrender.com`
- Railway остаётся доживать триал как fallback, после стабильной работы
  Render (2-3 дня) сервисы Railway удаляются.

## Альтернативы

- Koyeb / Hugging Face / Fly.io / Oracle / Cloud Run — см. ADR-0009.
- Публичный GitHub для приватного репо tiktok-watcher — отклонено;
  вместо этого установлен GitHub App Render (Only select repositories).

## Последствия

- Render free спит через 15 мин без трафика (cold start ~5-30с).
- Домены `onrender.com` — при необходимости правки CORS (ADR-0005).
- Секреты заданы в переменных Render (в git не попадают: `.dockerignore`).
- API-ключ Render после завершения миграции отзывается.
- Деплой обоих проектов — через git push (автодеплой Render).
