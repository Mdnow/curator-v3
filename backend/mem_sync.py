"""Синк корпуса заметок (Obsidian) + локальный поиск по нему (ADR-0019).

Источник — локальный Obsidian-хранилище пользователя (файлы .md). Модель
эмбеддинга — локальная (fastembed, multilingual), не зависит от VPN/OpenRouter
(OpenRouter с российского VPN отвечает 403). Пишет в те же таблицы, что и
модуль mem_sync (mem_notes + mem_note_embeddings, dim 768).
"""

import asyncio
import os
import re
from datetime import datetime, timezone

from backend.crypto import encrypt, decrypt
from backend.db import get_pool

EMBED_MODEL_NAME = os.getenv(
    "MEM_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
)

_embedder = None


def _get_embedder():
    """Ленивая инициализация локальной эмбеддинг-модели (fastembed)."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=EMBED_MODEL_NAME)
    return _embedder


def _norm(vec) -> list[float] | None:
    """L2-нормализация (вектор → единичная длина). Без неё L2-расстояния
    в pgvector смещены: у модели mpnet норма ~2.0, а порог подразумевает 0..2."""
    try:
        n = sum(float(x) * float(x) for x in vec) ** 0.5
        if n == 0:
            return None
        return [float(x) / n for x in vec]
    except Exception:
        return None


async def embed_local(text: str) -> list[float] | None:
    """Вектор текста локальной моделью (dim 768, L2-нормализованный)."""
    try:
        vecs = list(_get_embedder().embed([text[:4000]]))
        return _norm(vecs[0])
    except Exception as e:
        print(f"[mem_local] embed EXC {type(e).__name__}: {str(e)[:150]}", flush=True)
        return None


STATE = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "skipped": 0,
    "started_at": "",
    "finished_at": "",
    "last_error": "",
}


def sync_status() -> dict:
    return dict(STATE)


async def _embed_with_retry(content: str, retries: int = 2) -> list[float] | None:
    for attempt in range(retries):
        vec = await embed_local(content)
        if vec:
            return vec
        if attempt < retries - 1:
            await asyncio.sleep(2 * (attempt + 1))
    return None


# -------------------- синк из Obsidian --------------------

OBSIDIAN_ROOT = os.getenv(
    "OBSIDIAN_ROOT",
    r"C:\Users\danil\OneDrive\Рабочий стол\Проекты\Obsidian\Dnlchk",
)
EXCLUDE_DIRS = {".obsidian", ".git", "_АРХИВ", "_архив", "AppleNotes"}

_DATE_RE = re.compile(
    r"(?P<d>\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+(?P<y>\d{4})"
)
_ISO_DATE_RE = re.compile(r"(?P<y>\d{4})[-._](?P<m>\d{2})[-._](?P<d>\d{2})")
_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _parse_frontmatter(text: str):
    if text.startswith("---"):
        m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
        if m:
            fm = m.group(1)
            title_m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", fm, re.MULTILINE)
            title = title_m.group(1).strip() if title_m else None
            return title, text[m.end() :]
    return None, text


def _date_from_name(name: str, mtime: float, content: str = "") -> str:
    """Дата заметки: из имени файла (рус./ISO) → из контента → mtime.
    mtime — худший случай (дата копирования файла, не написания)."""
    m = _DATE_RE.search(name)
    if m:
        return (
            f"{int(m.group('y')):04d}-{_MONTHS[m.group(2)]:02d}-{int(m.group('d')):02d}"
        )
    m = _ISO_DATE_RE.search(name)
    if m:
        return f"{m.group('y')}-{m.group('m')}-{m.group('d')}"
    m = _DATE_RE.search(content[:1500])
    if m:
        return (
            f"{int(m.group('y')):04d}-{_MONTHS[m.group(2)]:02d}-{int(m.group('d')):02d}"
        )
    m = _ISO_DATE_RE.search(content[:1500])
    if m:
        return f"{m.group('y')}-{m.group('m')}-{m.group('d')}"
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def _clean_content(text: str) -> str:
    text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[>*`_~]", "", text)
    return text.strip()


def collect_obsidian_files(root: str) -> list[dict]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                stat = os.stat(path)
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
            except Exception:
                continue
            title_fm, body = _parse_frontmatter(raw)
            name = os.path.splitext(fn)[0]
            title = title_fm or name
            content = _clean_content(body)
            if not content:
                continue
            files.append(
                {
                    "path": path,
                    "name": name,
                    "title": title[:500],
                    "content": content,
                    "date": _date_from_name(name, stat.st_mtime, content),
                }
            )
    return files


async def _embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Батч-эмбеддинг. Батч 20 (на Windows ONNX не тянет 50 — bad allocation);
    тексты обрезаем до 4000 символов (как в embed_local); при сбое батча —
    ретрай одиночными вызовами."""
    try:
        emb = _get_embedder()
        out = []
        for i in range(0, len(texts), 20):
            chunk = [t[:4000] for t in texts[i : i + 20]]
            try:
                vecs = list(emb.embed(chunk, batch_size=len(chunk)))
                out.extend([_norm(v) for v in vecs])
            except Exception:
                # fallback: по одному
                for t in chunk:
                    try:
                        v = list(emb.embed([t], batch_size=1))[0]
                        out.append(_norm(v))
                    except Exception:
                        out.append(None)
        return out
    except Exception as e:
        print(f"[mem_local] batch EXC {type(e).__name__}: {str(e)[:150]}", flush=True)
        return [None] * len(texts)


