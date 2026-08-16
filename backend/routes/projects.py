from fastapi import APIRouter, HTTPException, Depends
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import decrypt
from backend.models import ProjectReq, ProjectUpdateReq
import json

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _get_project(db, project_id: int, user_id: int):
    row = await db.fetchrow(
        "SELECT id, name, created_at, updated_at FROM projects WHERE id=$1 AND user_id=$2",
        project_id,
        user_id,
    )
    if not row:
        raise HTTPException(404, "проект не найден")
    return row


@router.get("")
async def list_projects(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT p.id, p.name, p.created_at, p.updated_at,
                      (SELECT COUNT(*) FROM notes n WHERE n.user_id=$1 AND n.project_id=p.id) AS note_count,
                      (SELECT COUNT(*) FROM chat_history c WHERE c.user_id=$1 AND c.project_id=p.id) AS msg_count
               FROM projects p WHERE p.user_id=$1
               ORDER BY p.updated_at DESC""",
            user_id,
        )
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "created_at": str(r["created_at"]) if r["created_at"] else "",
                "updated_at": str(r["updated_at"]) if r["updated_at"] else "",
                "note_count": r["note_count"],
                "msg_count": r["msg_count"],
            }
            for r in rows
        ]


@router.post("")
async def create_project(req: ProjectReq, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        row = await db.fetchrow(
            "INSERT INTO projects (user_id, name) VALUES ($1,$2) RETURNING id, name, created_at",
            user_id,
            req.name,
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": str(row["created_at"]) if row["created_at"] else "",
            "updated_at": str(row["created_at"]) if row["created_at"] else "",
            "note_count": 0,
            "msg_count": 0,
        }


@router.get("/{project_id}")
async def get_project(project_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        project = await _get_project(db, project_id, user_id)

        note_rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, is_favorited, ai_title,
                      ai_summary, ai_category, ai_sentiment, ai_theses, mood, created_at
               FROM notes WHERE user_id=$1 AND project_id=$2
               ORDER BY created_at DESC""",
            user_id,
            project_id,
        )
        notes = []
        for r in note_rows:
            try:
                content = decrypt(r["content_encrypted"])
            except Exception:
                content = ""
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
                    "is_favorited": r["is_favorited"],
                    "ai_title": r["ai_title"] or "",
                    "ai_summary": r["ai_summary"] or "",
                    "ai_category": r["ai_category"] or "",
                    "ai_sentiment": float(r["ai_sentiment"])
                    if r["ai_sentiment"]
                    else 0.0,
                    "ai_theses": theses,
                    "mood": r["mood"] or "",
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                }
            )

        msg_rows = await db.fetch(
            """SELECT role, content, created_at FROM chat_history
               WHERE user_id=$1 AND project_id=$2 ORDER BY created_at ASC""",
            user_id,
            project_id,
        )
        messages = [
            {
                "role": r["role"],
                "content": r["content"],
                "time": str(r["created_at"]) if r["created_at"] else "",
            }
            for r in msg_rows
        ]

        return {
            "id": project["id"],
            "name": project["name"],
            "created_at": str(project["created_at"]) if project["created_at"] else "",
            "updated_at": str(project["updated_at"]) if project["updated_at"] else "",
            "notes": notes,
            "messages": messages,
        }


@router.put("/{project_id}")
async def rename_project(
    project_id: int, req: ProjectUpdateReq, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        await _get_project(db, project_id, user_id)
        if req.name is None:
            return {"ok": True}
        await db.execute(
            "UPDATE projects SET name=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2 AND user_id=$3",
            req.name,
            project_id,
            user_id,
        )
        return {"ok": True}


@router.delete("/{project_id}")
async def delete_project(project_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await _get_project(db, project_id, user_id)
        # Заметки проекта не удаляются: снимаем привязку (ON DELETE SET NULL).
        await db.execute(
            "UPDATE notes SET project_id=NULL WHERE user_id=$1 AND project_id=$2",
            user_id,
            project_id,
        )
        # Диалог проекта удаляется вместе с проектом (ON DELETE CASCADE).
        await db.execute(
            "DELETE FROM projects WHERE id=$1 AND user_id=$2", project_id, user_id
        )
        return {"ok": True}
