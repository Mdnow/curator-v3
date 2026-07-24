from pydantic import BaseModel
from typing import Optional


class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class NoteReq(BaseModel):
    content: str
    note_date: str
    tags: list[str] = []
    mood: Optional[str] = None


class NoteUpdateReq(BaseModel):
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    mood: Optional[str] = None


class TaskReq(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""
    due_time: str = ""
    priority: int = 0


class TaskUpdateReq(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[int] = None
    completed: Optional[int] = None


class DreamReq(BaseModel):
    content: str
    dream_type: str = "night"
    sleep_time: Optional[str] = None
    wake_time: Optional[str] = None
    sleep_quality: Optional[int] = None
    emotion_label: Optional[str] = None


class ChatReq(BaseModel):
    message: str
