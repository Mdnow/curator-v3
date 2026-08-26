import json
import os
import re
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from backend.db import get_db
from backend.auth import get_current_user
from backend.crypto import encrypt, decrypt
from backend.models import ChatReq
from backend.ai import (
    AI_LAST_ERROR,
    chat_with_context,
    generate_thread_title,
    CHAT_SYSTEM,
)
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


_ASSIGN_RE = re.compile(r"\[ASSIGN:(\{.*?\})\]", re.DOTALL)


def _extract_note_refs(text: str) -> list[int]:
    """Уникальные id заметок из плейсхолдеров ⟦NOTE:id⟧ в ответе куратора."""
    ids = []
    for m in re.finditer(r"⟦NOTE:(\d+)⟧", text):
        try:
            ids.append(int(m.group(1)))
        except ValueError:
            continue
    return list(dict.fromkeys(ids))


# Куратор ссылается на заметки маркером [NOTE:id] (правило промпта), но
# free-модели иногда пишут и «(заметка [id=654])», «заметка id=654»,
# «(id=654)». Все формы сводим к единому плейсхолдеру ⟦NOTE:id⟧, который
# фронт превращает в ссылку-название с превью по наведению.
_NOTE_REF_REPLACERS = (
    (re.compile(r"\[NOTE:\s*(\d+)\]", re.IGNORECASE), r"⟦NOTE:\1⟧"),
    (re.compile(r"\[id=\s*(\d+)\]"), r"⟦NOTE:\1⟧"),
    (re.compile(r"\(id[=\s:]?\s*(\d+)\)"), r"⟦NOTE:\1⟧"),
    (re.compile(r"(заметк\w*)\s+id[=\s:]?\s*(\d+)", re.IGNORECASE), r"\1 ⟦NOTE:\2⟧"),
)


def _replace_note_refs(text: str) -> str:
    """Все формы ссылок на заметки -> единый плейсхолдер ⟦NOTE:id⟧."""
    for pat, repl in _NOTE_REF_REPLACERS:
        text = pat.sub(repl, text)
    return text


# Просьба разложить заметки по проектам (распределение).
# Проекты в интерфейсе исторически называются «папками» (ADR-0013),
# поэтому синонимы «папк...» обязательны.
_ASSIGN_INTENT_WORDS = (
    "разложи",
    "разложите",
    "разложить",
    "раскладывай",
    "раскладку",
    "распредели",
    "распределите",
    "распределить",
    "раскидай",
    "раскидать",
    "разнеси",
    "разнести",
    "разбей",
    "разбейте",
    "разбить",
    "сгруппируй",
    "сгруппируйте",
    "сгруппировать",
    "группируй",
    "сортируй",
    "сортируйте",
    "рассортируй",
    "привяжи к проекту",
    "привяжи к проектам",
    "привяжи к папке",
    "привяжи к папкам",
    "привяжите к проекту",
    "привяжите к проектам",
    "распределение по проектам",
    "распределение по папкам",
    "разложи по проектам",
    "разложи по папкам",
    "по папкам",
    "сортировать по проектам",
    "сортировать по папкам",
    "отсортируй по проектам",
    "отсортируй по папкам",
)

# «Как бы разложить», «можно ли», «что если» — вопрос, а не приказ.
_ASSIGN_NEGATIVE_MARKERS = (
    "как бы",
    "можно ли",
    "что если",
    "что, если",
    "как бы ты",
    "предложи",
)


def _has_assign_intent(message: str) -> bool:
    """Пользователь явно попросил разложить заметки по проектам."""
    low = message.lower()
    if any(m in low for m in _ASSIGN_NEGATIVE_MARKERS):
        return False
    return any(word in low for word in _ASSIGN_INTENT_WORDS)


