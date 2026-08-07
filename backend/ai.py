import httpx
import json
from backend.config import OPENROUTER_API_KEY, OPENROUTER_URL

FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
]

ANALYZE_NOTE_PROMPT = """Ты — интуитивный куратор мыслей. Проанализируй текст и верни JSON:
{
  "summary": "одно предложение — суть заметки",
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
    model: str,
    msgs: list[dict],
    temperature: float,
    max_tokens: int,
) -> str | None:
    try:
        r = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": msgs,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "reasoning": {"exclude": True},
            },
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
    if not OPENROUTER_API_KEY:
        return None

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user_content})

    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(2):
            for model in FREE_MODELS:
                content = await _request_model(
                    client, model, msgs, temperature, max_tokens
                )
                if content:
                    return content
    return None


async def call_ai_json(
    user_content: str,
    temperature: float = 0.3,
    max_tokens: int = 500,
) -> dict | None:
    if not OPENROUTER_API_KEY:
        return None

    msgs = [{"role": "user", "content": user_content}]

    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(2):
            for model in FREE_MODELS:
                content = await _request_model(
                    client, model, msgs, temperature, max_tokens
                )
                data = _parse_json_content(content)
                if data is not None:
                    return data
    return None


async def analyze_note(text: str) -> dict:
    if not OPENROUTER_API_KEY:
        return {
            "summary": "",
            "category": "без категории",
            "sentiment": 0.0,
            "keyphrases": [],
            "thread_hint": None,
        }

    data = await call_ai_json(
        ANALYZE_NOTE_PROMPT + text, temperature=0.3, max_tokens=500
    )
    if data is None:
        err = ""
        if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
            err = ": бесплатный лимит на сегодня исчерпан (50 запросов/день, сброс 00:00 UTC). Добавь $10 на openrouter.ai, чтобы получить 1000 запросов/день"
        return {
            "summary": "",
            "category": "без категории",
            "sentiment": 0.0,
            "keyphrases": [],
            "thread_hint": None,
            "error": ("AI недоступен" + err),
        }

    return {
        "summary": data.get("summary", ""),
        "category": data.get("category", "без категории"),
        "sentiment": float(data.get("sentiment", 0.0) or 0.0),
        "keyphrases": data.get("keyphrases", []),
        "thread_hint": data.get("thread_hint"),
    }


async def analyze_dream(text: str) -> dict:
    if not OPENROUTER_API_KEY:
        return {
            "symbols": [],
            "themes": [],
            "summary": "",
            "valence": 0.0,
            "question": "",
        }

    data = await call_ai_json(
        ANALYZE_DREAM_PROMPT + text, temperature=0.5, max_tokens=500
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
    if not OPENROUTER_API_KEY:
        return "AI временно недоступен."

    prompt = DREAM_INSIGHT_PROMPT.format(
        night=night_text or "(нет записи)",
        morning=morning_text or "(нет записи)",
        quality=quality or "?",
        context=context or "(нет данных)",
    )
    result = await call_ai(prompt, temperature=0.6, max_tokens=300)
    return result or "Не удалось сформировать инсайт."


async def daily_patterns(notes_text: str, dreams_text: str) -> dict:
    if not OPENROUTER_API_KEY:
        return {
            "recurring_themes": [],
            "emotional_arc": "",
            "key_insight": "",
            "suggestion": "",
        }

    prompt = DAILY_PATTERNS_PROMPT.format(notes=notes_text, dreams=dreams_text)
    data = await call_ai_json(prompt, temperature=0.4, max_tokens=500)
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
    if not OPENROUTER_API_KEY:
        return {"thread_id": None, "thread_name": "", "confidence": 0.0}

    prompt = THREAD_SUGGEST_PROMPT.format(content=content, threads=threads)
    data = await call_ai_json(prompt, temperature=0.2, max_tokens=200)
    if data is None:
        return {"thread_id": None, "thread_name": "", "confidence": 0.0}

    return {
        "thread_id": data.get("thread_id"),
        "thread_name": data.get("thread_name", ""),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
    }


CHAT_SYSTEM = """Ты — Куратор, AI-ассистент внутри приложения для заметок.

Твоя главная задача — помогать пользователю думать и структурировать мысли.

ПРАВИЛА:
1. Будь лаконичным, точным, без воды. Отвечай по-русски.
2. Если пользователь ЯВНО просит сохранить мысль/цитату ("сохрани", "запиши", "это важно", "запомни", "save") — ТЫ ОБЯЗАН сохранить её.
   Используй маркер: [AUTO_SAVE:точный текст который нужно сохранить]
   После этого кратко подтверди что сохранил.
3. Если пользователь сказал что-то глубокое, важное, ценное — но НЕ просил сохранить — предложи:
   [AUTO_SAVE:точный текст]
4. НЕ предлагай сохранять приветствия, вопросы пользователя, технические инструкции.
5. Давай инсайты, связывай с прошлыми заметками, помогай видеть паттерны.
6. Если видишь связь с предыдущими заметками — упоминай это.
7. Задавай вопросы когда уместно — помогай углублять мысль.

Последние заметки пользователя для контекста:
"""


async def chat_with_context(messages: list[dict], system: str = "") -> str:
    if not OPENROUTER_API_KEY:
        return "API ключ не настроен."

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(2):
            for model in FREE_MODELS:
                content = await _request_model(
                    client, model, msgs, temperature=0.7, max_tokens=2000
                )
                if content:
                    return content

    if AI_LAST_ERROR and "rate limit" in AI_LAST_ERROR.lower():
        return "Бесплатный лимит OpenRouter на сегодня исчерпан (50 запросов/день, сброс в 00:00 UTC). Добавь $10 на openrouter.ai, чтобы получить 1000 запросов в день."
    return "AI временно недоступен. Попробуй через минуту."
