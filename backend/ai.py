import httpx
import json
from backend.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    ZEN_API_KEY,
    ZEN_URL,
)

OPENROUTER_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
]

ZEN_MODELS = [
    "big-pickle",
    "deepseek-v4-flash-free",
    "nemotron-3-ultra-free",
    "mimo-v2.5-free",
    "longcat-2.0-free",
    "laguna-s-2.1-free",
    "ling-3.0-tiny-free",
    "north-mini-code-free",
]

EMBED_MODEL = "nvidia/nemotron-3-embed-1b:free"

PROVIDERS = []
if ZEN_API_KEY:
    PROVIDERS.append(
        {
            "name": "zen",
            "url": ZEN_URL,
            "key": ZEN_API_KEY,
            "models": ZEN_MODELS,
            "extra": {},
        }
    )
if OPENROUTER_API_KEY:
    PROVIDERS.append(
        {
            "name": "openrouter",
            "url": OPENROUTER_URL,
            "key": OPENROUTER_API_KEY,
            "models": OPENROUTER_MODELS,
            "extra": {"reasoning": {"exclude": True}},
        }
    )

ANALYZE_NOTE_PROMPT = """Ты — интуитивный куратор мыслей. Проанализируй текст и верни JSON:
{
  "summary": "одно предложение — суть заметки",
  "theses": ["2-4 чётких тезиса — конкретные мысли, которые несёт текст"],
  "category": "одно слово — тема (Мысли/Задачи/Идеи/Наблюдения/Вопросы/Планы/Цитаты/Отношения/Саморазвитие)",
  "sentiment": число от -1.0 (тёмное/тревожное) до 1.0 (светлое/спокойное),
  "keyphrases": ["до 3 ключевых фраз из текста"],
  "thread_hint": "одно предложение — о чём эта нить мыслей (или null если не применимо)"
}
Только JSON, без markdown, без комментариев.

Текст:
"""

ANALYZE_DREAM_PROMPT = """Ты — аналитик бессознательного. Анализируй записи о снах/сновидениях.

ВЕРНИ JSON:
{
  "symbols": ["до 3 ключевых образов/символов"],
  "themes": ["до 2 тем/паттернов"],
  "summary": "одно предложение — о чём сон",
  "valence": число от -1.0 (тёмный кошмар) до 1.0 (светлый сон),
  "question": "один сократический вопрос для размышления"
}

ПРАВИЛА:
- Не интерпретируй навязчиво. Предлагай, не утверждай.
- Если видишь повторяющийся символ — упомяни, но не навязывай "значение".
- Вопрос важнее ответа. Помогай думать, не решать.
- Говори на языке образов, а не психологии.
- Если запись пустая или фрагментарная — это ОК. Цени саму попытку.

Текст:
"""

DREAM_INSIGHT_PROMPT = """Ты — зеркало между сном и явью. Создай утренний инсайт.

ДАННЫЕ:
- Запись перед сном (вчера): {night}
- Запись после пробуждения (сегодня): {morning}
- Качество сна: {quality}/5
- Последние 7 дней (заметки и сны): {context}

ФОРМАТ (без JSON, просто текст):
🌙 → ☀️

[1-2 предложения связывающие сон и утро]

[Повторяющийся паттерн за неделю, если есть]

Вопрос: [один вопрос для размышления на день]

ПРАВИЛА:
- Будь образным, не клиническим.
- Не объясняй сны — помогай видеть связи.
- Максимум 5-6 строк. Лаконичность.
- Если недостаточно данных — скажи честно, но предположи."""

DAILY_PATTERNS_PROMPT = """Ты — аналитик паттернов сознания. Проанализируй данные за неделю.

ЗАМЕТКИ:
{notes}

СНЫ:
{dreams}

ВЕРНИ JSON:
{{
  "recurring_themes": ["до 3 повторяющихся тем"],
  "emotional_arc": "одно предложение — как менялось настроение за неделю",
  "key_insight": "одно предложение — главный инсайт недели",
  "suggestion": "одно предложение — что попробовать на следующей неделе"
}}
Только JSON, без markdown."""

THREAD_SUGGEST_PROMPT = """Ты — система навигации мыслей. Определи к какой нити мыслей относится эта заметка.

НОВАЯ ЗАМЕТКА:
{content}

СУЩЕСТВУЮЩИЕ НИТИ (thread_id → описание):
{threads}

ВЕРНИ JSON:
{{
  "thread_id": "UUID существующей нити или null если новая",
  "thread_name": "название нити (2-4 слова)",
  "confidence": число от 0.0 до 1.0
}}
Только JSON, без markdown."""

