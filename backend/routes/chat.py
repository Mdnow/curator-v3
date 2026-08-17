import json
import re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import ChatReq
from backend.ai import chat_with_context, CHAT_SYSTEM
from datetime import datetime, timedelta

router = APIRouter(prefix="/api", tags=["chat"])

_SAVE_RE = re.compile(r"\[SAVE:(.+?)\]", re.DOTALL)

_SAVE_INTENT_WORDS = (
    "сохрани",
    "сохраните",
    "сохранить",
    "сохраню",
    "запиши",
    "запишите",
    "записать",
    "запишу",
    "запомни",
    "запомните",
    "запомнить",
    "занеси",
    "занесите",
    "занести",
    "сделай заметку",
    "сделайте заметку",
    "сделай запись",
    "сделайте запись",
    "в заметки",
    "в заметку",
    "save",
)

# Слова, которые НЕ являются просьбой, хотя и похожи на неё
# («надо запомнить» — оценка, а не приказ сохранить).
_SAVE_NEGATIVE_MARKERS = (
    "надо запомнить",
    "нужно запомнить",
    "стоит запомнить",
    "хочу запомнить",
)


def _has_save_intent(message: str) -> bool:
    """Пользователь явно попросил сохранить (глагол-просьба, а не «это важно»)."""
    low = message.lower()
    if any(m in low for m in _SAVE_NEGATIVE_MARKERS):
        return False
    return any(word in low for word in _SAVE_INTENT_WORDS)


def _extract_note_refs(text: str) -> list[int]:
    """Уникальные id заметок из маркеров [NOTE:id] в ответе куратора."""
    ids = []
    for m in re.finditer(r"\[NOTE:(\d+)\]", text, re.IGNORECASE):
        try:
            ids.append(int(m.group(1)))
        except ValueError:
            continue
    return list(dict.fromkeys(ids))


