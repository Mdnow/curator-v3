from fastapi import APIRouter, Depends
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
from datetime import datetime
import json

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
async def backup_data(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        notes_rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, tags,
                      is_favorited, ai_summary, ai_category, ai_sentiment,
                      ai_keyphrases, ai_theses, thread_id, mood, created_at
               FROM notes WHERE user_id=$1 ORDER BY created_at""",
            user_id,
        )
        notes = []
        for r in notes_rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            keyphrases = []
            if r["ai_keyphrases"]:
                try:
                    keyphrases = json.loads(r["ai_keyphrases"])
                except Exception:
                    pass
            theses = []
            if r["ai_theses"]:
                try:
                    theses = json.loads(r["ai_theses"])
                except Exception:
                    pass
            notes.append(
                {
                    "id": r["id"],
                    "content": content,
                    "note_date": r["note_date"],
                    "tags": json.loads(r["tags"]) if r["tags"] else [],
                    "is_favorited": r["is_favorited"],
                    "ai_summary": r["ai_summary"] or "",
                    "ai_category": r["ai_category"] or "",
                    "ai_sentiment": float(r["ai_sentiment"])
                    if r["ai_sentiment"]
                    else 0.0,
                    "ai_keyphrases": keyphrases,
                    "ai_theses": theses,
                    "thread_id": r["thread_id"] or "",
                    "mood": r["mood"] or "",
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )

        tasks_rows = await db.fetch(
            """SELECT id, title_encrypted, description_encrypted,
                      due_date, due_time, priority, completed,
                      is_favorited, created_at
               FROM tasks WHERE user_id=$1 ORDER BY created_at""",
            user_id,
        )
        tasks = []
        for r in tasks_rows:
            try:
                title = decrypt(r["title_encrypted"])
            except Exception:
                title = ""
            try:
                desc = (
                    decrypt(r["description_encrypted"])
                    if r["description_encrypted"]
                    else ""
                )
            except Exception:
                desc = ""
            tasks.append(
                {
                    "id": r["id"],
                    "title": title,
                    "description": desc,
                    "due_date": r["due_date"],
                    "due_time": r["due_time"],
                    "priority": r["priority"],
                    "completed": r["completed"],
                    "is_favorited": r["is_favorited"],
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )

        dream_rows = await db.fetch(
            """SELECT id, content_encrypted, dream_type, sleep_time,
                      wake_time, sleep_quality, emotion_label,
                      emotion_valence, ai_symbols, ai_themes,
                      ai_summary, ai_question, linked_note_ids, created_at
               FROM dreams WHERE user_id=$1 ORDER BY created_at""",
            user_id,
        )
        dreams = []
        for r in dream_rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            symbols = json.loads(r["ai_symbols"]) if r["ai_symbols"] else []
            themes = json.loads(r["ai_themes"]) if r["ai_themes"] else []
            dreams.append(
                {
                    "id": r["id"],
                    "content": content,
                    "dream_type": r["dream_type"],
                    "sleep_time": r["sleep_time"] or "",
                    "wake_time": r["wake_time"] or "",
                    "sleep_quality": r["sleep_quality"],
                    "emotion_label": r["emotion_label"] or "",
                    "emotion_valence": float(r["emotion_valence"])
                    if r["emotion_valence"]
                    else 0.0,
                    "ai_symbols": symbols,
                    "ai_themes": themes,
                    "ai_summary": r["ai_summary"] or "",
                    "ai_question": r["ai_question"] or "",
                    "linked_note_ids": r["linked_note_ids"] or [],
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )

        chat_rows = await db.fetch(
            """SELECT role, content, created_at, session_id
               FROM chat_history WHERE user_id=$1 ORDER BY created_at""",
            user_id,
        )
        chats = []
        for r in chat_rows:
            chats.append(
                {
                    "role": r["role"],
                    "content": r["content"],
                    "time": str(r["created_at"]) if r["created_at"] else "",
                    "session_id": r["session_id"],
                }
            )

        return {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "notes": notes,
            "tasks": tasks,
            "dreams": dreams,
            "chat_history": chats,
            "stats": {
                "notes": len(notes),
                "tasks": len(tasks),
                "dreams": len(dreams),
                "chats": len(chats),
            },
        }
