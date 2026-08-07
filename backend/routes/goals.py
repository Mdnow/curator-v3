from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
from backend.ai import generate_goals
import json

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _row_to_goal(r) -> dict:
    def _parse(s: str):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    return {
        "id": r["id"],
        "title": r["title"],
        "description": r["description"],
        "evidence": _parse(r["evidence"]),
        "thread_ids": _parse(r["thread_ids"]),
        "categories": _parse(r["categories"]),
        "source_count": r["source_count"],
        "is_pinned": bool(r["is_pinned"]),
        "created_at": str(r["created_at"]) if r["created_at"] else "",
        "updated_at": str(r["updated_at"]) if r["updated_at"] else "",
    }


async def _generate_in_background(user_id: int):
    from backend.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, ai_category, thread_id
               FROM notes WHERE user_id=$1
               ORDER BY created_at DESC LIMIT 100""",
            user_id,
        )
        note_parts = []
        date_map = {}
        for r in rows:
            try:
                text = decrypt(r["content_encrypted"])
            except Exception:
                continue
            if not text or not text.strip():
                continue
            note_parts.append(f"[id={r['id']}] ({r['note_date']}) {text[:400]}")
            date_map[r["id"]] = r["note_date"]

    notes_text = "\n\n".join(note_parts) if note_parts else ""
    result = await generate_goals(notes_text)
    if "error" in result:
        print(f"[goals] generate FAIL: {result['error']}", flush=True)
        return

    new_goals = result["goals"]
    async with pool.acquire() as db:
        existing = await db.fetch("SELECT title FROM goals WHERE user_id=$1", user_id)
        existing_titles = {g["title"].strip().lower() for g in existing}

        added = 0
        for g in new_goals:
            if g["title"].strip().lower() in existing_titles:
                continue
            evidence = []
            for e in g["evidence"]:
                nid = e.get("note_id")
                if isinstance(nid, str) and nid.isdigit():
                    nid = int(nid)
                evidence.append(
                    {
                        "note_id": nid,
                        "note_date": date_map.get(nid, ""),
                        "quote": e.get("quote", ""),
                    }
                )
            await db.execute(
                """INSERT INTO goals
                   (user_id, title, description, evidence, thread_ids, categories, source_count)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                user_id,
                g["title"],
                g["description"],
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(g["thread_ids"], ensure_ascii=False),
                json.dumps(g["categories"], ensure_ascii=False),
                len(evidence),
            )
            existing_titles.add(g["title"].strip().lower())
            added += 1
        print(f"[goals] added {added} new, total existing {len(existing)}", flush=True)


@router.get("")
async def get_goals(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT * FROM goals WHERE user_id=$1
               ORDER BY is_pinned DESC, updated_at DESC""",
            user_id,
        )
        return [_row_to_goal(r) for r in rows]


@router.get("/{goal_id}")
async def get_goal(goal_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT * FROM goals WHERE id=$1 AND user_id=$2", goal_id, user_id
        )
        if not row:
            raise HTTPException(404, "цель не найдена")
        return _row_to_goal(row)


@router.post("/generate")
async def generate_goals_endpoint(
    bg: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    bg.add_task(_generate_in_background, user_id)
    return {"status": "started"}


@router.delete("/{goal_id}")
async def delete_goal(goal_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM goals WHERE id=$1 AND user_id=$2", goal_id, user_id
        )
        return {"ok": True}


@router.post("/{goal_id}/pin")
async def pin_goal(goal_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT id, is_pinned FROM goals WHERE id=$1 AND user_id=$2",
            goal_id,
            user_id,
        )
        if not row:
            raise HTTPException(404, "цель не найдена")
        new_val = 0 if row["is_pinned"] else 1
        await db.execute(
            "UPDATE goals SET is_pinned=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2 AND user_id=$3",
            new_val,
            goal_id,
            user_id,
        )
        return {"is_pinned": new_val}
