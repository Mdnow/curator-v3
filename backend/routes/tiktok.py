from fastapi import APIRouter, HTTPException, Depends
from datetime import date
import asyncio
import json

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import TikTokImportReq, TikTokSkillReq
from backend.tiktok_pipeline import process_task
from backend.tiktok_skills import run_skill

router = APIRouter(prefix="/api/tiktok", tags=["tiktok"])


@router.post("/import")
async def import_tiktok(req: TikTokImportReq, user_id: int = Depends(get_current_user)):
    """Ссылка TikTok → фоновый воркер (скачивание → транскрипция → перевод) → заметка."""
    url = req.url.strip()
    if "tiktok.com" not in url.lower():
        raise HTTPException(400, "нужна ссылка на видео TikTok")
    note_date = req.note_date or date.today().isoformat()
    async with get_db() as db:
        row = await db.fetchrow(
            """INSERT INTO tiktok_tasks (user_id, url, note_date)
               VALUES ($1,$2,$3) RETURNING id""",
            user_id,
            url,
            note_date,
        )
        task_id = row["id"]
    asyncio.get_running_loop().create_task(process_task(task_id, user_id))
    return {"id": task_id, "status": "pending"}


@router.get("")
async def list_tiktok(day: str = "", user_id: int = Depends(get_current_user)):
    """Задачи дня (для вкладки «Тикток»)."""
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT id, url, note_date, status, error, author, title, note_id,
                      description, hashtags, duration, ai_hook, ai_map, ai_viral
               FROM tiktok_tasks
               WHERE user_id=$1 AND ($2='' OR note_date=$2)
               ORDER BY id DESC""",
            user_id,
            day,
        )
    return [_serialize(r) for r in rows]


@router.get("/{task_id}")
async def tiktok_status(task_id: int, user_id: int = Depends(get_current_user)):
    """Статус задачи (поллинг фронта)."""
    async with get_db() as db:
        row = await db.fetchrow(
            """SELECT id, url, note_date, status, error, author, title, note_id,
                      description, hashtags, duration, ai_hook, ai_map, ai_viral
               FROM tiktok_tasks WHERE id=$1 AND user_id=$2""",
            task_id,
            user_id,
        )
    if not row:
        raise HTTPException(404, "задача не найдена")
    return _serialize(row)


@router.post("/{task_id}/skill")
async def tiktok_skill(
    task_id: int,
    req: TikTokSkillReq,
    user_id: int = Depends(get_current_user),
):
    """AI-скилл поверх готовой заметки задачи (ADR-0020)."""
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT status, note_id FROM tiktok_tasks WHERE id=$1 AND user_id=$2",
            task_id,
            user_id,
        )
    if not row:
        raise HTTPException(404, "задача не найдена")
    if row["status"] != "done" or not row["note_id"]:
        raise HTTPException(409, "заметка ещё не готова (задача не завершена)")
    return await run_skill(task_id, req.skill, user_id)


def _parse_json_field(raw: str | None) -> object:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _serialize(row) -> dict:
    d = dict(row)
    for key in ("hashtags", "ai_map", "ai_viral"):
        d[key] = _parse_json_field(d.get(key))
    return d
