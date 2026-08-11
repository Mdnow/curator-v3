import asyncio
import time
from httpx import AsyncClient, ASGITransport
from backend.main import app


async def test():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=15
    ) as client:
        # Register/login
        r = await client.post(
            "/api/register", json={"username": "test_feat", "password": "test123"}
        )
        if r.status_code != 200:
            r = await client.post(
                "/api/login", json={"username": "test_feat", "password": "test123"}
            )
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        print("Auth: OK")

        # === 1. THOUGHT THREADING ===
        print("\n=== 1. THOUGHT THREADING ===")
        for i, text in enumerate(
            [
                "Думаю о контроле. Почему так сильно хочется контролировать всё?",
                "Контроль - это страх. Страх что развалится если отпущу.",
                "Отпустила ситуацию на работе. Было страшно но интересно.",
            ]
        ):
            r = await client.post(
                "/api/notes",
                json={"content": text, "note_date": "2026-07-22"},
                headers=h,
            )
            print(f"  Note {i + 1}: {r.status_code}")
            if r.status_code != 200:
                print(f"    Error: {r.text[:200]}")

        print("  Waiting 5s for AI background analysis...")
        time.sleep(5)

        r = await client.get("/api/notes/threads", headers=h)
        print(f"  Threads: {r.status_code}")
        if r.status_code == 200:
            threads = r.json()
            print(f"  Found {len(threads)} threads")
            for t in threads:
                print(f"    thread {t['thread_id'][:8]}... ({t['count']} notes)")
        else:
            print(f"    Error: {r.text[:200]}")

        # Check if notes got thread_id
        r = await client.get("/api/notes?days=1", headers=h)
        if r.status_code == 200:
            notes = r.json()
            for n in notes:
                tid = n.get("thread_id")
                print(f"  Note {n['id']}: thread_id={tid}")

        # === 2. PROACTIVE INSIGHTS ===
        print("\n=== 2. PROACTIVE INSIGHTS ===")
        r = await client.get("/api/insights/daily", headers=h)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  Themes: {d.get('recurring_themes', [])}")
            print(f"  Insight: {d.get('key_insight', '')[:80]}")
            print(f"  Suggestion: {d.get('suggestion', '')[:80]}")
        else:
            print(f"  Error: {r.text[:200]}")

        # === 3. DREAM JOURNAL ===
        print("\n=== 3. SLEEP/DREAM JOURNAL ===")
        r = await client.post(
            "/api/dreams",
            json={
                "content": "Сон: в доме который распадается но мне всё равно",
                "dream_type": "night",
                "sleep_time": "23:30",
                "emotion_label": "спокойно",
            },
            headers=h,
        )
        print(f"  Night dream: {r.status_code} id={r.json().get('id')}")
        if r.status_code != 200:
            print(f"    Error: {r.text[:200]}")

        r = await client.post(
            "/api/dreams",
            json={
                "content": "Помню образ дома и странное чувство покоя",
                "dream_type": "morning",
                "wake_time": "07:00",
                "sleep_quality": 4,
            },
            headers=h,
        )
        print(f"  Morning dream: {r.status_code} id={r.json().get('id')}")
        if r.status_code != 200:
            print(f"    Error: {r.text[:200]}")

        print("  Waiting 5s for AI analysis...")
        time.sleep(5)

        r = await client.get("/api/dreams?days=7", headers=h)
        print(f"  GET dreams: {r.status_code}")
        if r.status_code == 200:
            dreams = r.json()
            print(f"  Found {len(dreams)} dreams")
            for d in dreams:
                symbols = d.get("ai_symbols") or []
                valence = d.get("emotion_valence") or 0
                summary = d.get("ai_summary") or ""
                print(
                    f"    [{d['dream_type']}] symbols={symbols} valence={valence:.1f}"
                )
                if summary:
                    print(f"    summary: {summary[:60]}")
        else:
            print(f"    Error: {r.text[:200]}")

        r = await client.get("/api/dreams/insight", headers=h)
        print(f"  Dream insight: {r.status_code}")
        if r.status_code == 200:
            print(f"  Text: {r.json().get('insight', '')[:120]}")
        else:
            print(f"    Error: {r.text[:200]}")

        r = await client.get("/api/dreams/patterns?days=7", headers=h)
        print(f"  Dream patterns: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  Themes: {d.get('recurring_themes', [])}")
            print(f"  Insight: {d.get('key_insight', '')[:80]}")
        else:
            print(f"    Error: {r.text[:200]}")

        print("\n=== DONE ===")


asyncio.run(test())
