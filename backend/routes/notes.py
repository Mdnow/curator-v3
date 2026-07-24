from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import NoteReq, NoteUpdateReq
from backend.ai import analyze_note, thread_suggest
import json

router = APIRouter(prefix="/api/notes", tags=["notes"])


async def _analyze_in_background(note_id: int, content: str, user_id: int):
    from backend.db import get_pool

    ai = await analyze_note(content)

    pool = await get_pool()
    async with pool.acquire() as db:
        if ai.get("summary") or ai.get("category"):
            await db.execute(
                "UPDATE notes SET ai_summary=$1, ai_category=$2, ai_sentiment=$3, ai_keyphrases=$4 WHERE id=$5",
                ai.get("summary", ""),
                ai.get("category", ""),
                ai.get("sentiment", 0.0),
                json.dumps(ai.get("keyphrases", [])),
                note_id,
            )

        thread_rows = await db.fetch(
            "SELECT DISTINCT thread_id FROM notes WHERE user_id=$1 AND thread_id IS NOT NULL",
            user_id,
        )
        existing = []
        for r in thread_rows:
            trow = await db.fetchrow(
                "SELECT content_encrypted FROM notes WHERE thread_id=$1 LIMIT 1",
                r["thread_id"],
            )
            if trow:
                try:
                    existing.append(
                        {
                            "id": r["thread_id"],
                            "preview": decrypt(trow["content_encrypted"])[:80],
                        }
                    )
                except Exception:
                    pass

    if existing and ai.get("thread_hint"):
        threads_str = "\n".join(f"- {t['id']}: {t['preview']}" for t in existing)
        ts = await thread_suggest(content, threads_str)
        async with pool.acquire() as db:
            if ts.get("thread_id") and ts.get("confidence", 0) > 0.5:
                await db.execute(
                    "UPDATE notes SET thread_id=$1 WHERE id=$2",
                    ts["thread_id"],
                    note_id,
                )
            elif ts.get("thread_name"):
                import uuid

                new_id = str(uuid.uuid4())[:8]
                await db.execute(
                    "UPDATE notes SET thread_id=$1 WHERE id=$2",
                    new_id,
                    note_id,
                )


@router.get("")
async def get_notes(
    date: str, page: int = 1, limit: int = 50, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        offset = (page - 1) * limit
        rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, tags, is_favorited,
                      ai_summary, ai_category, ai_sentiment, ai_keyphrases,
                      thread_id, mood, created_at, updated_at
               FROM notes WHERE user_id=$1 AND note_date=$2
               ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
            user_id,
            date,
            limit,
            offset,
        )
        notes = []
        for r in rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            tags = []
            if r["tags"]:
                try:
                    tags = json.loads(r["tags"])
                except Exception:
                    pass
            keyphrases = []
            if r["ai_keyphrases"]:
                try:
                    keyphrases = json.loads(r["ai_keyphrases"])
                except Exception:
                    pass
            notes.append(
                {
                    "id": r["id"],
                    "content": content,
                    "note_date": r["note_date"],
                    "tags": tags,
                    "is_favorited": r["is_favorited"],
                    "ai_summary": r["ai_summary"] or "",
                    "ai_category": r["ai_category"] or "",
                    "ai_sentiment": float(r["ai_sentiment"])
                    if r["ai_sentiment"]
                    else 0.0,
                    "ai_keyphrases": keyphrases,
                    "thread_id": r["thread_id"] or "",
                    "mood": r["mood"] or "",
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                    "updated_at": str(r["updated_at"]) if r["updated_at"] else "",
                }
            )
        return notes


@router.post("")
async def create_note(
    req: NoteReq, bg: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        enc = encrypt(req.content)
        tags_json = json.dumps(req.tags)
        row = await db.fetchrow(
            """INSERT INTO notes (user_id, content_encrypted, note_date, tags, mood)
               VALUES ($1,$2,$3,$4,$5) RETURNING id""",
            user_id,
            enc,
            req.note_date,
            tags_json,
            req.mood or "",
        )
        note_id = row["id"]

    bg.add_task(_analyze_in_background, note_id, req.content, user_id)
    return {"id": note_id}


@router.put("/{note_id}")
async def update_note(
    note_id: int, req: NoteUpdateReq, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        existing = await db.fetchrow(
            "SELECT id FROM notes WHERE id=$1 AND user_id=$2", note_id, user_id
        )
        if not existing:
            raise HTTPException(404)
        updates = []
        params = []
        idx = 1
        if req.content is not None:
            updates.append(f"content_encrypted=${idx}")
            params.append(encrypt(req.content))
            idx += 1
        if req.tags is not None:
            updates.append(f"tags=${idx}")
            params.append(json.dumps(req.tags))
            idx += 1
        if req.mood is not None:
            updates.append(f"mood=${idx}")
            params.append(req.mood)
            idx += 1
        if not updates:
            return {"ok": True}
        updates.append("updated_at=CURRENT_TIMESTAMP")
        params.extend([note_id, user_id])
        await db.execute(
            f"UPDATE notes SET {', '.join(updates)} WHERE id=${idx} AND user_id=${idx + 1}",
            *params,
        )
        return {"ok": True}


@router.delete("/{note_id}")
async def delete_note(note_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM notes WHERE id=$1 AND user_id=$2", note_id, user_id
        )
        return {"ok": True}


@router.get("/dates")
async def get_notes_dates(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT note_date, COUNT(*) as cnt FROM notes
               WHERE user_id=$1 GROUP BY note_date ORDER BY note_date DESC""",
            user_id,
        )
        return [{"date": r["note_date"], "count": r["cnt"]} for r in rows]


@router.post("/{note_id}/favorite")
async def toggle_note_favorite(note_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        note = await db.fetchrow(
            "SELECT id, is_favorited FROM notes WHERE id=$1 AND user_id=$2",
            note_id,
            user_id,
        )
        if not note:
            raise HTTPException(404)
        new_val = 0 if note["is_favorited"] else 1
        await db.execute(
            "UPDATE notes SET is_favorited=$1 WHERE id=$2 AND user_id=$3",
            new_val,
            note_id,
            user_id,
        )
        return {"is_favorited": new_val}


@router.get("/threads")
async def get_threads(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT thread_id, COUNT(*) as cnt,
                      MIN(created_at) as first, MAX(created_at) as last
               FROM notes WHERE user_id=$1 AND thread_id IS NOT NULL
               GROUP BY thread_id ORDER BY last DESC""",
            user_id,
        )
        threads = []
        for r in rows:
            preview_row = await db.fetchrow(
                "SELECT content_encrypted FROM notes WHERE thread_id=$1 AND user_id=$2 ORDER BY created_at ASC LIMIT 1",
                r["thread_id"],
                user_id,
            )
            preview = ""
            if preview_row:
                try:
                    preview = decrypt(preview_row["content_encrypted"])[:120]
                except Exception:
                    pass
            threads.append(
                {
                    "thread_id": r["thread_id"],
                    "count": r["cnt"],
                    "first": str(r["first"]) if r["first"] else "",
                    "last": str(r["last"]) if r["last"] else "",
                    "preview": preview,
                }
            )
        return threads


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, ai_summary, mood,
                      created_at
               FROM notes WHERE thread_id=$1 AND user_id=$2
               ORDER BY created_at ASC""",
            thread_id,
            user_id,
        )
        notes = []
        for r in rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
            notes.append(
                {
                    "id": r["id"],
                    "content": content,
                    "note_date": r["note_date"],
                    "ai_summary": r["ai_summary"] or "",
                    "mood": r["mood"] or "",
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )
        return notes
