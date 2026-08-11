import asyncio
import asyncpg
from contextlib import asynccontextmanager
from backend.config import DATABASE_URL

_pool: asyncpg.Pool | None = None

# Разрывы/перезапуск соединения — на них можно безопасно повторить запрос
_RETRYABLE = (
    asyncpg.ConnectionDoesNotExistError,
    asyncpg.InterfaceError,
    ConnectionResetError,
    OSError,
)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            # Neon гасит compute после ~5 мин простоя и рвёт idle-коннекты.
            # Короткий lifetime заставляет пул сам отбрасывать протухшие.
            max_inactive_connection_lifetime=30.0,
        )
    return _pool


async def _healthy_connection() -> asyncpg.Connection:
    """Взять коннект из пула, проверить живость, при обрыве переподключиться."""
    pool = await get_pool()
    last_err: Exception | None = None
    for attempt in range(4):
        conn = await pool.acquire()
        try:
            await conn.fetchval("SELECT 1")
            return conn
        except _RETRYABLE as e:
            last_err = e
            await pool.release(conn)
            await asyncio.sleep(0.2 * (2**attempt))
    if last_err is not None:
        raise last_err
    raise RuntimeError("Не удалось получить живое соединение с БД")


@asynccontextmanager
async def get_db():
    conn = await _healthy_connection()
    try:
        yield conn
    finally:
        pool = await get_pool()
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
                ai_theses TEXT DEFAULT '[]',
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
            ("ai_theses", "TEXT", "'[]'"),
            ("thread_id", "TEXT", "NULL"),
            ("mood", "TEXT", "''"),
            ("ai_title", "TEXT", "NULL"),
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
        await db.execute(
            "ALTER TABLE goals ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS day_essences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                essence TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, date)
            )
        """)

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