async def _insert_batch(
    pool_ref: list, batch: list[dict], vecs: list[list[float] | None]
):
    """Пакетная вставка заметок Obsidian. Без эмбеддинга НЕ вставляем.
    pool_ref — mutable [pool], чтобы обновить пул при обрыве.
    content_plaintext заполняется для tsvector-поиска на проде."""
    for idx, f in enumerate(batch):
        vec = vecs[idx]
        if not vec:
            STATE["failed"] += 1
            continue
        for attempt in range(3):
            try:
                pool = pool_ref[0]
                async with pool.acquire() as db:
                    row = await db.fetchrow(
                        """INSERT INTO mem_notes
                               (mem_id, title, content_encrypted, content_plaintext,
                                created_at)
                           VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                        f"obsidian:{f['path']}",
                        f["title"],
                        encrypt(f["content"]),
                        f["content"][:10000],
                        f["date"],
                    )
                    local_id = row["id"]
                    await db.execute(
                        """INSERT INTO mem_note_embeddings (note_id, embedding)
                           VALUES ($1,$2)""",
                        local_id,
                        str(vec),
                    )
                break
            except Exception as e:
                STATE["last_error"] = f"insert {f['name'][:40]}: {e}"
                print(
                    f"[mem_sync] INSERT FAIL (attempt {attempt + 1}) {f['name'][:50]}: {type(e).__name__}: {e}",
                    flush=True,
                )
                if attempt < 2:
                    try:
                        old = pool_ref[0]
                        await old.close()
                    except Exception:
                        pass
                    pool_ref[0] = await get_pool(force=True)
                    await asyncio.sleep(1)
                else:
                    STATE["failed"] += 1


async def run_obsidian_sync() -> dict:
    """Полный синк Obsidian → mem_notes. Запускать фоново (долгий процесс).
    Запись инкрементальная — по батчам по 50 файлов, прогресс виден в БД."""
    if STATE["running"]:
        return {"error": "синк уже идёт"}
    if not os.path.isdir(OBSIDIAN_ROOT):
        return {"error": f"папка Obsidian не найдена: {OBSIDIAN_ROOT}"}

    STATE.update(
        running=True,
        total=0,
        done=0,
        failed=0,
        skipped=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at="",
        last_error="",
    )
    try:
        pool = await get_pool()
        pool_ref = [pool]
        files = collect_obsidian_files(OBSIDIAN_ROOT)
        STATE["total"] = len(files)

        existing = set()
        async with pool.acquire() as db:
            rows = await db.fetch("SELECT mem_id FROM mem_notes")
            existing = {r["mem_id"] for r in rows}

        to_insert = []
        for f in files:
            mem_id = f"obsidian:{f['path']}"
            if mem_id in existing:
                STATE["skipped"] += 1
                STATE["done"] += 1
            else:
                to_insert.append(f)

        print(
            f"[obsidian_sync] новых: {len(to_insert)}, уже есть: {STATE['skipped']}",
            flush=True,
        )
        for i in range(0, len(to_insert), 50):
            batch = to_insert[i : i + 50]
            vecs = await _embed_batch([f["content"] for f in batch])
            await _insert_batch(pool_ref, batch, vecs)
            STATE["done"] += len(batch)
            if STATE["done"] % 100 == 0 or i + 50 >= len(to_insert):
                print(
                    f"[obsidian_sync] {STATE['done']}/{STATE['total']} "
                    f"(fail {STATE['failed']}, skip {STATE['skipped']})",
                    flush=True,
                )

        STATE["running"] = False
        STATE["finished_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "total": STATE["total"],
            "done": STATE["done"],
            "failed": STATE["failed"],
            "skipped": STATE["skipped"],
        }
    except Exception as e:
        STATE["running"] = False
        STATE["finished_at"] = datetime.now(timezone.utc).isoformat()
        STATE["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return {"error": STATE["last_error"]}


# -------------------- поиск по синкнутой базе --------------------


async def mem_search_local(query: str, limit: int = 8) -> list[dict]:
    """Поиск по синкнутой базе (Obsidian) — локально, по смыслу."""
    vec = await embed_local(query)
    if not vec:
        return []
    try:
        pool = await get_pool()
    except Exception:
        return []
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT n.id, n.mem_id, n.title, n.content_encrypted, n.created_at,
                      ne.embedding <-> $1 AS dist
               FROM mem_note_embeddings ne
               JOIN mem_notes n ON n.id = ne.note_id
               ORDER BY dist ASC
               LIMIT $2""",
            str(vec),
            limit,
        )
    results = []
    for r in rows:
        try:
            content = decrypt(r["content_encrypted"])
        except Exception:
            content = ""
        results.append(
            {
                "id": r["mem_id"],
                "title": r["title"],
                "snippet": content[:300],
                "created_at": r["created_at"],
                "date": (r["created_at"] or "")[:10],
                "dist": r["dist"],
            }
        )
    return results


