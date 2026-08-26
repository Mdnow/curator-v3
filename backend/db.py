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


async def get_pool(force: bool = False) -> asyncpg.Pool:
    global _pool
    if _pool is not None and not force:
        return _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
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
        # Ветки чата (ADR-0014): диалог = тема с названием, сообщения привязаны
        # через thread_id. Проектные диалоги остаются в своём режиме (project_id).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS thread_id INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_thread ON chat_history(user_id, thread_id, created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_user ON chat_threads(user_id, updated_at)"
        )
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
        # Синк-копия базы Mem AI (ADR-0019): полный корпус заметок с эмбеддингами.
        # Куратор ищет по ним локально (без VPN и лимитов search-API Mem).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mem_notes (
                id SERIAL PRIMARY KEY,
                mem_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                content_encrypted TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mem_note_embeddings (
                note_id INTEGER PRIMARY KEY REFERENCES mem_notes(id) ON DELETE CASCADE,
                embedding vector(768),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_notes_created ON mem_notes(created_at)"
        )
        # tsvector для полнотекстового поиска по заметкам (ADR-0019).
        # Работает на проде без AI-моделей — PostgreSQL ищет сам.
        await db.execute("""
            ALTER TABLE mem_notes
            ADD COLUMN IF NOT EXISTS content_plaintext TEXT NOT NULL DEFAULT ''
        """)
        await db.execute("""
            ALTER TABLE mem_notes
            ADD COLUMN IF NOT EXISTS tsvect_search tsvector
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_mem_notes_tsvect
            ON mem_notes USING GIN(tsvect_search)
        """)
        # Триггер: автоматически заполняет tsvector из plaintext
        await db.execute("""
            CREATE OR REPLACE FUNCTION mem_notes_tsvect_trigger()
            RETURNS trigger AS $$
            BEGIN
                NEW.tsvect_search :=
                    setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('russian', coalesce(NEW.content_plaintext, '')), 'B');
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql
        """)
        await db.execute("""
            DROP TRIGGER IF EXISTS tsvector_update ON mem_notes
        """)
        await db.execute("""
            CREATE TRIGGER tsvector_update
            BEFORE INSERT OR UPDATE OF title, content_plaintext
            ON mem_notes
            FOR EACH ROW
            EXECUTE FUNCTION mem_notes_tsvect_trigger()
        """)
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tiktok_tasks (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                note_date TEXT NOT NULL DEFAULT '',
                status TEXT DEFAULT 'pending',
                error TEXT,
                author TEXT,
                title TEXT,
                note_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tiktok_user_date ON tiktok_tasks(user_id, note_date)"
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

        # Projects — контейнеры: имя + свой диалог + привязанные заметки (материалы)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at)"
        )
        # Связь заметок с проектом (материалы). Удаление проекта не удаляет заметки —
        # только снимает привязку (SET NULL).
        await db.execute(
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"
        )
        # Диалог проекта живёт в chat_history, project_id — фильтр диалога.
        # При удалении проекта его диалог удаляется (CASCADE).
        await db.execute(
            "ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(user_id, project_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_history(user_id, project_id)"
        )

        # ── Миграция (ADR-0014): старые сессии → ветки chat_threads ──
        # Сессии-по-времени превращаются в тематические ветки: одна группа
        # (user_id, session_id) → одна ветка, заголовок из первого сообщения.
        # Проектные диалоги (project_id) не трогаем — они остаются в своём режиме.
        migrate_groups = await db.fetch(
            """SELECT user_id, session_id, MIN(created_at) as started
               FROM chat_history
               WHERE session_id IS NOT NULL AND thread_id IS NULL
               GROUP BY user_id, session_id"""
        )
        for g in migrate_groups:
            first = await db.fetchrow(
                """SELECT content FROM chat_history
                   WHERE user_id=$1 AND session_id=$2 AND role='user'
                   ORDER BY created_at ASC LIMIT 1""",
                g["user_id"],
                g["session_id"],
            )
            title = (first["content"] or "")[:60] if first else ""
            thr = await db.fetchrow(
                """INSERT INTO chat_threads (user_id, title, created_at, updated_at)
                   VALUES ($1,$2,$3,$3) RETURNING id""",
                g["user_id"],
                title,
                g["started"] or "now()",
            )
            await db.execute(
                """UPDATE chat_history SET thread_id=$1
                   WHERE user_id=$2 AND session_id=$3""",
                thr["id"],
                g["user_id"],
                g["session_id"],
            )
        # Старые «несохранённые» сообщения без сессии и без проекта — в одну ветку.
        unassigned_users = await db.fetch(
            """SELECT DISTINCT user_id, MIN(created_at) as started
               FROM chat_history
               WHERE session_id IS NULL AND thread_id IS NULL AND project_id IS NULL
               GROUP BY user_id"""
        )
        for u in unassigned_users:
            thr = await db.fetchrow(
                """INSERT INTO chat_threads (user_id, title, created_at, updated_at)
                   VALUES ($1,'старые сообщения',$2,$2) RETURNING id""",
                u["user_id"],
                u["started"] or "now()",
            )
            await db.execute(
                """UPDATE chat_history SET thread_id=$1
                   WHERE user_id=$2 AND session_id IS NULL AND thread_id IS NULL
                     AND project_id IS NULL""",
                thr["id"],
                u["user_id"],
            )
