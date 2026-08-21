import httpx

from backend.config import MEM_API_KEY

MEM_API_URL = "https://api.mem.ai"
TIMEOUT = httpx.Timeout(20.0)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {MEM_API_KEY}",
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    return bool(MEM_API_KEY)


async def mem_search(query: str, limit: int = 5) -> list[dict]:
    """Поиск заметок в Mem по смыслу. Возвращает id/title/snippet/дату."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{MEM_API_URL}/v2/notes/search?limit={limit}&offset=0",
            headers=_headers(),
            json={"query": query},
        )
    if resp.status_code == 401:
        raise RuntimeError("неверный или просроченный ключ Mem API")
    if resp.status_code != 200:
        raise RuntimeError(f"Mem API ответил {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    results = []
    for r in data.get("results", []):
        results.append(
            {
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "snippet": r.get("snippet", "") or r.get("content", "")[:300],
                "created_at": r.get("created_at", ""),
            }
        )
    return results


async def mem_list_all() -> list[dict]:
    """Все заметки Mem: id/title/created_at. Курсорная пагинация
    через GET /v2/notes с параметром page (next_page из ответа)."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        all_notes = []
        seen = set()
        page_token = None
        while True:
            resp = await client.get(
                f"{MEM_API_URL}/v2/notes?limit=100"
                + (f"&page={page_token}" if page_token else ""),
                headers=_headers(),
            )
            if resp.status_code == 401:
                raise RuntimeError("неверный или просроченный ключ Mem API")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Mem API ответил {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            results = data.get("results", [])
            for r in results:
                nid = r.get("id", "")
                if nid and nid not in seen:
                    seen.add(nid)
                    all_notes.append(
                        {
                            "id": nid,
                            "title": r.get("title", ""),
                            "created_at": r.get("created_at", ""),
                        }
                    )
            page_token = data.get("next_page")
            if not page_token or not results:
                break
    return all_notes


async def mem_read(note_id: str) -> dict:
    """Полное содержимое заметки Mem по id."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{MEM_API_URL}/v2/notes/{note_id}", headers=_headers())
    if resp.status_code == 401:
        raise RuntimeError("неверный или просроченный ключ Mem API")
    if resp.status_code != 200:
        raise RuntimeError(f"Mem API ответил {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return {
        "id": data.get("id", note_id),
        "title": data.get("title", ""),
        "content": data.get("content", ""),
        "created_at": data.get("created_at", ""),
    }


async def mem_create(content: str) -> dict:
    """Создать заметку в Mem. Первая строка markdown — заголовок."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{MEM_API_URL}/v2/notes",
            headers=_headers(),
            json={"content": content},
        )
    if resp.status_code == 401:
        raise RuntimeError("неверный или просроченный ключ Mem API")
    if resp.status_code != 201 and resp.status_code != 200:
        raise RuntimeError(f"Mem API ответил {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return {
        "id": data.get("id", ""),
        "title": data.get("title", ""),
        "content": data.get("content", ""),
    }
