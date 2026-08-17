"""Деплой curator-v3 на Render через API.

Использование:
  python deploy_render.py status           — последние деплои и их статус
  python deploy_render.py deploy           — ручной редеплой последнего коммита
  python deploy_render.py logs [deploy_id] — события сборки/деплоя сервиса
                                            (по умолчанию — последние 50)

Ключ читается из RENDER_API_KEY в .env (в git не попадает).
SERVICE_ID — curator-v3 на Render (смотри docs/adr/0010).
"""

import json
import os
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "srv-d9tdhiht0dsc73b1o1kg")
API = "https://api.render.com/v1"


def _load_key() -> str:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("RENDER_API_KEY="):
                    return line.split("=", 1)[1].strip()
    key = os.getenv("RENDER_API_KEY", "")
    if not key:
        sys.exit("RENDER_API_KEY не найден: добавь в .env или окружение")
    return key


def api(path, method="GET", body=None, key: str | None = None):
    key = key or _load_key()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    r = urllib.request.urlopen(req, timeout=90)
    raw = r.read()
    return json.loads(raw) if raw else None


def _short(id_: str) -> str:
    return id_[:8]


def status():
    deploys = api(f"/services/{SERVICE_ID}/deploys?limit=6")
    print(f"Сервис: {SERVICE_ID}")
    for item in deploys:
        d = item["deploy"]
        commit = (d.get("commit") or {}).get("id", "?")
        print(
            f"  {d['id']}  commit={_short(commit)}  "
            f"status={d['status']}  trigger={d['trigger']}  "
            f"created={d['createdAt'][:19]}"
        )


def deploy():
    d = api(
        f"/services/{SERVICE_ID}/deploys",
        method="POST",
        body={"clearCache": "do_not_clear"},
    )
    dep = d.get("deploy", d)
    print(f"Деплой запущен: {dep['id']} status={dep['status']}")
    print(
        f"Следить: https://dashboard.render.com/web/{SERVICE_ID}/deploys/{dep['id']}/events"
    )


def logs(deploy_id: str | None):
    """События сервиса (сборка/деплой) по API. Полные логи сборки — только в дашборде."""
    events = api(f"/services/{SERVICE_ID}/events?limit=50")
    shown = 0
    for item in events:
        e = item.get("event", {})
        details = e.get("details", {}) or {}
        if (
            deploy_id
            and details.get("deployId") != deploy_id
            and details.get("buildId") != deploy_id
        ):
            continue
        ts = e.get("timestamp", "")[:19]
        status = (
            details.get("deployStatus")
            or details.get("buildStatus")
            or details.get("status", "")
        )
        print(f"[{ts}] {e.get('type')}  {status}")
        shown += 1
    if deploy_id and not shown:
        print(f"Событий для {deploy_id} не найдено (за последние 50 событий сервиса).")
    if not deploy_id and not shown:
        print("Событий нет.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "deploy":
        deploy()
    elif cmd == "logs":
        logs(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        sys.exit(f"неизвестная команда: {cmd}")
