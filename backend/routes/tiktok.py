from fastapi import APIRouter, HTTPException, Depends
from datetime import date
import asyncio

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import TikTokImportReq
from backend.tiktok_pipeline import process_task

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
            """SELECT id, url, note_date, status, error, author, title, note_id
               FROM tiktok_tasks
               WHERE user_id=$1 AND ($2='' OR note_date=$2)
               ORDER BY id DESC""",
            user_id,
            day,
        )
    return [dict(r) for r in rows]


@router.get("/{task_id}")
async def tiktok_status(task_id: int, user_id: int = Depends(get_current_user)):
    """Статус задачи (поллинг фронта)."""
    async with get_db() as db:
        row = await db.fetchrow(
            """SELECT id, url, note_date, status, error, author, title, note_id
               FROM tiktok_tasks WHERE id=$1 AND user_id=$2""",
            task_id,
            user_id,
        )
    if not row:
        raise HTTPException(404, "задача не найдена")
    return dict(row)