# -------------------- полнотекстовый поиск (tsvector) --------------------


async def mem_text_search(query: str, limit: int = 8) -> list[dict]:
    """Поиск по ключевым словам через PostgreSQL tsvector.
    Работает на проде без AI-моделей — бесплатно, быстро, в 512 MB."""
    try:
        pool = await get_pool()
    except Exception:
        return []
    try:
        async with pool.acquire() as db:
            rows = await db.fetch(
                """SELECT n.id, n.mem_id, n.title, n.content_plaintext,
                          n.created_at,
                          ts_rank(n.tsvect_search,
                            plainto_tsquery('russian', $1)) AS rank
                   FROM mem_notes n
                   WHERE n.tsvect_search @@ plainto_tsquery('russian', $1)
                   ORDER BY rank DESC
                   LIMIT $2""",
                query,
                limit,
            )
    except Exception as e:
        print(f"[mem_text_search] ERROR: {type(e).__name__}: {e}", flush=True)
        return []
    results = []
    for r in rows:
        results.append(
            {
                "id": r["mem_id"],
                "title": r["title"],
                "snippet": (r["content_plaintext"] or "")[:300],
                "created_at": r["created_at"],
                "date": (r["created_at"] or "")[:10],
                "rank": float(r["rank"]),
            }
        )
    return results
