from fastapi import APIRouter, Depends
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
from backend.ai import daily_patterns
import json

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/daily")
async def daily_insight(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        note_rows = await db.fetch(
            """SELECT content_encrypted, ai_category, ai_sentiment, note_date
               FROM notes WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '7 days'
               ORDER BY created_at DESC LIMIT 30""",
            user_id,
        )
        note_parts = []
        for r in note_rows:
            try:
                text = decrypt(r["content_encrypted"])
                cat = r["ai_category"] or "?"
                sent = float(r["ai_sentiment"]) if r["ai_sentiment"] else 0
                note_parts.append(f"[{r['note_date']}] ({cat}, {sent:.1f}) {text[:80]}")
            except Exception:
                pass

        dream_rows = await db.fetch(
            """SELECT content_encrypted, dream_type, ai_symbols, created_at::text as day
               FROM dreams WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '7 days'
               ORDER BY created_at DESC LIMIT 15""",
            user_id,
        )
        dream_parts = []
        for r in dream_rows:
            try:
                text = decrypt(r["content_encrypted"])
                symbols = json.loads(r["ai_symbols"]) if r["ai_symbols"] else []
                dream_parts.append(
                    f"[{r['day'][:10]} {r['dream_type']}] (s={symbols}) {text[:60]}"
                )
            except Exception:
                pass

    notes_text = "\n".join(note_parts) if note_parts else "(нет заметок)"
    dreams_text = "\n".join(dream_parts) if dream_parts else "(нет снов)"

    patterns = await daily_patterns(notes_text, dreams_text)
    return patterns
