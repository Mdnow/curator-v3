from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import DreamReq
from backend.ai import analyze_dream
import json

router = APIRouter(prefix="/api/dreams", tags=["dreams"])


async def _analyze_dream_in_background(dream_id: int, content: str):
    from backend.db import get_pool

    ai = await analyze_dream(content)
    if ai.get("symbols") or ai.get("themes"):
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                """UPDATE dreams SET
                   ai_symbols=$1, ai_themes=$2, ai_summary=$3,
                   ai_question=$4, emotion_valence=$5
                   WHERE id=$6""",
                json.dumps(ai.get("symbols", [])),
                json.dumps(ai.get("themes", [])),
                ai.get("summary", ""),
                ai.get("question", ""),
                ai.get("valence", 0.0),
                dream_id,
            )


@router.post("")
async def create_dream(
    req: DreamReq, bg: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        enc = encrypt(req.content)
        row = await db.fetchrow(
            """INSERT INTO dreams (user_id, content_encrypted, dream_type,
                                   sleep_time, wake_time, sleep_quality,
                                   emotion_label)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            user_id,
            enc,
            req.dream_type,
            req.sleep_time or "",
            req.wake_time or "",
            req.sleep_quality,
            req.emotion_label or "",
        )
        dream_id = row["id"]

    bg.add_task(_analyze_dream_in_background, dream_id, req.content)
    return {"id": dream_id}


@router.get("")
async def get_dreams(
    date: str = "", days: int = 30, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        if date:
            rows = await db.fetch(
                """SELECT id, content_encrypted, dream_type, sleep_time,
                          wake_time, sleep_quality, emotion_label,
                          emotion_valence, ai_symbols, ai_themes,
                          ai_summary, ai_question, linked_note_ids,
                          created_at
                   FROM dreams WHERE user_id=$1
                   AND DATE(created_at) = $2
                   ORDER BY created_at DESC""",
                user_id,
                date,
            )
        else:
            rows = await db.fetch(
                """SELECT id, content_encrypted, dream_type, sleep_time,
                          wake_time, sleep_quality, emotion_label,
                          emotion_valence, ai_symbols, ai_themes,
                          ai_summary, ai_question, linked_note_ids,
                          created_at
                   FROM dreams WHERE user_id=$1
                   AND created_at > NOW() - INTERVAL '{} days'
                   ORDER BY created_at DESC""".format(days),
                user_id,
            )
        dreams = []
        for r in rows:
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
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )
        return dreams


@router.get("/timeline")
async def dream_timeline(days: int = 30, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT DATE(created_at) as day, COUNT(*) as cnt,
                      AVG(emotion_valence) as avg_valence,
                      AVG(sleep_quality) as avg_quality
               FROM dreams WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '{} days'
               GROUP BY DATE(created_at)
               ORDER BY day ASC""".format(days),
            user_id,
        )
        return [
            {
                "date": str(r["day"]),
                "count": r["cnt"],
                "avg_valence": float(r["avg_valence"]) if r["avg_valence"] else 0.0,
                "avg_quality": float(r["avg_quality"]) if r["avg_quality"] else None,
            }
            for r in rows
        ]


@router.get("/insight")
async def dream_insight_endpoint(user_id: int = Depends(get_current_user)):
    from backend.ai import dream_insight as ai_dream_insight

    async with get_db() as db:
        today = await db.fetchval("SELECT CURRENT_DATE::text")

        night_row = await db.fetchrow(
            """SELECT content_encrypted, sleep_quality
               FROM dreams WHERE user_id=$1 AND dream_type='night'
               AND DATE(created_at) = $2
               ORDER BY created_at DESC LIMIT 1""",
            user_id,
            today,
        )
        morning_row = await db.fetchrow(
            """SELECT content_encrypted
               FROM dreams WHERE user_id=$1 AND dream_type='morning'
               AND DATE(created_at) = $2
               ORDER BY created_at DESC LIMIT 1""",
            user_id,
            today,
        )

        night_text = ""
        night_quality = None
        if night_row:
            try:
                night_text = decrypt(night_row["content_encrypted"])
            except Exception:
                pass
            night_quality = night_row["sleep_quality"]

        morning_text = ""
        if morning_row:
            try:
                morning_text = decrypt(morning_row["content_encrypted"])
            except Exception:
                pass

        note_rows = await db.fetch(
            """SELECT content_encrypted, note_date FROM notes
               WHERE user_id=$1 AND note_date >= $2::text - INTERVAL '7 days'
               ORDER BY created_at DESC LIMIT 20""",
            user_id,
            today,
        )
        context_parts = []
        for r in note_rows:
            try:
                text = decrypt(r["content_encrypted"])
                context_parts.append(f"[{r['note_date']}] {text[:100]}")
            except Exception:
                pass

        dream_rows = await db.fetch(
            """SELECT content_encrypted, dream_type, created_at::text as day
               FROM dreams WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '7 days'
               ORDER BY created_at DESC LIMIT 10""",
            user_id,
        )
        for r in dream_rows:
            try:
                text = decrypt(r["content_encrypted"])
                context_parts.append(f"[{r['day'][:10]} {r['dream_type']}] {text[:80]}")
            except Exception:
                pass

        context = "\n".join(context_parts) if context_parts else "(нет данных)"

    insight = await ai_dream_insight(night_text, morning_text, night_quality, context)

    return {
        "insight": insight,
        "has_night": bool(night_text),
        "has_morning": bool(morning_text),
    }


@router.get("/patterns")
async def dream_patterns(days: int = 30, user_id: int = Depends(get_current_user)):
    from backend.ai import daily_patterns as ai_daily_patterns

    async with get_db() as db:
        note_rows = await db.fetch(
            """SELECT content_encrypted, ai_category, ai_sentiment, note_date
               FROM notes WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '{} days'
               ORDER BY created_at DESC LIMIT 30""".format(days),
            user_id,
        )
        note_parts = []
        for r in note_rows:
            try:
                text = decrypt(r["content_encrypted"])
                cat = r["ai_category"] or "?"
                sent = float(r["ai_sentiment"]) if r["ai_sentiment"] else 0
                note_parts.append(
                    f"[{r['note_date']}] ({cat}, sentiment={sent:.1f}) {text[:80]}"
                )
            except Exception:
                pass

        dream_rows = await db.fetch(
            """SELECT content_encrypted, dream_type, ai_symbols, emotion_valence,
                      created_at::text as day
               FROM dreams WHERE user_id=$1
               AND created_at > NOW() - INTERVAL '{} days'
               ORDER BY created_at DESC LIMIT 20""".format(days),
            user_id,
        )
        dream_parts = []
        for r in dream_rows:
            try:
                text = decrypt(r["content_encrypted"])
                symbols = json.loads(r["ai_symbols"]) if r["ai_symbols"] else []
                val = float(r["emotion_valence"]) if r["emotion_valence"] else 0
                dream_parts.append(
                    f"[{r['day'][:10]} {r['dream_type']}] (symbols={symbols}, valence={val:.1f}) {text[:80]}"
                )
            except Exception:
                pass

    notes_text = "\n".join(note_parts) if note_parts else "(нет заметок)"
    dreams_text = "\n".join(dream_parts) if dream_parts else "(нет снов)"

    patterns = await ai_daily_patterns(notes_text, dreams_text)
    return patterns
