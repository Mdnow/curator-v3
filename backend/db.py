import asyncpg
from contextlib import asynccontextmanager
from backend.config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


@asynccontextmanager
async def get_db():
    pool = await get_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content_encrypted TEXT NOT NULL,
                note_date TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                is_favorited INTEGER DEFAULT 0,
                ai_summary TEXT,
                ai_category TEXT,
                ai_sentiment REAL,
                ai_keyphrases TEXT DEFAULT '[]',
                thread_id TEXT,
                mood TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title_encrypted TEXT NOT NULL,
                description_encrypted TEXT,
                due_date TEXT,
                due_time TEXT,
                priority INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                is_favorited INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dreams (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content_encrypted TEXT NOT NULL,
                dream_type TEXT NOT NULL DEFAULT 'night',
                sleep_time TEXT,
                wake_time TEXT,
                sleep_quality INTEGER,
                emotion_label TEXT,
                emotion_valence REAL,
                ai_symbols TEXT DEFAULT '[]',
                ai_themes TEXT DEFAULT '[]',
                ai_summary TEXT,
                ai_question TEXT,
                linked_note_ids TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                session_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Embeddings for semantic search (pgvector)
        await db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS note_embeddings (
                note_id INTEGER PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                embedding vector(2048),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_note_embeddings_user ON note_embeddings(user_id)"
        )
        # Migrate existing v2 tables — add missing columns
        note_cols = await db.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='notes'"
        )
        note_col_names = {r["column_name"] for r in note_cols}
        for col, typ, default in [
            ("ai_sentiment", "REAL", "0.0"),
            ("ai_keyphrases", "TEXT", "'[]'"),
            ("thread_id", "TEXT", "NULL"),
            ("mood", "TEXT", "''"),
        ]:
            if col not in note_col_names:
                await db.execute(
                    f"ALTER TABLE notes ADD COLUMN {col} {typ} DEFAULT {default}"
                )

        # Dreams table — create if not exists (new in v3)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dreams (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content_encrypted TEXT NOT NULL,
                dream_type TEXT NOT NULL DEFAULT 'night',
                sleep_time TEXT,
                wake_time TEXT,
                sleep_quality INTEGER,
                emotion_label TEXT,
                emotion_valence REAL,
                ai_symbols TEXT DEFAULT '[]',
                ai_themes TEXT DEFAULT '[]',
                ai_summary TEXT,
                ai_question TEXT,
                linked_note_ids TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                evidence TEXT DEFAULT '[]',
                thread_ids TEXT DEFAULT '[]',
                categories TEXT DEFAULT '[]',
                source_count INTEGER NOT NULL DEFAULT 0,
                is_pinned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id, created_at)"
        )

        # Indexes — safe to create repeatedly
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_notes_user_date ON notes(user_id, note_date)"
        )
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_thread ON notes(user_id, thread_id)"
            )
        except Exception:
            pass  # column may not exist yet on old tables
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, due_date)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dreams_user_date ON dreams(user_id, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dreams_type ON dreams(user_id, dream_type)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_history(user_id, created_at)"
        )
