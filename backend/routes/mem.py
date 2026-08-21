from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from datetime import date

from backend.auth import get_current_user
from backend.db import get_db
from backend.crypto import encrypt
from backend.models import MemImportReq, MemExportReq
from backend import mem_api
from backend.ai import embed_text
from backend import mem_sync
import json

router = APIRouter(prefix="/api/mem", tags=["mem"])


def _require_mem():
    if not mem_api.is_configured():
        raise HTTPException(400, "Mem API ключ не настроен (MEM_API_KEY)")


@router.get("/search")
async def mem_search(
    q: str = "", limit: int = 5, user_id: int = Depends(get_current_user)
):
    """Поиск заметок в Mem по смыслу. q — свободный запрос."""
    _require_mem()
    q = q.strip()
    if not q:
        raise HTTPException(400, "нужен текст запроса (q)")
    limit = min(max(limit, 1), 50)
    try:
        results = await mem_api.mem_search(q, limit=limit)
    except RuntimeError as e:
        raise HTTPException(502, f"Mem API: {e}")
    return {"query": q, "results": results}


@router.post("/import")
async def mem_import(
    req: MemImportReq, bg: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    """Заметка Mem → заметка Куратора (тег mem). note_id из Mem API."""
    _require_mem()
    try:
        note = await mem_api.mem_read(req.note_id)
    except RuntimeError as e:
        raise HTTPException(502, f"Mem API: {e}")
    content = note["content"].strip()
    if not content:
        raise HTTPException(400, "заметка Mem пуста")
    note_date = (req.note_date or date.today().isoformat())[:10]
    tags = list(set((req.tags or []) + ["mem"]))
    async with get_db() as db:
        enc = encrypt(content)
        tags_json = json.dumps(tags)
        row = await db.fetchrow(
            """INSERT INTO notes (user_id, content_encrypted, note_date, tags)
               VALUES ($1,$2,$3,$4) RETURNING id""",
            user_id,
            enc,
            note_date,
            tags_json,
        )
        note_id_local = row["id"]

    async def _embed():
        from backend.db import get_pool

        pool = await get_pool()
        vec = await embed_text(content)
        if vec:
            async with pool.acquire() as db:
                await db.execute(
                    """INSERT INTO note_embeddings (note_id, user_id, embedding)
                       VALUES ($1,$2,$3) ON CONFLICT (note_id) DO UPDATE SET embedding=$3""",
                    note_id_local,
                    user_id,
                    str(vec),
                )

    bg.add_task(_embed)
    return {"id": note_id_local, "title": note["title"], "source": "mem"}


@router.post("/export")
async def mem_export(req: MemExportReq, user_id: int = Depends(get_current_user)):
    """Заметка Куратора → заметка в Mem. Первая строка content — заголовок Mem."""
    _require_mem()
    content = req.content.strip()
    if not content:
        raise HTTPException(400, "content пуст")
    try:
        created = await mem_api.mem_create(content)
    except RuntimeError as e:
        raise HTTPException(502, f"Mem API: {e}")
    return {"mem_id": created["id"], "title": created["title"]}


@router.post("/sync")
async def mem_sync_start(user_id: int = Depends(get_current_user)):
    """Запуск синка Obsidian-базы в mem_notes (локально, без VPN)."""
    result = await mem_sync.run_obsidian_sync()
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/sync-status")
async def mem_sync_status(user_id: int = Depends(get_current_user)):
    return mem_sync.sync_status()


@router.get("/search-local")
async def mem_search_local(
    q: str = "", limit: int = 8, user_id: int = Depends(get_current_user)
):
    """Поиск по синкнутой Obsidian-базе (локально, по смыслу)."""
    q = q.strip()
    if not q:
        raise HTTPException(400, "нужен текст запроса (q)")
    limit = min(max(limit, 1), 20)
    results = await mem_sync.mem_search_local(q, limit=limit)
    return {"query": q, "count": len(results), "results": results}
