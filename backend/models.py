from pydantic import BaseModel, field_validator
from typing import Optional


class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


def _check_len(v: str, field: str, min_len: int, max_len: int) -> str:
    if v is None:
        raise ValueError(f"{field} не может быть пустым")
    s = v.strip()
    if len(s) < min_len:
        raise ValueError(f"{field} слишком короткий")
    if len(s) > max_len:
        raise ValueError(f"{field} слишком длинный (макс. {max_len})")
    return v


class NoteReq(BaseModel):
    content: str
    note_date: str
    tags: list[str] = []
    mood: Optional[str] = None
    project_id: Optional[int] = None

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: str) -> str:
        return _check_len(v, "content", 1, 20000)

    @field_validator("note_date")
    @classmethod
    def _v_date(cls, v: str) -> str:
        return _check_len(v, "note_date", 1, 10)


class ProjectReq(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return _check_len(v, "name", 1, 200)


class ProjectUpdateReq(BaseModel):
    name: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _check_len(v, "name", 1, 200)


class ImportNoteReq(BaseModel):
    content: str
    note_date: str
    tags: list[str] = []
    mood: Optional[str] = None
    ai_title: str = ""
    ai_summary: str = ""
    ai_category: str = ""
    ai_sentiment: float = 0.0
    ai_keyphrases: list[str] = []
    ai_theses: list[str] = []

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: str) -> str:
        return _check_len(v, "content", 1, 20000)

    @field_validator("note_date")
    @classmethod
    def _v_date(cls, v: str) -> str:
        return _check_len(v, "note_date", 1, 10)


class NoteUpdateReq(BaseModel):
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    mood: Optional[str] = None
    project_id: Optional[int] = None

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _check_len(v, "content", 1, 20000)


class TaskReq(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""
    due_time: str = ""
    priority: int = 0

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: str) -> str:
        return _check_len(v, "title", 1, 500)

    @field_validator("description")
    @classmethod
    def _v_desc(cls, v: str) -> str:
        if not v:
            return v
        return _check_len(v, "description", 1, 20000)


class TaskUpdateReq(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[int] = None
    completed: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _check_len(v, "title", 1, 500)

    @field_validator("description")
    @classmethod
    def _v_desc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _check_len(v, "description", 1, 20000)


class DreamReq(BaseModel):
    content: str
    dream_type: str = "night"
    sleep_time: Optional[str] = None
    wake_time: Optional[str] = None
    sleep_quality: Optional[int] = None
    emotion_label: Optional[str] = None

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: str) -> str:
        return _check_len(v, "content", 1, 20000)


class ChatReq(BaseModel):
    message: str
    session_id: Optional[int] = None
    project_id: Optional[int] = None
    goal_id: Optional[int] = None
    thread_id: Optional[int] = None

    @field_validator("message")
    @classmethod
    def _v_message(cls, v: str) -> str:
        return _check_len(v, "message", 1, 10000)


class TikTokImportReq(BaseModel):
    url: str
    note_date: str = ""

    @field_validator("url")
    @classmethod
    def _v_url(cls, v: str) -> str:
        return _check_len(v, "url", 8, 2000)


class MemImportReq(BaseModel):
    note_id: str
    note_date: str = ""
    tags: list[str] = []

    @field_validator("note_id")
    @classmethod
    def _v_note_id(cls, v: str) -> str:
        return _check_len(v, "note_id", 1, 100)


class MemExportReq(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _v_content(cls, v: str) -> str:
        return _check_len(v, "content", 1, 20000)
