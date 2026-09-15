import json

from backend.ai import (
    SKILL_CAPTION_PROMPT,
    SKILL_HOOKS_PROMPT,
    SKILL_REWRITE_PROMPT,
    SKILL_WHY_VIRAL_PROMPT,
    call_ai,
    call_ai_json,
)
from backend.db import get_db

SKILL_NAMES = {"hooks", "rewrite", "why_viral", "caption"}


async def _load_source(task_id: int, user_id: int) -> dict | None:
    """Горячий текст задачи из рабочей зоны (content_text)."""
    async with get_db() as db:
        row = await db.fetchrow(
            """SELECT content_text, title, author, description, ai_hook
               FROM tiktok_tasks WHERE id=$1 AND user_id=$2""",
            task_id,
            user_id,
        )
    if not row or not row["content_text"]:
        return None

    return {
        "translation": row["content_text"],
        "title": row["title"] or "",
        "author": row["author"] or "",
        "description": row["description"] or "",
        "hook": row["ai_hook"] or "",
    }


def _build_prompt(skill: str, src: dict) -> str:
    translation = (src["translation"] or "").strip()[:12000]
    if skill == "hooks":
        prompt = SKILL_HOOKS_PROMPT
        hook = (src["hook"] or "").strip()
        ideal = f"\nХУК ОРИГИНАЛА: {hook}" if hook else ""
        return prompt + ideal + "\n" + translation
    if skill == "rewrite":
        return SKILL_REWRITE_PROMPT + "\n" + translation
    if skill == "why_viral":
        return SKILL_WHY_VIRAL_PROMPT + "\n" + translation
    if skill == "caption":
        title = (src["title"] or src["description"] or src["hook"] or "видео")[:200]
        return SKILL_CAPTION_PROMPT.replace("__TITLE__", title) + "\n" + translation
    raise ValueError(skill)


async def run_skill(task_id: int, skill: str, user_id: int) -> dict:
    skill = skill.strip().lower()
    if skill not in SKILL_NAMES:
        return {"error": f"неизвестный скилл: {skill}"}

    src = await _load_source(task_id, user_id)
    if src is None:
        return {"error": "у задачи нет готовой заметки (перевода)"}

    prompt = _build_prompt(skill, src)

    if skill in ("hooks", "caption"):
        data = await call_ai_json(prompt, temperature=0.7, max_tokens=1200)
        if data is None:
            return {"error": "AI недоступен"}
        variants = data.get("variants", [])
        if not isinstance(variants, list):
            variants = []
        return {"skill": skill, "variants": variants}
    else:
        text = await call_ai(prompt, temperature=0.7, max_tokens=1500)
        if not text:
            return {"error": "AI недоступен"}
        return {"skill": skill, "text": text}
