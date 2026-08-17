import json
import os
import re
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import ChatReq
from backend.ai import chat_with_context, generate_thread_title, CHAT_SYSTEM
from datetime import datetime

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


async def _title_thread(thread_id: int, user_id: int, first_message: str):
    """Фоновый AI-заголовок ветки из первого сообщения (по смыслу, 2-5 слов)."""
    from backend.db import get_pool

    title = await generate_thread_title(first_message)
    if not title:
        return
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE chat_threads SET title=$1 WHERE id=$2 AND user_id=$3",
            title,
            thread_id,
            user_id,
        )


async def _chat_reply(
    db,
    user_id: int,
    thread_id: int | None,
    project_id: int | None,
    request_message: str,
    background: BackgroundTasks,
    goal_id: int | None = None,
) -> dict:
    """Общий путь ответа куратора (текст и файлы, ADR-0016).

    user-сообщение уже вставлено в историю вызывающей стороной; здесь:
    контекст (заметки/сны/цели) → AI → [NOTE] / [SAVE] → ответ в историю.
    """
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
               WHERE user_id=$1 AND thread_id=$2
               ORDER BY created_at DESC LIMIT 40""",
            user_id,
            thread_id,
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
    if goal_id is not None:
        goal_row = await db.fetchrow(
            "SELECT title, description, evidence, thread_ids FROM goals WHERE id=$1 AND user_id=$2",
            goal_id,
            user_id,
        )
        if goal_row:
            try:
                evidence = (
                    json.loads(goal_row["evidence"]) if goal_row["evidence"] else []
                )
                thread_ids = (
                    json.loads(goal_row["thread_ids"]) if goal_row["thread_ids"] else []
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
        if thought_text and _has_save_intent(request_message):
            saved = await _save_note(db, user_id, thought_text, background, project_id)

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
            """INSERT INTO chat_history (user_id, role, content, thread_id)
               VALUES ($1,$2,$3,$4)""",
            user_id,
            "assistant",
            result,
            thread_id,
        )
        await db.execute(
            "UPDATE chat_threads SET updated_at=CURRENT_TIMESTAMP WHERE id=$1",
            thread_id,
        )

    return {
        "reply": result,
        "auto_saved": [],
        "saved": saved,
        "note_refs": note_refs,
        "thread_id": thread_id,
        "session_id": thread_id,
        "project_id": project_id,
    }


@router.post("/ai/chat")
async def ai_chat(
    req: ChatReq, background: BackgroundTasks, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        # Диалог проекта остаётся в своём режиме (ADR-0014): постоянный фильтр по project_id.
        # Обычный чат — ветки (thread): новая при первом сообщении, продолжение по thread_id.
        project_id = None
        thread_id = None
        if req.project_id is not None:
            owner = await db.fetchrow(
                "SELECT id FROM projects WHERE id=$1 AND user_id=$2",
                req.project_id,
                user_id,
            )
            if not owner:
                raise HTTPException(404, "проект не найден")
            project_id = req.project_id
        elif req.thread_id is not None:
            owner = await db.fetchrow(
                "SELECT id FROM chat_threads WHERE id=$1 AND user_id=$2 LIMIT 1",
                req.thread_id,
                user_id,
            )
            if not owner:
                raise HTTPException(404, "ветка не найдена")
            thread_id = req.thread_id
        else:
            # Новая ветка: модель как в ChatGPT/Claude — каждое новое обращение
            # из «обсудить»/«новый диалог» создаёт отдельный разговор.
            row = await db.fetchrow(
                "INSERT INTO chat_threads (user_id) VALUES ($1) RETURNING id",
                user_id,
            )
            thread_id = row["id"]

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
                """INSERT INTO chat_history (user_id, role, content, thread_id)
                   VALUES ($1,$2,$3,$4)""",
                user_id,
                "user",
                req.message,
                thread_id,
            )
            background.add_task(_title_thread, thread_id, user_id, req.message)

        return await _chat_reply(
            db, user_id, thread_id, project_id, req.message, background, req.goal_id
        )


@router.post("/chat/upload")
async def chat_upload(
    file: UploadFile,
    background: BackgroundTasks,
    user_id: int = Depends(get_current_user),
    message: str = Form(""),
    thread_id: int | None = Form(None),
):
    """Загрузка файла в чат Куратора с осмыслением (ADR-0016).

    Извлечённый смысл файла вставляется в историю ветки как сообщение
    пользователя, далее обычный ответ куратора по контексту.
    """
    from backend.fileparse import (
        MAX_FILE_SIZE,
        MIME_BY_EXT,
        detect_kind,
        extract_text,
    )
    from backend.ai import describe_image
    import base64

    data = await file.read()
    if not data:
        raise HTTPException(400, "пустой файл")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "файл больше 5 МБ")

    kind = detect_kind(file.filename or "")
    if kind == "unsupported":
        raise HTTPException(
            415,
            "формат не поддерживается: отправь текст (.txt/.md/.csv/.json/.log), PDF или изображение",
        )

    if kind == "image":
        img_b64 = base64.b64encode(data).decode("ascii")
        mime = MIME_BY_EXT.get(
            os.path.splitext((file.filename or "").lower())[1], "image/png"
        )
        content = await describe_image(img_b64, mime)
        if not content:
            raise HTTPException(
                422, "не удалось распознать изображение (vision недоступен)"
            )
    else:
        try:
            content = extract_text(file.filename or "", data)
        except Exception as e:
            raise HTTPException(422, str(e))

    async with get_db() as db:
        if thread_id is not None:
            owner = await db.fetchrow(
                "SELECT id FROM chat_threads WHERE id=$1 AND user_id=$2 LIMIT 1",
                thread_id,
                user_id,
            )
            if not owner:
                raise HTTPException(404, "ветка не найдена")
        else:
            row = await db.fetchrow(
                "INSERT INTO chat_threads (user_id) VALUES ($1) RETURNING id",
                user_id,
            )
            thread_id = row["id"]

        user_text = f"файл: {file.filename}\n\n{content}"
        if message and message.strip():
            user_text += f"\n\n{message.strip()}"
        await db.execute(
            """INSERT INTO chat_history (user_id, role, content, thread_id)
               VALUES ($1,$2,$3,$4)""",
            user_id,
            "user",
            user_text,
            thread_id,
        )
        background.add_task(_title_thread, thread_id, user_id, user_text)

        return await _chat_reply(db, user_id, thread_id, None, message, background)


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
        await db.execute("DELETE FROM chat_threads WHERE user_id=$1", user_id)
        return {"ok": True}


@router.delete("/chat/threads/{thread_id}")
async def delete_thread(thread_id: int, user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM chat_threads WHERE id=$1 AND user_id=$2",
            thread_id,
            user_id,
        )
        return {"ok": True}


@router.get("/chat/threads")
async def chat_threads(user_id: int = Depends(get_current_user)):
    async with get_db() as db:
        rows = await db.fetch(
            """SELECT t.id, t.title, t.created_at as started,
                      MAX(h.created_at) as ended, COUNT(h.id) as msg_count,
                      MIN(h.created_at) as first_at
               FROM chat_threads t
               LEFT JOIN chat_history h ON h.thread_id=t.id
               WHERE t.user_id=$1
               GROUP BY t.id
               ORDER BY COALESCE(MAX(h.created_at), t.updated_at) DESC""",
            user_id,
        )
        threads = []
        for r in rows:
            title = (r["title"] or "").strip()
            preview = ""
            if not title:
                first = await db.fetchrow(
                    """SELECT content FROM chat_history
                       WHERE user_id=$1 AND thread_id=$2 AND role='user'
                       ORDER BY created_at ASC LIMIT 1""",
                    user_id,
                    r["id"],
                )
                preview = first["content"][:120] if first else ""
            threads.append(
                {
                    "thread_id": r["id"],
                    "title": title,
                    "started": r["started"] or r["first_at"],
                    "ended": r["ended"],
                    "msg_count": r["msg_count"] or 0,
                    "preview": preview,
                }
            )
        return threads


@router.get("/chat/threads/{thread_id}")
async def chat_thread_messages(
    thread_id: int, user_id: int = Depends(get_current_user)
):
    async with get_db() as db:
        owner = await db.fetchrow(
            "SELECT id FROM chat_threads WHERE id=$1 AND user_id=$2",
            thread_id,
            user_id,
        )
        if not owner:
            raise HTTPException(404, "ветка не найдена")
        rows = await db.fetch(
            """SELECT role, content, created_at
               FROM chat_history
               WHERE user_id=$1 AND thread_id=$2
               ORDER BY created_at ASC""",
            user_id,
            thread_id,
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
            """SELECT role, content, created_at, thread_id
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
                    "thread_id": r["thread_id"],
                }
            )
        return results