async def _save_note(
    db,
    user_id: int,
    text: str,
    background: BackgroundTasks | None = None,
    project_id: int | None = None,
) -> dict:
    """Сохранить текст как заметку «Цитаты».

    AI-разметку уводим в фон (как у обычных заметок): второй последовательный
    AI-вызов внутри запроса раздувал ответ за таймаут Render, и клиент видел
    «ошибку соединения». Фоновая задача пишет и ai_title.
    """
    today = datetime.now().date().isoformat()
    enc = encrypt(text)
    row = await db.fetchrow(
        """INSERT INTO notes (user_id, content_encrypted, note_date, tags, ai_category, project_id)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        user_id,
        enc,
        today,
        "[]",
        "Цитаты",
        project_id,
    )
    if background is not None:
        from backend.routes.notes import _analyze_in_background

        background.add_task(_analyze_in_background, row["id"], text, user_id)
        return {"text": text, "note_id": row["id"], "ai": None}

    from backend.ai import analyze_note

    ai = await analyze_note(text)
    if ai.get("summary") or ai.get("category"):
        await db.execute(
            "UPDATE notes SET ai_summary=$1, ai_category=$2 WHERE id=$3",
            ai.get("summary", ""),
            ai.get("category", "Цитаты"),
            row["id"],
        )
    return {"text": text, "note_id": row["id"], "ai": ai}


@router.post("/ai/chat")
async def ai_chat(
    req: ChatReq, background: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        # Диалог проекта: постоянный (без правила «2 часа»), фильтр по project_id.
        project_id = None
        session_id = None
        if req.project_id is not None:
            owner = await db.fetchrow(
                "SELECT id FROM projects WHERE id=$1 AND user_id=$2",
                req.project_id,
                user_id,
            )
            if not owner:
                raise HTTPException(404, "проект не найден")
            project_id = req.project_id
        elif req.session_id is not None:
            owner = await db.fetchrow(
                "SELECT id FROM chat_history WHERE user_id=$1 AND session_id=$2 LIMIT 1",
                user_id,
                req.session_id,
            )
            if not owner:
                raise HTTPException(404, "диалог не найден")
            session_id = req.session_id
        else:
            last_row = await db.fetchrow(
                """SELECT session_id, created_at FROM chat_history
                   WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1""",
                user_id,
            )
            session_id = 1
            if last_row:
                try:
                    last_time = last_row["created_at"]
                    if isinstance(last_time, str):
                        last_time = datetime.fromisoformat(last_time)
                    if (datetime.now() - last_time) > timedelta(hours=2):
                        session_id = (last_row["session_id"] or 0) + 1
                    else:
                        session_id = last_row["session_id"] or 1
                except Exception:
                    session_id = (last_row["session_id"] or 0) + 1

        if project_id is not None:
            await db.execute(
                """INSERT INTO chat_history (user_id, role, content, project_id)
                   VALUES ($1,$2,$3,$4)""",
                user_id,
                "user",
                req.message,
                project_id,
            )
        else:
            await db.execute(
                """INSERT INTO chat_history (user_id, role, content, session_id)
                   VALUES ($1,$2,$3,$4)""",
                user_id,
                "user",
                req.message,
                session_id,
            )

        if project_id is not None:
            all_rows = await db.fetch(
                """SELECT role, content FROM chat_history
                   WHERE user_id=$1 AND project_id=$2
                   ORDER BY created_at DESC LIMIT 40""",
                user_id,
                project_id,
            )
        else:
            all_rows = await db.fetch(
                """SELECT role, content FROM chat_history
                   WHERE user_id=$1 AND session_id=$2
                   ORDER BY created_at DESC LIMIT 40""",
                user_id,
                session_id,
            )
        history = []
        for r in reversed(all_rows):
            history.append({"role": r["role"], "content": r["content"]})

        # В контексте куратора — материалы проекта, если диалог внутри проекта.
        note_rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, is_favorited, ai_summary,
                      ai_category
               FROM notes WHERE user_id=$1
               AND ($2::int IS NULL OR project_id=$2)
               ORDER BY created_at DESC LIMIT 30""",
            user_id,
            project_id,
        )
        notes = []
        fav_notes = []
        cat_counts = {}
        for r in note_rows:
            try:
                text = decrypt(r["content_encrypted"])
                notes.append(f"[id={r['id']}] [{r['note_date']}] {text}")
                if r["is_favorited"]:
                    fav_notes.append(text)
                cat = (r["ai_category"] or "").strip()
                if cat and cat != "без категории":
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            except Exception:
                pass

        dream_rows = await db.fetch(
            """SELECT content_encrypted, created_at FROM dreams
               WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5""",
            user_id,
        )
        dreams = []
        for r in dream_rows:
            try:
                dreams.append(decrypt(r["content_encrypted"]))
            except Exception:
                pass

        pattern_block = ""
        if cat_counts:
            top = sorted(cat_counts.items(), key=lambda x: -x[1])[:4]
            pattern_block += "\n\nСВОДКА ТЕМ ЗА ПОСЛЕДНИЕ ЗАМЕТКИ:\n" + "\n".join(
                f"- {k}: {v}" for k, v in top
            )
        if dreams:
            pattern_block += "\n\nПОСЛЕДНИЕ ЗАПИСИ О СНАХ:\n" + "\n".join(
                f"- {d[:140]}" for d in dreams
            )

        fav_context = ""
        if fav_notes:
            fav_context = "\n\nИЗБРАННЫЕ МЫСЛИ (фокус, приоритет):\n" + "\n".join(
                f"- {t}" for t in fav_notes
            )

        goal_context = ""
        if req.goal_id is not None:
            goal_row = await db.fetchrow(
                "SELECT title, description, evidence, thread_ids FROM goals WHERE id=$1 AND user_id=$2",
                req.goal_id,
                user_id,
            )
            if goal_row:
                try:
                    evidence = (
                        json.loads(goal_row["evidence"]) if goal_row["evidence"] else []
                    )
                    thread_ids = (
                        json.loads(goal_row["thread_ids"])
                        if goal_row["thread_ids"]
                        else []
                    )
                except Exception:
                    evidence, thread_ids = [], []
                quotes = "\n".join(
                    f"- «{e.get('quote', '')}»" for e in evidence if e.get("quote")
                )
                goal_context = (
                    "\n\nЦЕЛЬ (направление пользователя, о котором он просит поговорить):\n"
                    f"Название: {goal_row['title']}\n"
                    f"Описание: {goal_row['description'] or ''}\n"
                )
                if quotes:
                    goal_context += "Подтверждения из заметок:\n" + quotes
                if thread_ids:
                    goal_context += "\nСвязанные темы: " + ", ".join(
                        str(t) for t in thread_ids
                    )

        system = (
            CHAT_SYSTEM
            + ("\n".join(notes) if notes else "Заметок пока нет.")
            + pattern_block
            + fav_context
            + goal_context
        )

        result = await chat_with_context(history, system=system)

        # Ссылки на заметки: куратор помечает упоминания маркером [NOTE:id].
        # Маркеры вырезаем из текста, по id подтягиваем данные заметок, чтобы
        # фронт сделал их кликабельными (пользователь читает полный текст).
        note_ref_ids = _extract_note_refs(result)
        result = re.sub(r"\[NOTE:\d+\]", "", result, flags=re.IGNORECASE).strip()
        note_refs = []
        if note_ref_ids:
            rows = await db.fetch(
                """SELECT id, note_date, content_encrypted, ai_title, ai_summary,
                          ai_category
                   FROM notes WHERE id = ANY($1::int[]) AND user_id=$2""",
                note_ref_ids,
                user_id,
            )
            for r in rows:
                try:
                    content = decrypt(r["content_encrypted"])
                except Exception:
                    content = ""
                note_refs.append(
                    {
                        "id": r["id"],
                        "note_date": r["note_date"] or "",
                        "content": content,
                        "ai_title": r["ai_title"] or "",
                        "ai_summary": r["ai_summary"] or "",
                        "ai_category": r["ai_category"] or "",
                    }
                )

        # Сохранение по явной просьбе пользователя: куратор добавляет в ответ
        # маркер [SAVE:текст], который превращается в заметку. Маркер из ответа
        # вырезается, чтобы пользователь его не видел и он не попал в историю.
        # Защита от самовольного сохранения: маркер уважается только если
        # пользователь явно просил сохранить. Иначе маркер вырезается, но
        # заметка не создаётся (free-модели иногда добавляют [SAVE:] сами).
        saved = None
        save_match = _SAVE_RE.search(result)
        if save_match:
            thought_text = save_match.group(1).strip()
            result = _SAVE_RE.sub("", result).strip()
            if thought_text and _has_save_intent(req.message):
                saved = await _save_note(
                    db, user_id, thought_text, background, project_id
                )

        if project_id is not None:
            await db.execute(
                """INSERT INTO chat_history (user_id, role, content, project_id)
                   VALUES ($1,$2,$3,$4)""",
                user_id,
                "assistant",
                result,
                project_id,
            )
            await db.execute(
                "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=$1",
                project_id,
            )
        else:
            await db.execute(
                """INSERT INTO chat_history (user_id, role, content, session_id)
                   VALUES ($1,$2,$3,$4)""",
                user_id,
                "assistant",
                result,
                session_id,
            )

        return {
            "reply": result,
            "auto_saved": [],
            "saved": saved,
            "note_refs": note_refs,
            "session_id": session_id,
            "project_id": project_id,
        }