GOALS_PROMPT = """Ты — когнитивное зеркало. Проанализируй заметки за период и собери ТЕКУЩИЙ ФОКУС ВНИМАНИЯ: 3-5 ПРОЯВЛЕННЫХ ЦЕЛЕЙ — устойчивых направлений, к которым пользователь возвращается вновь и вновь.

Цель — НЕ задача и НЕ мечта. Цель = паттерн, подтверждённый цитатами. Вкладка показывает 3-5 живых направлений — созвездие, а не архив.

ГЛАВНОЕ — ОДНА ТЕМА = ОДНА ЦЕЛЬ, НЕ ДУБЛИРУЙ:
- Если фразы из разных заметок описывают одну и ту же тему разными словами («написать книгу», «работа над книгой», «главы про свободу») — это ОДНА цель. Собери все цитаты в её evidence, не дроби.
- Называй цель устойчивой именной формой (тема, а не случайный глагол из заметки): «Книга», а не «написать книгу» / «работа над книгой». Так цель остаётся узнаваемой при перегенерации.
- Выбирай ТОЛЬКО устойчивые направления: отбрасывай слабые паттерны с одним подтверждением.
- Упорядочь цели по силе: больше подтверждений в окне — выше в списке.

Сверься со списком СУЩЕСТВУЮЩИХ ЦЕЛЕЙ ниже. Если паттерн уже покрыт существующей целью (смысл совпадает, даже если слова другие) — НЕ создавай новую запись: укажи её id в "existing_goal_id" и собери свежие цитаты в evidence. Это касается и архивных целей (status: archived) — если вектор снова жив, верни их id, и они снова станут активными.

ВЕРНИ JSON:
{{
  "goals": [
    {{
      "title": "2-4 слова",
      "description": "одно предложение — куда ведёт вектор",
      "evidence": [{{"quote": "точная цитата из заметки", "note_id": 123}}],
      "thread_ids": ["uuid"],
      "categories": ["Саморазвитие"],
      "existing_goal_id": null
    }}
  ]
}}

ПРАВИЛА:
- 3-5 целей, не больше пяти.
- Каждая цель обязана иметь минимум 2 цитаты из РАЗНЫХ заметок.
- Цитата — дословно из текста, не пересказ.
- Не выдумывай цели, которых нет в данных.
- note_id бери ТОЛЬКО из предоставленного списка.
- existing_goal_id: id цели из СУЩЕСТВУЮЩИХ ЦЕЛЕЙ, если этот паттерн уже в ней (иначе null). Не выдумывай id.

СУЩЕСТВУЮЩИЕ ЦЕЛИ (JSON):
{existing}

ЗАМЕТКИ:
{notes}

Только JSON, без markdown."""

DAY_ESSENCE_PROMPT = """Ты — когнитивное зеркало. Посмотри заметки за один день и скажи в двух-трёх предложениях, в чём человек варился в этот день.

Говори только фактами из заметок: главные темы, повторяющиеся мысли, эмоциональный фон, что перетекало из других дней. Без оценок, без советов, без «ты».

ВЕРНИ JSON:
{{
  "essence": "2-3 предложения"
}}

ЗАМЕТКИ ДНЯ:
{notes}

Только JSON, без markdown."""


AI_LAST_ERROR = ""