async def _projects_context_block(db, user_id: int) -> str:
    """Список проектов для контекста куратора: «[id=5] Книга»."""
    rows = await db.fetch(
        "SELECT id, name FROM projects WHERE user_id=$1 ORDER BY updated_at DESC",
        user_id,
    )
    if not rows:
        return ""
    return "ПРОЕКТЫ (контейнеры заметок):\n" + "\n".join(
        f"- [id={r['id']}] {r['name']}" for r in rows
    )


async def _assign_pool_block(db, user_id: int) -> tuple[str, list[int]]:
    """Пакет последних незакреплённых заметок + их id.

    Заметка показывается кратко: заголовок/суммари/категория, если есть,
    иначе первые символы текста. Полный текст не льём — классификации
    достаточно, а токенов тратится меньше.
    """
    rows = await db.fetch(
        """SELECT id, note_date, content_encrypted, ai_title, ai_summary, ai_category
           FROM notes WHERE user_id=$1 AND project_id IS NULL
           ORDER BY created_at DESC LIMIT 30""",
        user_id,
    )
    if not rows:
        return "", []
    lines = []
    ids = []
    for r in rows:
        ids.append(r["id"])
        preview = ""
        try:
            content = decrypt(r["content_encrypted"]) or ""
        except Exception:
            content = ""
        if r["ai_summary"]:
            preview = r["ai_summary"][:180]
        elif r["ai_title"]:
            preview = r["ai_title"]
        else:
            preview = content[:180].replace("\n", " ")
        cat = (r["ai_category"] or "").strip()
        cat_part = f" | категория: {cat}" if cat and cat != "без категории" else ""
        lines.append(f"- [id={r['id']}] [{r['note_date']}] «{preview}»{cat_part}")
    block = (
        "РАСПРЕДЕЛЕНИЕ ПО ПРОЕКТАМ (по просьбе пользователя):\n"
        + "\n".join(lines)
        + "\n\nИнструкция: реши, какие заметки к каким проектам отнести. "
        "Привязывай ТОЛЬКО при явном совпадении темы. Если темы нет или "
        "подходящего проекта нет — заметку НЕ трогай, оставь как есть. "
        "Если несколько заметок образуют устойчивую тему без подходящего "
        "проекта — назови новый проект (1-3 слова). В конце ответа добавь "
        'маркер [ASSIGN:{"<id_заметки>": <id_проекта> | "<имя нового проекта>", ...}]: '
        "число = id существующего проекта из списка выше, строка = имя нового "
        "проекта. Используй ТОЛЬКО реальные id заметок и проектов. "
        "Не привязывай всё скопом — только то, в чём уверена."
    )
    return block, ids


def _parse_assign_plan(text: str) -> dict[int, int | str]:
    """План из маркера [ASSIGN:{"12": 5, "15": "Здоровье"}].

    Число — id существующего проекта, строка — имя нового. Возвращает
    пустой dict, если маркеров нет или JSON битый.
    """
    plan: dict[int, int | str] = {}
    for m in _ASSIGN_RE.finditer(text):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            try:
                note_id = int(k)
            except (TypeError, ValueError):
                continue
            if isinstance(v, int) and v > 0:
                plan[note_id] = v
            elif isinstance(v, str) and v.strip():
                plan[note_id] = v.strip()
    return plan


