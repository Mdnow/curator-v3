import httpx
import time

BASE = "http://127.0.0.1:8765"

# Register
r = httpx.post(
    f"{BASE}/api/register",
    json={"username": "testfeat5", "password": "test123"},
    timeout=8,
)
token = r.json()["token"]
h = {"Authorization": f"Bearer {token}"}
print("=== Auth OK ===")

# === 1. THOUGHT THREADING ===
print("\n=== 1. THOUGHT THREADING ===")
for i, text in enumerate(
    [
        "Думаю о контроле. Почему так сильно хочется контролировать всё?",
        "Контроль - это страх. Страх что развалится если отпущу.",
        "Отпустила ситуацию на работе. Было страшно но интересно.",
    ]
):
    r = httpx.post(
        f"{BASE}/api/notes",
        json={"content": text, "note_date": "2026-07-22"},
        headers=h,
        timeout=8,
    )
    print(f"  Note {i + 1}: {r.status_code} {r.json()}")

print("  Waiting 5s for AI background analysis...")
time.sleep(5)

r = httpx.get(f"{BASE}/api/notes/threads", headers=h, timeout=8)
print(f"  GET /api/notes/threads: {r.status_code}")
threads = r.json()
print(f"  Found {len(threads)} threads")
for t in threads:
    print(
        f"    {t['thread_id'][:8]}... ({t['count']} notes) preview={t['preview'][:60]}"
    )

# Check notes have thread_id
r = httpx.get(f"{BASE}/api/notes?date=2026-07-22", headers=h, timeout=8)
notes = r.json()
for n in notes:
    print(
        f"  Note {n['id']}: thread_id={n.get('thread_id', '')!r} ai={n.get('ai_summary', '')[:40]!r}"
    )

# === 2. PROACTIVE INSIGHTS ===
print("\n=== 2. PROACTIVE INSIGHTS ===")
r = httpx.get(f"{BASE}/api/insights/daily", headers=h, timeout=15)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  Themes: {d.get('recurring_themes', [])}")
    print(f"  Emotional arc: {d.get('emotional_arc', '')[:80]}")
    print(f"  Insight: {d.get('key_insight', '')[:80]}")
    print(f"  Suggestion: {d.get('suggestion', '')[:80]}")
else:
    print(f"  Error: {r.text[:300]}")

# === 3. DREAM JOURNAL ===
print("\n=== 3. SLEEP/DREAM JOURNAL ===")

# Night dream
r = httpx.post(
    f"{BASE}/api/dreams",
    json={
        "content": "Сон: в доме который распадается но мне всё равно. Дети играют на обломках.",
        "dream_type": "night",
        "sleep_time": "23:30",
        "emotion_label": "спокойно",
    },
    headers=h,
    timeout=8,
)
print(f"  Night dream: {r.status_code} {r.json()}")

# Morning dream
r = httpx.post(
    f"{BASE}/api/dreams",
    json={
        "content": "Помню образ дома и странное чувство покоя. Как будто разрушение - это нормально.",
        "dream_type": "morning",
        "wake_time": "07:00",
        "sleep_quality": 4,
    },
    headers=h,
    timeout=8,
)
print(f"  Morning dream: {r.status_code} {r.json()}")

print("  Waiting 5s for AI analysis...")
time.sleep(5)

# Get dreams
r = httpx.get(f"{BASE}/api/dreams?days=7", headers=h, timeout=8)
print(f"  GET /api/dreams: {r.status_code}")
dreams = r.json()
print(f"  Found {len(dreams)} dreams")
for d in dreams:
    symbols = d.get("ai_symbols") or []
    valence = d.get("emotion_valence") or 0
    summary = d.get("ai_summary") or ""
    question = d.get("ai_question") or ""
    print(f"    [{d['dream_type']}] symbols={symbols} valence={valence:.1f}")
    if summary:
        print(f"      summary: {summary[:80]}")
    if question:
        print(f"      question: {question[:80]}")

# Dream insight
r = httpx.get(f"{BASE}/api/dreams/insight", headers=h, timeout=15)
print(f"\n  Dream insight: {r.status_code}")
if r.status_code == 200:
    print(f"  {r.json().get('insight', '')[:200]}")
else:
    print(f"  Error: {r.text[:300]}")

# Dream patterns
r = httpx.get(f"{BASE}/api/dreams/patterns?days=7", headers=h, timeout=15)
print(f"\n  Dream patterns: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  Themes: {d.get('recurring_themes', [])}")
    print(f"  Insight: {d.get('key_insight', '')[:80]}")
    print(f"  Suggestion: {d.get('suggestion', '')[:80]}")
else:
    print(f"  Error: {r.text[:300]}")

print("\n=== ALL TESTS DONE ===")
