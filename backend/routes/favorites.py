from fastapi import APIRouter, Depends
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
import json

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


@router.get("")
async def get_favorites(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        note_rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, ai_summary,
                      ai_category, created_at
               FROM notes WHERE user_id=$1 AND is_favorited=1
               ORDER BY created_at DESC""",
            user_id,
        )
        notes = []
        for r in note_rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            notes.append(
                {
                    "id": r["id"],
                    "content": content,
                    "note_date": r["note_date"],
                    "ai_summary": r["ai_summary"],
                    "ai_category": r["ai_category"],
                    "created_at": r["created_at"],
                }
            )

        task_rows = await db.fetch(
            """SELECT id, title_encrypted, due_date, due_time,
                      priority, completed
               FROM tasks WHERE user_id=$1 AND is_favorited=1 AND completed=0
               ORDER BY due_date ASC""",
            user_id,
        )
        tasks = []
        for r in task_rows:
            tasks.append(
                {
                    "id": r["id"],
                    "title": decrypt(r["title_encrypted"]),
                    "due_date": r["due_date"],
                    "due_time": r["due_time"],
                    "priority": r["priority"],
                    "completed": r["completed"],
                }
            )

        return {"notes": notes, "tasks": tasks}