async def _apply_assign_plan(db, user_id: int, plan: dict[int, int | str]) -> dict:
    """Применить план: привязки к существующим/новым проектам. Сводка для UI."""
    summary: dict = {"assigned": [], "created_projects": []}
    for note_id, target in plan.items():
        note = await db.fetchrow(
            "SELECT id, project_id FROM notes WHERE id=$1 AND user_id=$2",
            note_id,
            user_id,
        )
        if not note:
            continue
        pid = None
        proj_name = ""
        new_project = False
        if isinstance(target, int):
            proj = await db.fetchrow(
                "SELECT id, name FROM projects WHERE id=$1 AND user_id=$2",
                target,
                user_id,
            )
            if proj:
                pid = proj["id"]
                proj_name = proj["name"]
        elif isinstance(target, str):
            proj_name = target
            proj = await db.fetchrow(
                "SELECT id FROM projects WHERE user_id=$1 AND LOWER(name)=LOWER($2)",
                user_id,
                proj_name,
            )
            if proj:
                pid = proj["id"]
            else:
                new = await db.fetchrow(
                    "INSERT INTO projects (user_id, name) VALUES ($1,$2) RETURNING id",
                    user_id,
                    proj_name,
                )
                pid = new["id"]
                new_project = True
        if pid is None:
            continue
        if note["project_id"] == pid:
            continue
        await db.execute(
            "UPDATE notes SET project_id=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2 AND user_id=$3",
            pid,
            note_id,
            user_id,
        )
        await db.execute(
            "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=$1", pid
        )
        if new_project and proj_name not in summary["created_projects"]:
            summary["created_projects"].append(proj_name)
        summary["assigned"].append(
            {
                "note_id": note_id,
                "project": proj_name,
                "new_project": new_project,
                # Прежний проект (или null) — для отката кнопкой в UI.
                "prev_project_id": note["project_id"],
            }
        )
    return summary


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
    text = (text or "").strip()
    if not text:
        return {"text": "", "note_id": 0, "ai": None}
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

    Вставка user-сообщения и ответ — в одной транзакции: при сбое AI
    откатывается всё, чтобы в истории не копились осиротевшие сообщения
    и фейковые ответы. Возвращает dict или бросает HTTPException(503).
    """
    async with db.transaction():
        return await _chat_reply_tx(
            db, user_id, thread_id, project_id, request_message, background, goal_id
        )


async def _chat_reply_tx(
    db,
    user_id: int,
    thread_id: int | None,
    project_id: int | None,
    request_message: str,
    background: BackgroundTasks,
    goal_id: int | None = None,
) -> dict:
    """Тело ответа куратора (вызывается внутри транзакции _chat_reply)."""
    if project_id is not None:
        owner = await db.fetchrow(
            "SELECT id FROM projects WHERE id=$1 AND user_id=$2",
            project_id,
            user_id,
        )
        if not owner:
            raise HTTPException(404, "проект не найден")
    elif thread_id is not None:
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

    if project_id is not None:
        await db.execute(
            """INSERT INTO chat_history (user_id, role, content, project_id)
               VALUES ($1,$2,$3,$4)""",
            user_id,
            "user",
            request_message,
            project_id,
        )
    else:
        await db.execute(
            """INSERT INTO chat_history (user_id, role, content, thread_id)
               VALUES ($1,$2,$3,$4)""",
            user_id,
            "user",
            request_message,
            thread_id,
        )
        background.add_task(_title_thread, thread_id, user_id, request_message)

    if project_id is not None:
        all_rows = await db.fetch(
            """SELECT role, content FROM chat_history
               WHERE user_id=$1 AND project_id=$2
               ORDER BY created_at DESC, id DESC LIMIT 40""",
            user_id,
            project_id,
        )
    else:
        all_rows = await db.fetch(
            """SELECT role, content FROM chat_history
               WHERE user_id=$1 AND thread_id=$2
               ORDER BY created_at DESC, id DESC LIMIT 40""",
            user_id,
            thread_id,
        )
    history = []
    for r in reversed(all_rows):
        history.append({"role": r["role"], "content": r["content"]})

    # Распределение по проектам (ADR-0017): определяем интент заранее,
    # чтобы при нём не тянуть полные тексты заметок в контекст (токены,
    # обрезка ответа free-модели). Для распределения хватает компактного
    # пула ниже.
    assign_intent = _has_assign_intent(request_message)

    # В контексте куратора — материалы проекта, если диалог внутри проекта.
    notes = []
    fav_notes = []
    cat_counts = {}
    dreams = []
    if not assign_intent:
        note_rows = await db.fetch(
            """SELECT id, content_encrypted, note_date, is_favorited, ai_summary,
                      ai_category
               FROM notes WHERE user_id=$1
               AND ($2::int IS NULL OR project_id=$2)
               ORDER BY created_at DESC LIMIT 30""",
            user_id,
            project_id,
        )
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

    if assign_intent:
        system = CHAT_SYSTEM + goal_context
    else:
        system = (
            CHAT_SYSTEM
            + ("\n".join(notes) if notes else "Заметок пока нет.")
            + pattern_block
            + fav_context
            + goal_context
        )

    # Проекты — контейнеры заметок: куратор видит их, чтобы советовать
    # и раскладывать заметки (ADR-0017).
    projects_block = await _projects_context_block(db, user_id)
    if projects_block:
        system += "\n\n" + projects_block

    # Распределение по проектам: пакет незакреплённых заметок + инструкция
    # с маркером [ASSIGN:...]. Применяется только при явной просьбе.
    assign_block = ""
    if assign_intent:
        assign_block, assign_pool_ids = await _assign_pool_block(db, user_id)
        if assign_block:
            system += "\n\n" + assign_block
        print(
            f"[assign] intent=True pool={len(assign_pool_ids)} pool_block={'yes' if assign_block else 'no'}",
            flush=True,
        )

    result = await chat_with_context(history, system=system)

    # AI недоступен: не пишем в историю ни user, ни assistant — транзакция
    # откатывается, клиент видит ошибку и может повторить без дубля.
    if not result:
        raise HTTPException(
            503,
            "AI временно недоступен"
            + (
                ": бесплатный лимит AI исчерпан на сегодня (сброс в 00:00 UTC)"
                if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower()
                else ". Попробуй через минуту"
            ),
        )

    # Ссылки на заметки: куратор помечает упоминания маркером [NOTE:id]
    # (или пишет «(заметка [id=N])»). Все формы сводим к плейсхолдеру
    # ⟦NOTE:id⟧ и по id подтягиваем данные заметок — фронт сделает их
    # ссылками-названиями с превью по наведению.
    result = _replace_note_refs(result)
    note_ref_ids = _extract_note_refs(result)
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

    # Распределение по проектам: маркер [ASSIGN:...] уважается только при
    # явной просьбе (защита от самовольного раскладывания, как у [SAVE:]).
    # Маркер вырезается в любом случае, чтобы не попасть в историю.
    assigned = None
    assign_plan = _parse_assign_plan(result)
    if assign_plan:
        result = _ASSIGN_RE.sub("", result).strip()
        if _has_assign_intent(request_message):
            assigned = await _apply_assign_plan(db, user_id, assign_plan)

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
        "assigned": assigned,
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
        # Вся логика (владелец ветки/проекта, вставка user, AI, вставка assistant,
        # транзакция на сбой) — в _chat_reply (ADR-0014, ADR-0016).
        return await _chat_reply(
            db,
            user_id,
            req.thread_id,
            req.project_id,
            req.message,
            background,
            req.goal_id,
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

    data = await file.read(MAX_FILE_SIZE + 1)
    if not data:
        raise HTTPException(400, "пустой файл")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "файл больше 5 МБ")

    if message and len(message) > 10000:
        raise HTTPException(422, "сообщение слишком длинное (макс. 10000)")

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

    user_text = f"файл: {file.filename}\n\n{content}"
    if message and message.strip():
        user_text += f"\n\n{message.strip()}"

    async with get_db() as db:
        return await _chat_reply(db, user_id, thread_id, None, user_text, background)


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
               ORDER BY created_at DESC, id DESC LIMIT $2 OFFSET $3""",
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
        # Удаляем только ветки чата; проектные диалоги (project_id) не трогаем.
        await db.execute(
            "DELETE FROM chat_history WHERE user_id=$1 AND project_id IS NULL",
            user_id,
        )
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
               ORDER BY created_at ASC, id ASC""",
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
               WHERE user_id=$1 AND content ILIKE $2 ESCAPE '\\'
               ORDER BY created_at DESC, id DESC LIMIT 50""",
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
