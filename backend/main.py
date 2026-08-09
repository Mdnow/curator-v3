from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from backend.db import init_db
from backend.auth import hash_password, verify_password, create_token, get_current_user
from backend.models import RegisterReq, LoginReq

from backend.routes.notes import router as notes_router
from backend.routes.tasks import router as tasks_router
from backend.routes.dreams import router as dreams_router
from backend.routes.chat import router as chat_router
from backend.routes.favorites import router as favorites_router
from backend.routes.backup import router as backup_router
from backend.routes.health import router as health_router
from backend.routes.insights import router as insights_router
from backend.routes.goals import router as goals_router

app = FastAPI(title="Curator v3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://curator-v3-production.up.railway.app",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(notes_router)
app.include_router(tasks_router)
app.include_router(dreams_router)
app.include_router(chat_router)
app.include_router(favorites_router)
app.include_router(backup_router)
app.include_router(insights_router)
app.include_router(goals_router)
app.include_router(health_router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.post("/api/register")
async def register(req: RegisterReq):
    from backend.db import get_db

    async with get_db() as db:
        existing = await db.fetchrow(
            "SELECT id FROM users WHERE username=$1", req.username
        )
        if existing:
            raise HTTPException(400, "имя занято")
        h = hash_password(req.password)
        row = await db.fetchrow(
            "INSERT INTO users (username, password_hash) VALUES ($1,$2) RETURNING id",
            req.username,
            h,
        )
        uid = row["id"]
        token = create_token(uid)
        return {"token": token, "user": req.username}


@app.post("/api/login")
async def login(req: LoginReq):
    from backend.db import get_db

    async with get_db() as db:
        user = await db.fetchrow(
            "SELECT id, password_hash FROM users WHERE username=$1", req.username
        )
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(401, "неверное имя или пароль")
        token = create_token(user["id"])
        return {"token": token, "user": req.username}


@app.get("/api/me")
async def me(user_id: int = Depends(get_current_user)):
    from backend.db import get_db

    async with get_db() as db:
        user = await db.fetchrow(
            "SELECT username, created_at FROM users WHERE id=$1", user_id
        )
        if not user:
            raise HTTPException(404)
        return {"user": user["username"], "created_at": user["created_at"]}


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
