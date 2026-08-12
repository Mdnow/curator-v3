import asyncio
import json
import os
import re
import subprocess

import httpx

from backend.config import GROQ_API_KEY, OPENROUTER_API_KEY, TMP_DIR
from backend.crypto import encrypt
from backend.db import get_db, get_pool

# --- скачивание (из tiktok-watcher, ADR-0008/0009) ---

TIKTOK_EXTRACTOR_ARGS = "tiktok:api_hostname=tiktokv.com"


class DownloadError(Exception):
    pass


def extract_video_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url)
    if m:
        return m.group(1)
    return ""


def _extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


async def fetch_tikwm(url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://www.tikwm.com/api/",
            params={"url": url, "hd": "1"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code >= 400:
            raise DownloadError(f"tikwm HTTP {r.status_code}")
        data = r.json()
    if data.get("code") != 0:
        raise DownloadError(f"tikwm error: {data.get('msg', 'unknown')}")
    d = data.get("data", {})
    if not d:
        raise DownloadError("tikwm: пустой ответ")
    video_url = d.get("play") or d.get("wmplay")
    if not video_url:
        raise DownloadError("tikwm: нет ссылки на видео")
    return {
        "video_url": video_url,
        "id": str(d.get("id", "")),
        "author": (d.get("author") or {}).get("unique_id", "") or d.get("nickname", ""),
        "description": d.get("title") or d.get("desc") or "",
        "duration": d.get("duration"),
        "hashtags": [],
    }


async def _ytdlp_json(url: str) -> dict | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--dump-single-json",
            "--extractor-args",
            TIKTOK_EXTRACTOR_ARGS,
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "--no-progress",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
        if not out:
            return None
        return json.loads(out.decode("utf-8", errors="replace"))
    except Exception:
        return None


async def fetch_ytdlp_meta(url: str) -> dict:
    info = await _ytdlp_json(url)
    if not info:
        raise DownloadError("yt-dlp: нет метаданных")
    description = info.get("description") or ""
    return {
        "video_url": None,
        "id": str(info.get("id") or extract_video_id(url)),
        "author": info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or "",
        "description": description,
        "duration": info.get("duration"),
        "hashtags": _extract_hashtags(description),
    }


async def _download_ytdlp(url: str, dest: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-f",
            "mp4/best",
            "--extractor-args",
            TIKTOK_EXTRACTOR_ARGS,
            "--no-playlist",
            "-o",
            dest,
            "--no-warnings",
            "--quiet",
            "--no-progress",
            url,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        return os.path.exists(dest) and os.path.getsize(dest) > 0
    except Exception:
        return False


async def download_video(url: str, task_id: int) -> dict:
    os.makedirs(TMP_DIR, exist_ok=True)
    try:
        meta = await fetch_tikwm(url)
    except DownloadError:
        meta = None

    if meta is not None:
        dest = os.path.join(TMP_DIR, f"{task_id}_{meta['id'] or 'video'}.mp4")
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                r = await client.get(
                    meta["video_url"],
                    headers={"Referer": "https://www.tiktok.com/"},
                )
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(dest, "wb") as f:
                        f.write(r.content)
        except Exception:
            pass
        if not (os.path.exists(dest) and os.path.getsize(dest) > 1000):
            ok = await _download_ytdlp(meta["video_url"], dest)
            if not ok:
                ok = await _download_ytdlp(url, dest)
            if not ok:
                return {**meta, "video_path": None}
    else:
        meta = await fetch_ytdlp_meta(url)
        dest = os.path.join(TMP_DIR, f"{task_id}_{meta['id'] or 'video'}.mp4")
        ok = await _download_ytdlp(url, dest)
        if not ok:
            return {**meta, "video_path": None}

    meta["hashtags"] = _extract_hashtags(meta["description"])
    meta["video_path"] = dest if os.path.exists(dest) else None
    return meta


# --- транскрипция (ffmpeg + Groq Whisper) ---

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3-turbo"


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode == 0, (proc.stderr or "")[-500:]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def extract_audio(video_path: str, out: str) -> tuple[str | None, str]:
    ok, err = _run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", out]
    )
    if ok and os.path.exists(out) and os.path.getsize(out) > 0:
        return out, ""
    return None, err or "ffmpeg: звук не извлечён"


async def transcribe_audio(audio_path: str) -> tuple[str, str]:
    if not GROQ_API_KEY:
        return "", "нет GROQ_API_KEY"
    try:
        with open(audio_path, "rb") as f:
            content = f.read()
    except Exception as e:
        return "", f"не прочитан wav: {type(e).__name__}: {str(e)[:100]}"
    if len(content) > 25 * 1024 * 1024:
        return "", "wav больше лимита Groq (25MB)"
    last_err = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("audio.wav", content, "audio/wav")},
                    data={"model": WHISPER_MODEL, "response_format": "json"},
                )
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"Groq HTTP {r.status_code}"
                print(
                    f"[tiktok] groq {r.status_code}, retry {attempt + 1}",
                    flush=True,
                )
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 400:
                print(
                    f"[tiktok] groq -> {r.status_code}: {r.text[:200]}",
                    flush=True,
                )
                return "", f"Groq HTTP {r.status_code}: {r.text[:150]}"
            text = (r.json().get("text") or "").strip()
            if text:
                return text, ""
            return "", "нет речи"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"[tiktok] groq EXC {last_err}", flush=True)
            await asyncio.sleep(2 * (attempt + 1))
    return "", last_err or "Groq не ответил"


