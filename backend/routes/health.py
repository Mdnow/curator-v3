from fastapi import APIRouter
from backend.db import get_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    async with get_db() as db:
        try:
            await db.fetchval("SELECT 1")
            return {"status": "ok", "database": "postgresql", "version": "3.0"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
