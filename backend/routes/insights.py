from fastapi import APIRouter, Depends, BackgroundTasks
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
from backend.ai import daily_patterns, day_essence
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


async def _essence_in_background(user_id: int, date: str):
    from backend.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT content_encrypted, ai_category, ai_sentiment, note_date
               FROM notes WHERE user_id=$1 AND note_date=$2
               ORDER BY created_at ASC""",
            user_id,
            date,
        )
        parts = []
        for r in rows:
            try:
                text = decrypt(r["content_encrypted"])
            except Exception:
                continue
            if not text or not text.strip():
                continue
            cat = r["ai_category"] or ""
            sent = float(r["ai_sentiment"]) if r["ai_sentiment"] else 0
            parts.append(f"[{cat}, {sent:.1f}] {text[:300]}")

    notes_text = "\n".join(parts) if parts else ""
    result = await day_essence(notes_text)
    if "error" in result:
        print(f"[daymap] essence FAIL ({date}): {result['error']}", flush=True)
        return

    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO day_essences (user_id, date, essence)
               VALUES ($1,$2,$3)
               ON CONFLICT (user_id, date)
               DO UPDATE SET essence=EXCLUDED.essence, updated_at=CURRENT_TIMESTAMP""",
            user_id,
            date,
            result["essence"],
        )
        print(f"[daymap] essence saved ({date}): {result['essence'][:60]}", flush=True)


@router.get("/day-map")
async def day_map(date: str, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT id, content_encrypted, ai_category, ai_sentiment,
                      ai_keyphrases, thread_id
               FROM notes WHERE user_id=$1 AND note_date=$2
               ORDER BY created_at ASC""",
            user_id,
            date,
        )

        cat_agg: dict[str, dict] = {}
        phrase_count: dict[str, int] = {}
        thread_map: dict[str, dict] = {}
        sentiments = []

        for r in rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            sent = float(r["ai_sentiment"]) if r["ai_sentiment"] else 0.0
            sentiments.append(sent)

            cat = (r["ai_category"] or "").strip()
            if cat and cat not in ("без категории", "Другое"):
                a = cat_agg.setdefault(cat, {"count": 0, "sent_sum": 0.0})
                a["count"] += 1
                a["sent_sum"] += sent

            try:
                kp = json.loads(r["ai_keyphrases"]) if r["ai_keyphrases"] else []
            except Exception:
                kp = []
            for p in kp:
                key = str(p).strip().lower()
                if key and len(key) > 1:
                    phrase_count[key] = phrase_count.get(key, 0) + 1

            tid = r["thread_id"]
            if tid:
                t = thread_map.setdefault(tid, {"count": 0, "preview": content[:100]})
                t["count"] += 1

        essence_row = await db.fetchrow(
            "SELECT essence FROM day_essences WHERE user_id=$1 AND date=$2",
            user_id,
            date,
        )

    categories = [
        {
            "name": name,
            "count": agg["count"],
            "sentiment": round(agg["sent_sum"] / agg["count"], 2),
        }
        for name, agg in cat_agg.items()
    ]
    categories.sort(key=lambda c: c["count"], reverse=True)

    phrases = [
        {"phrase": key, "count": cnt}
        for key, cnt in sorted(phrase_count.items(), key=lambda x: -x[1])[:8]
    ]

    threads = [
        {"thread_id": tid, "count": t["count"], "preview": t["preview"]}
        for tid, t in thread_map.items()
    ]
    threads.sort(key=lambda x: x["count"], reverse=True)

    avg_sent = round(sum(sentiments) / len(sentiments), 2) if sentiments else 0.0

    return {
        "date": date,
        "total": len(rows),
        "sentiment": avg_sent,
        "categories": categories,
        "phrases": phrases,
        "threads": threads,
        "essence": essence_row["essence"] if essence_row else "",
    }


@router.post("/day-map/{date}/essence")
async def day_essence_endpoint(
    date: str, bg: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    bg.add_task(_essence_in_background, user_id, date)
    return {"status": "started"}