async def transcribe_video(video_path: str | None, task_id: int) -> tuple[str, str]:
    if not video_path or not os.path.exists(video_path):
        return "", "видео не скачано"
    out = os.path.join(TMP_DIR, f"audio_{task_id}.wav")
    audio, reason = await asyncio.to_thread(extract_audio, video_path, out)
    if not audio:
        return "", f"извлечь звук не удалось: {reason}"
    return await transcribe_audio(audio)


# --- перевод (Groq LLM, OpenRouter — fallback) ---

GROQ_LLM_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_LLM_MODEL = "llama-3.3-70b-versatile"
TRANSLATE_MAX_TOKENS = 6000

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODELS = [
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
]

TRANSLATE_PROMPT = """Ты — переводчик. Переведи транскрипт речи на русский язык.

ПРАВИЛА:
- Дословный полный перевод всего текста, без пропусков и сокращений.
- Сохрани смысл, интонацию и структуру высказывания.
- Не добавляй свои комментарии, не пересказывай, не редактируй.
- Не заворачивай ответ в markdown и кавычки — только текст перевода.
- Если в тексте есть имена, бренды, термины — оставляй их как есть.
- Только перевод, ничего больше."""


async def _call(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    model: str,
    msgs: list[dict],
    extra: dict | None = None,
) -> str | None:
    try:
        body = {
            "model": model,
            "messages": msgs,
            "temperature": 0.4,
            "max_tokens": TRANSLATE_MAX_TOKENS,
        }
        if extra:
            body.update(extra)
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if r.status_code >= 400:
            print(f"[tiktok] {model} -> {r.status_code}", flush=True)
            return None
        return r.json()["choices"][0]["message"]["content"] or None
    except Exception as e:
        print(f"[tiktok] EXC {type(e).__name__}: {str(e)[:150]}", flush=True)
        return None


async def translate_transcript(audio_text: str) -> str:
    text = (audio_text or "").strip()
    if not text:
        return ""
    msgs = [
        {"role": "system", "content": TRANSLATE_PROMPT},
        {"role": "user", "content": text[:12000]},
    ]
    async with httpx.AsyncClient(timeout=120) as client:
        if GROQ_API_KEY:
            content = await _call(
                client, GROQ_LLM_URL, GROQ_API_KEY, GROQ_LLM_MODEL, msgs
            )
            if content:
                return content.strip()
            print("[tiktok] groq llm failed, fallback to openrouter", flush=True)
        if OPENROUTER_API_KEY:
            for _ in range(2):
                for model in FREE_MODELS:
                    content = await _call(
                        client,
                        OPENROUTER_URL,
                        OPENROUTER_API_KEY,
                        model,
                        msgs,
                        {"reasoning": {"exclude": True}},
                    )
                    if content:
                        return content.strip()
    return ""


# --- фоновый воркер ---

MAX_CONTENT_LEN = 20000


def _title_for_note(meta: dict, translation: str) -> str:
    desc = (meta.get("description") or "").strip()
    if desc:
        return desc[:120]
    first_line = (translation or "").strip().split("\n")[0].strip()
    return first_line[:120]


async def _embed_in_background(note_id: int, content: str, user_id: int):
    from backend.ai import embed_text

    vec = await embed_text(content)
    if not vec:
        return
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO note_embeddings (note_id, user_id, embedding)
               VALUES ($1,$2,$3) ON CONFLICT (note_id) DO UPDATE SET embedding=$3""",
            note_id,
            user_id,
            str(vec),
        )


async def _set_status(task_id: int, **fields):
    async with get_db() as db:
        await db.execute(
            f"UPDATE tiktok_tasks SET {', '.join(f'{k}=${i}' for i, k in enumerate(fields, start=1))} WHERE id=${len(fields) + 1}",
            *list(fields.values()),
            task_id,
        )


async def process_task(task_id: int, user_id: int) -> None:
    async with get_db() as db:
        row = await db.fetchrow(
            "SELECT url, note_date FROM tiktok_tasks WHERE id=$1 AND user_id=$2",
            task_id,
            user_id,
        )
    if not row:
        return
    url, note_date = row["url"], row["note_date"]

    try:
        await _set_status(task_id, status="downloading")
        meta = await download_video(url, task_id)
        await _set_status(task_id, author=meta.get("author", ""))

        await _set_status(task_id, status="transcribing")
        audio_text = ""
        reason = ""
        if meta.get("video_path"):
            audio_text, reason = await transcribe_video(meta["video_path"], task_id)
            if audio_text:
                await _set_status(task_id, status="translating")
                translation = await translate_transcript(audio_text)
            else:
                translation = ""
        else:
            translation = ""
            reason = "видео не скачано"

        note_error = ""
        if translation:
            content = translation
        elif reason == "нет речи":
            content = "В видео не распознана речь (только музыка или шумы)."
        else:
            note_error = f"Расшифровка не удалась: {reason or 'неизвестно'}"
            content = (
                "Речи в видео не было (расшифровка не удалась: "
                + (reason or "неизвестно")
                + ")."
            )
        content = content[:MAX_CONTENT_LEN]

        await _set_status(task_id, status="saving", error=note_error)
        title = _title_for_note(meta, translation)
        async with get_db() as db:
            note_row = await db.fetchrow(
                """INSERT INTO notes (user_id, content_encrypted, note_date, tags, ai_title)
                   VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                user_id,
                encrypt(content),
                note_date,
                json.dumps(["tiktok"]),
                title,
            )
            note_id = note_row["id"]

        asyncio.get_running_loop().create_task(
            _embed_in_background(note_id, content, user_id)
        )

        await _set_status(task_id, status="done", note_id=note_id, title=title)
    except Exception as e:
        print(
            f"[tiktok] task {task_id} EXC {type(e).__name__}: {str(e)[:200]}",
            flush=True,
        )
        await _set_status(task_id, status="error", error=str(e)[:500])