def _parse_json_content(content: str | None) -> dict | None:
    if not content:
        return None
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _request_model(
    client: httpx.AsyncClient,
    provider: dict,
    model: str,
    msgs: list[dict],
    temperature: float,
    max_tokens: int,
) -> str | None:
    try:
        body = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body.update(provider["extra"])
        r = await client.post(
            provider["url"],
            headers={
                "Authorization": f"Bearer {provider['key']}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if r.status_code == 429:
            global AI_LAST_ERROR
            try:
                err = r.json().get("error", {}).get("message", "")
            except Exception:
                err = r.text[:300]
            if err:
                AI_LAST_ERROR = err
            print(f"[ai] {model} -> 429", flush=True)
            return None
        if r.status_code >= 400:
            err = ""
            try:
                err = r.json().get("error", {}).get("message", "")[:200]
            except Exception:
                err = r.text[:200]
            print(f"[ai] {model} -> {r.status_code}: {err}", flush=True)
            return None
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return content or None
    except Exception as e:
        print(f"[ai] {model} -> EXC {type(e).__name__}: {str(e)[:150]}", flush=True)
        return None


async def call_ai(
    user_content: str,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str | None:
    if not PROVIDERS:
        return None

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user_content})

    async with httpx.AsyncClient(timeout=90) as client:
        for _ in range(2):
            for provider in PROVIDERS:
                for model in provider["models"]:
                    content = await _request_model(
                        client, provider, model, msgs, temperature, max_tokens
                    )
                    if content:
                        return content
    return None


async def call_ai_json(
    user_content: str,
    temperature: float = 0.3,
    max_tokens: int = 1000,
) -> dict | None:
    if not PROVIDERS:
        return None

    msgs = [{"role": "user", "content": user_content}]

    async with httpx.AsyncClient(timeout=90) as client:
        for _ in range(2):
            for provider in PROVIDERS:
                for model in provider["models"]:
                    content = await _request_model(
                        client, provider, model, msgs, temperature, max_tokens
                    )
                    data = _parse_json_content(content)
                    if data is not None:
                        return data
    return None


async def analyze_note(text: str) -> dict:
    if not PROVIDERS:
        return {
            "summary": "",
            "theses": [],
            "category": "без категории",
            "sentiment": 0.0,
            "keyphrases": [],
            "thread_hint": None,
        }

    data = await call_ai_json(
        ANALYZE_NOTE_PROMPT + text, temperature=0.3, max_tokens=1000
    )
    if data is None:
        err = ""
        if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
            err = ": бесплатный лимит AI исчерпан на сегодня (сброс 00:00 UTC)"
        return {
            "summary": "",
            "theses": [],
            "category": "без категории",
            "sentiment": 0.0,
            "keyphrases": [],
            "thread_hint": None,
            "error": ("AI недоступен" + err),
        }

    return {
        "summary": data.get("summary", ""),
        "theses": data.get("theses", [])
        if isinstance(data.get("theses"), list)
        else [],
        "category": data.get("category", "без категории"),
        "sentiment": float(data.get("sentiment", 0.0) or 0.0),
        "keyphrases": data.get("keyphrases", []),
        "thread_hint": data.get("thread_hint"),
    }


async def analyze_dream(text: str) -> dict:
    if not PROVIDERS:
        return {
            "symbols": [],
            "themes": [],
            "summary": "",
            "valence": 0.0,
            "question": "",
        }

    data = await call_ai_json(
        ANALYZE_DREAM_PROMPT + text, temperature=0.5, max_tokens=1000
    )
    if data is None:
        return {
            "symbols": [],
            "themes": [],
            "summary": "",
            "valence": 0.0,
            "question": "",
            "error": "AI недоступен",
        }

    return {
        "symbols": data.get("symbols", []),
        "themes": data.get("themes", []),
        "summary": data.get("summary", ""),
        "valence": float(data.get("valence", 0.0) or 0.0),
        "question": data.get("question", ""),
    }


async def dream_insight(
    night_text: str, morning_text: str, quality: int | None, context: str
) -> str:
    if not PROVIDERS:
        return "AI временно недоступен."

    prompt = DREAM_INSIGHT_PROMPT.format(
        night=night_text or "(нет записи)",
        morning=morning_text or "(нет записи)",
        quality=quality or "?",
        context=context or "(нет данных)",
    )
    result = await call_ai(prompt, temperature=0.6, max_tokens=800)
    return result or "Не удалось сформировать инсайт."


async def daily_patterns(notes_text: str, dreams_text: str) -> dict:
    if not PROVIDERS:
        return {
            "recurring_themes": [],
            "emotional_arc": "",
            "key_insight": "",
            "suggestion": "",
        }

    prompt = DAILY_PATTERNS_PROMPT.format(notes=notes_text, dreams=dreams_text)
    data = await call_ai_json(prompt, temperature=0.4, max_tokens=1000)
    if data is None:
        return {
            "recurring_themes": [],
            "emotional_arc": "",
            "key_insight": "",
            "suggestion": "",
        }

    return {
        "recurring_themes": data.get("recurring_themes", []),
        "emotional_arc": data.get("emotional_arc", ""),
        "key_insight": data.get("key_insight", ""),
        "suggestion": data.get("suggestion", ""),
    }


async def thread_suggest(content: str, threads: str) -> dict:
    if not PROVIDERS:
        return {"thread_id": None, "thread_name": "", "confidence": 0.0}

    prompt = THREAD_SUGGEST_PROMPT.format(content=content, threads=threads)
    data = await call_ai_json(prompt, temperature=0.2, max_tokens=1000)
    if data is None:
        return {"thread_id": None, "thread_name": "", "confidence": 0.0}

    return {
        "thread_id": data.get("thread_id"),
        "thread_name": data.get("thread_name", ""),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
    }


async def generate_goals(
    notes_text: str, existing_goals: list[dict] | None = None
) -> dict:
    """Возвращает {"goals": [...]} или {"error": str} при сбое.

    existing_goals — список целей, уже лежащих в зеркале
    ([{"id": int, "title": str, "description": str}]): передаются в промпт,
    чтобы AI не плодил дубликаты и помечал их полем existing_goal_id.
    """
    if not PROVIDERS:
        return {"error": "API ключ не настроен."}

    existing_goals = [g for g in (existing_goals or []) if isinstance(g, dict)]
    existing_json = json.dumps(existing_goals, ensure_ascii=False)[:8000] or "[]"
    known_ids = {g["id"] for g in existing_goals if isinstance(g.get("id"), int)}
    prompt = GOALS_PROMPT.replace("{existing}", existing_json).replace(
        "{notes}", notes_text or "(нет заметок)"
    )
    data = await call_ai_json(prompt, temperature=0.3, max_tokens=2000)
    if data is None:
        err = ""
        if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
            err = ": бесплатный лимит AI исчерпан на сегодня (сброс 00:00 UTC)"
        return {"error": "AI недоступен" + err}

    goals = data.get("goals")
    if not isinstance(goals, list):
        return {"error": "AI не вернул цели."}

    clean = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        title = str(g.get("title", "")).strip()
        evidence = g.get("evidence")
        if not title or not isinstance(evidence, list) or len(evidence) < 2:
            continue
        quotes = []
        for e in evidence:
            if isinstance(e, dict) and e.get("quote") and e.get("note_id"):
                quotes.append(
                    {
                        "note_id": e["note_id"],
                        "quote": str(e["quote"]).strip(),
                    }
                )
        if len(quotes) < 2:
            continue
        # цитаты должны быть из разных заметок — иначе нет «проявленного вектора»
        if len({q["note_id"] for q in quotes}) < 2:
            continue
        eid = g.get("existing_goal_id")
        if isinstance(eid, bool):
            eid = None
        elif isinstance(eid, str) and eid.isdigit():
            eid = int(eid)
        existing_goal_id = eid if isinstance(eid, int) and eid in known_ids else None
        clean.append(
            {
                "title": title[:80],
                "description": str(g.get("description", "")).strip()[:300],
                "evidence": quotes,
                "thread_ids": g.get("thread_ids")
                if isinstance(g.get("thread_ids"), list)
                else [],
                "categories": g.get("categories")
                if isinstance(g.get("categories"), list)
                else [],
                "existing_goal_id": existing_goal_id,
            }
        )
    if not clean:
        return {"error": "AI вернул цели без цитат-источников."}
    return {"goals": clean}


async def day_essence(notes_text: str) -> dict:
    """Возвращает {"essence": str} или {"error": str} при сбое."""
    if not PROVIDERS:
        return {"error": "API ключ не настроен."}

    prompt = DAY_ESSENCE_PROMPT.format(notes=notes_text or "(нет заметок)")
    data = await call_ai_json(prompt, temperature=0.4, max_tokens=800)
    if data is None:
        err = ""
        if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
            err = ": бесплатный лимит AI исчерпан на сегодня (сброс 00:00 UTC)"
        return {"error": "AI недоступен" + err}

    essence = str(data.get("essence", "")).strip()
    if not essence:
        return {"error": "AI не вернул фразу."}
    return {"essence": essence[:500]}


CHAT_SYSTEM = """Ты — Куратор, AI-ассистент внутри приложения для заметок.

Твоя главная задача — помогать пользователю думать и структурировать мысли.

ПРАВИЛА:
1. Будь лаконичным, точным, без воды. Отвечай по-русски.
2. НИКОГДА не сохраняй мысли пользователя сам. Сохранение происходит ТОЛЬКО когда пользователь ЯВНО об этом просит (скажет «сохрани», «запиши», «это важно», «запомни», «save»). В этом случае ответь пользователю, что он может нажать кнопку сохранения.
3. НЕ используй никакие маркеры/скрытые команды в ответах. Отвечай обычным текстом.
4. Давай инсайты, связывай с прошлыми заметками, помогай видеть паттерны.
5. Если видишь связь с предыдущими заметками — упоминай это.
6. Задавай вопросы когда уместно — помогай углублять мысль.

Последние заметки пользователя для контекста:
"""


async def chat_with_context(messages: list[dict], system: str = "") -> str:
    if not PROVIDERS:
        return "API ключ не настроен."

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    async with httpx.AsyncClient(timeout=90) as client:
        for _ in range(2):
            for provider in PROVIDERS:
                for model in provider["models"]:
                    content = await _request_model(
                        client,
                        provider,
                        model,
                        msgs,
                        temperature=0.7,
                        max_tokens=2000,
                    )
                    if content:
                        return content

    if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
        return "Бесплатный лимит AI на сегодня исчерпан (сброс в 00:00 UTC)."
    return "AI временно недоступен. Попробуй через минуту."


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def embed_text(text: str) -> list[float] | None:
    """Вектор текста через бесплатную эмбеддинг-модель OpenRouter."""
    if not OPENROUTER_API_KEY or not text.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": EMBED_MODEL, "input": [text[:4000]]},
            )
            if r.status_code >= 400:
                print(f"[embed] -> {r.status_code}", flush=True)
                return None
            data = r.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        print(f"[embed] EXC {type(e).__name__}: {str(e)[:150]}", flush=True)
        return None
