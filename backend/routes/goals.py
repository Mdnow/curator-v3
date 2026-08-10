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

    evidence = _parse(r["evidence"])
    last_activity = ""
    for e in evidence:
        d = e.get("note_date", "")
        if d and d > last_activity:
            last_activity = d

    return {
        "id": r["id"],
        "title": r["title"],
        "description": r["description"],
        "evidence": evidence,
        "thread_ids": _parse(r["thread_ids"]),
        "categories": _parse(r["categories"]),
        "source_count": r["source_count"],
        "strength": r["source_count"],
        "last_activity": last_activity,
        "status": r.get("status") or "active",
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
        existing = await db.fetch(
            "SELECT id, title, description, status FROM goals WHERE user_id=$1",
            user_id,
        )

    existing_list = [
        {
            "id": r["id"],
            "title": r["title"],
            "description": r["description"] or "",
            "status": r["status"] or "active",
        }
        for r in existing
    ]
    result = await generate_goals(notes_text, existing_goals=existing_list)
    if "error" in result:
        print(f"[goals] generate FAIL: {result['error']}", flush=True)
        return

    by_id = {r["id"]: r for r in existing}
    chosen_ids = set()

    async with pool.acquire() as db, db.transaction():
        added = 0
        for g in result["goals"]:
            evidence = []
            for e in g["evidence"]:
                nid = e.get("note_id")
                if isinstance(nid, str) and nid.isdigit():
                    nid = int(nid)
                if nid is None or nid not in date_map:
                    continue  # галлюцинированный note_id — не подтверждение
                evidence.append(
                    {
                        "note_id": nid,
                        "note_date": date_map.get(nid, ""),
                        "quote": e.get("quote", ""),
                    }
                )
            if len({q["note_id"] for q in evidence}) < 2:
                continue  # нет двух реальных подтверждений — мимо

            # существующая цель (активная или архивная) возвращается в фокус
            eid = g.get("existing_goal_id")
            if isinstance(eid, bool):
                eid = None
            if eid is not None and eid in by_id:
                if eid in chosen_ids:
                    continue  # дубликат в ответе AI — не затирать первый
                chosen_ids.add(eid)
                await db.execute(
                    """UPDATE goals
                       SET title=$1, description=$2, evidence=$3, thread_ids=$4,
                           categories=$5, source_count=$6, status='active',
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=$7 AND user_id=$8""",
                    g["title"],
                    g["description"],
                    json.dumps(evidence, ensure_ascii=False),
                    json.dumps(g["thread_ids"], ensure_ascii=False),
                    json.dumps(g["categories"], ensure_ascii=False),
                    len(evidence),
                    eid,
                    user_id,
                )
                continue

            inserted = await db.fetchrow(
                """INSERT INTO goals
                   (user_id, title, description, evidence, thread_ids, categories, source_count)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   RETURNING id""",
                user_id,
                g["title"],
                g["description"],
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(g["thread_ids"], ensure_ascii=False),
                json.dumps(g["categories"], ensure_ascii=False),
                len(evidence),
            )
            if inserted:
                chosen_ids.add(inserted["id"])
            added += 1

        # пересборка: активные, не выбранные AI и не закреплённые — в архив
        archived = 0
        if chosen_ids:
            active_rows = await db.fetch(
                "SELECT id FROM goals WHERE user_id=$1 AND status='active' AND is_pinned=0",
                user_id,
            )
            for r in active_rows:
                if r["id"] not in chosen_ids:
                    await db.execute(
                        "UPDATE goals SET status='archived' WHERE id=$1 AND user_id=$2",
                        r["id"],
                        user_id,
                    )
                    archived += 1
        print(
            f"[goals] rebuilt: chosen {len(chosen_ids)}, added {added}, "
            f"archived {archived}, total existing {len(existing)}",
            flush=True,
        )


@router.get("")
async def get_goals(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT * FROM goals WHERE user_id=$1
               ORDER BY is_pinned DESC, source_count DESC, updated_at DESC""",
            user_id,
        )
    active = []
    archived = []
    for r in rows:
        g = _row_to_goal(r)
        if g["status"] == "archived":
            archived.append(g)
        else:
            active.append(g)
    archived.sort(key=lambda g: g["updated_at"], reverse=True)
    return {"active": active, "archived": archived}


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


async def _set_status(goal_id: int, user_id: int, status: str):
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT id FROM goals WHERE id=$1 AND user_id=$2", goal_id, user_id
        )
        if not row:
            raise HTTPException(404, "цель не найдена")
        await db.execute(
            "UPDATE goals SET status=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2",
            status,
            goal_id,
        )
        return {"status": status}


@router.post("/{goal_id}/archive")
async def archive_goal(goal_id: int, user_id: int = Depends(get_current_user)):
    """«Убрать из зеркала»: цель покидает созвездие, но не теряется."""
    return await _set_status(goal_id, user_id, "archived")


@router.post("/{goal_id}/activate")
async def activate_goal(goal_id: int, user_id: int = Depends(get_current_user)):
    """Вернуть цель в созвездие вручную."""
    return await _set_status(goal_id, user_id, "active")


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