@router.post("/ai/save-thought")
async def save_thought(
    req: ChatReq, background: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        saved = await _save_note(db, user_id, req.message, background)
        return {"id": saved["note_id"], "ai": saved["ai"]}


@router.get("/chat/history")
async def chat_history(
    page: int = 1, limit: int = 50, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        page = max(page, 1)
        limit = min(max(limit, 1), 100)
        offset = (page - 1) * limit
        rows = await db.fetch(
            """SELECT role, content, created_at
               FROM chat_history WHERE user_id=$1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user_id,
            limit,
            offset,
        )
        return [
            {"role": r["role"], "content": r["content"], "time": r["created_at"]}
            for r in reversed(list(rows))
        ]


@router.delete("/chat/history")
async def clear_chat(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await db.execute("DELETE FROM chat_history WHERE user_id=$1", user_id)
        return {"ok": True}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        if session_id == 0:
            await db.execute(
                "DELETE FROM chat_history WHERE user_id=$1 AND session_id IS NULL",
                user_id,
            )
        else:
            await db.execute(
                "DELETE FROM chat_history WHERE user_id=$1 AND session_id=$2",
                user_id,
                session_id,
            )
        return {"ok": True}


@router.get("/chat/sessions")
async def chat_sessions(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT session_id, MIN(created_at) as started,
                      MAX(created_at) as ended, COUNT(*) as msg_count
               FROM chat_history
               WHERE user_id=$1 AND session_id IS NOT NULL
               GROUP BY session_id ORDER BY started DESC""",
            user_id,
        )
        sessions = []
        for r in rows:
            first = await db.fetchrow(
                """SELECT content FROM chat_history
                   WHERE user_id=$1 AND session_id=$2 AND role='user'
                   ORDER BY created_at ASC LIMIT 1""",
                user_id,
                r["session_id"],
            )
            preview = first["content"][:120] if first else ""
            sessions.append(
                {
                    "session_id": r["session_id"],
                    "started": r["started"],
                    "ended": r["ended"],
                    "msg_count": r["msg_count"],
                    "preview": preview,
                }
            )

        unassigned = await db.fetchrow(
            """SELECT COUNT(*) as cnt FROM chat_history
               WHERE user_id=$1 AND session_id IS NULL""",
            user_id,
        )
        if unassigned and unassigned["cnt"] > 0:
            sessions.insert(
                0,
                {
                    "session_id": 0,
                    "started": None,
                    "ended": None,
                    "msg_count": unassigned["cnt"],
                    "preview": "старые сообщения",
                },
            )

        return sessions


@router.get("/chat/sessions/{session_id}")
async def chat_session_messages(
    session_id: int, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        if session_id == 0:
            rows = await db.fetch(
                """SELECT role, content, created_at
                   FROM chat_history WHERE user_id=$1 AND session_id IS NULL
                   ORDER BY created_at ASC""",
                user_id,
            )
        else:
            rows = await db.fetch(
                """SELECT role, content, created_at
                   FROM chat_history WHERE user_id=$1 AND session_id=$2
                   ORDER BY created_at ASC""",
                user_id,
                session_id,
            )
        return [
            {"role": r["role"], "content": r["content"], "time": r["created_at"]}
            for r in rows
        ]


@router.get("/chat/search")
async def chat_search(q: str = "", user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        if not q.strip():
            return []
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = await db.fetch(
            """SELECT role, content, created_at, session_id
               FROM chat_history
               WHERE user_id=$1 AND content LIKE $2 ESCAPE '\\'
               ORDER BY created_at DESC LIMIT 50""",
            user_id,
            pattern,
        )
        results = []
        for r in rows:
            text = r["content"]
            idx = text.lower().find(q.lower())
            start = max(0, idx - 40)
            end = min(len(text), idx + len(q) + 40)
            snippet = (
                ("..." if start > 0 else "")
                + text[start:end]
                + ("..." if end < len(text) else "")
            )
            results.append(
                {
                    "role": r["role"],
                    "snippet": snippet,
                    "full": text,
                    "time": r["created_at"],
                    "session_id": r["session_id"],
                }
            )
        return results
