from fastapi import APIRouter, HTTPException, Depends
import httpx

from backend.auth import get_current_user
from backend.config import TIKTOK_WATCHER_URL
from backend.models import TikTokImportReq

router = APIRouter(prefix="/api/tiktok", tags=["tiktok"])

_WATCHER_TIMEOUT = httpx.Timeout(30.0)


def _check_configured() -> str:
    if not TIKTOK_WATCHER_URL:
        raise HTTPException(
            503, "зеркало дня недоступно (не настроен TIKTOK_WATCHER_URL)"
        )
    return TIKTOK_WATCHER_URL


@router.post("/import")
async def import_tiktok(req: TikTokImportReq, user_id: int = Depends(get_current_user)):
    """Передать ссылку в «Зеркало дня» (watcher). Заметка вернётся через /api/notes/import."""
    base = _check_configured()
    url = req.url.strip()
    if "tiktok.com" not in url.lower():
        raise HTTPException(400, "нужна ссылка на видео TikTok")
    try:
        async with httpx.AsyncClient(timeout=_WATCHER_TIMEOUT) as client:
            r = await client.post(
                f"{base}/api/tiktok",
                json={"url": url, "note_date": req.note_date},
            )
    except Exception as e:
        raise HTTPException(502, f"зеркало дня не ответило ({type(e).__name__})")
    if r.status_code >= 400:
        raise HTTPException(502, "зеркало дня не приняло ссылку")
    return r.json()


@router.get("")
async def list_tiktok(day: str = "", user_id: int = Depends(get_current_user)):
    """Список задач дня из зеркала дня (для вкладки «Тикток»)."""
    base = _check_configured()
    try:
        async with httpx.AsyncClient(timeout=_WATCHER_TIMEOUT) as client:
            r = await client.get(f"{base}/api/tiktok", params={"day": day})
    except Exception:
        raise HTTPException(502, "зеркало дня не ответило")
    if r.status_code >= 400:
        raise HTTPException(502, "зеркало дня недоступно")
    return r.json()


@router.get("/{task_id}")
async def tiktok_status(task_id: int, user_id: int = Depends(get_current_user)):
    """Статус задачи из зеркала дня."""
    base = _check_configured()
    try:
        async with httpx.AsyncClient(timeout=_WATCHER_TIMEOUT) as client:
            r = await client.get(f"{base}/api/tiktok/{task_id}")
    except Exception:
        raise HTTPException(502, "зеркало дня не ответило")
    if r.status_code == 404:
        raise HTTPException(404, "задача не найдена")
    if r.status_code >= 400:
        raise HTTPException(502, "зеркало дня недоступно")
    data = r.json()
    return {
        "id": data.get("id"),
        "status": data.get("status", "pending"),
        "error": data.get("error"),
        "curator_note_id": data.get("curator_note_id"),
        "title": data.get("title", ""),
        "author": data.get("author", ""),
        "note_date": data.get("note_date", ""),
    }
