from fastapi import APIRouter, HTTPException, Depends
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import TaskReq, TaskUpdateReq

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def get_tasks(date: str = "", user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        if date:
            rows = await db.fetch(
                """SELECT id, title_encrypted, description_encrypted, due_date,
                          due_time, priority, completed, is_favorited, created_at
                   FROM tasks WHERE user_id=$1 AND due_date=$2
                   ORDER BY is_favorited DESC, priority DESC, due_time ASC""",
                user_id,
                date,
            )
        else:
            rows = await db.fetch(
                """SELECT id, title_encrypted, description_encrypted, due_date,
                          due_time, priority, completed, is_favorited, created_at
                   FROM tasks WHERE user_id=$1 AND completed=0
                   ORDER BY is_favorited DESC, due_date ASC, priority DESC""",
                user_id,
            )
        tasks = []
        for r in rows:
            tasks.append(
                {
                    "id": r["id"],
                    "title": decrypt(r["title_encrypted"]),
                    "description": decrypt(r["description_encrypted"])
                    if r["description_encrypted"]
                    else "",
                    "due_date": r["due_date"],
                    "due_time": r["due_time"],
                    "priority": r["priority"],
                    "completed": r["completed"],
                    "is_favorited": r["is_favorited"],
                    "created_at": r["created_at"],
                }
            )
        return tasks


@router.post("")
async def create_task(req: TaskReq, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        t_enc = encrypt(req.title)
        d_enc = encrypt(req.description) if req.description else ""
        row = await db.fetchrow(
            """INSERT INTO tasks (user_id, title_encrypted, description_encrypted,
                                  due_date, due_time, priority)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            user_id,
            t_enc,
            d_enc,
            req.due_date,
            req.due_time,
            req.priority,
        )
        return {"id": row["id"]}


@router.put("/{task_id}")
async def update_task(
    task_id: int, req: TaskUpdateReq, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        existing = await db.fetchrow(
            "SELECT id FROM tasks WHERE id=$1 AND user_id=$2", task_id, user_id
        )
        if not existing:
            raise HTTPException(404)
        updates = []
        params = []
        idx = 1
        if req.title is not None:
            updates.append(f"title_encrypted=${idx}")
            params.append(encrypt(req.title))
            idx += 1
        if req.description is not None:
            updates.append(f"description_encrypted=${idx}")
            params.append(encrypt(req.description))
            idx += 1
        if req.due_date is not None:
            updates.append(f"due_date=${idx}")
            params.append(req.due_date)
            idx += 1
        if req.due_time is not None:
            updates.append(f"due_time=${idx}")
            params.append(req.due_time)
            idx += 1
        if req.priority is not None:
            updates.append(f"priority=${idx}")
            params.append(req.priority)
            idx += 1
        if req.completed is not None:
            updates.append(f"completed=${idx}")
            params.append(req.completed)
            idx += 1
        if not updates:
            return {"ok": True}
        params.extend([task_id, user_id])
        await db.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id=${idx} AND user_id=${idx + 1}",
            *params,
        )
        return {"ok": True}


@router.delete("/{task_id}")
async def delete_task(task_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, user_id
        )
        return {"ok": True}


@router.post("/{task_id}/favorite")
async def toggle_task_favorite(task_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        task = await db.fetchrow(
            "SELECT id, is_favorited FROM tasks WHERE id=$1 AND user_id=$2",
            task_id,
            user_id,
        )
        if not task:
            raise HTTPException(404)
        new_val = 0 if task["is_favorited"] else 1
        await db.execute(
            "UPDATE tasks SET is_favorited=$1 WHERE id=$2 AND user_id=$3",
            new_val,
            task_id,
            user_id,
        )
        return {"is_favorited": new_val}


@router.get("/upcoming")
async def upcoming_tasks(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT id, title_encrypted, due_date, due_time, priority, completed
               FROM tasks WHERE user_id=$1 AND completed=0 AND due_date != ''
               ORDER BY due_date ASC LIMIT 20""",
            user_id,
        )
        return [
            {
                "id": r["id"],
                "title": decrypt(r["title_encrypted"]),
                "due_date": r["due_date"],
                "due_time": r["due_time"],
                "priority": r["priority"],
                "completed": r["completed"],
            }
            for r in rows
        ]
