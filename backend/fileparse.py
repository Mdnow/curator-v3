"""Извлечение смысла из загруженных файлов для чата Куратора (ADR-0016)."""

import io
import os

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 МБ
MAX_TEXT_LEN = 20000  # как у заметки

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".log"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class FileParseError(Exception):
    pass


def detect_kind(filename: str) -> str:
    """'text' | 'pdf' | 'image' | 'unsupported' по расширению имени."""
    ext = os.path.splitext((filename or "").lower())[1]
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "unsupported"


def extract_text(filename: str, data: bytes) -> str:
    """Текст из txt/md/csv/json/log/pdf. Для изображений — не вызывается."""
    kind = detect_kind(filename)
    if kind == "text":
        text = _decode_text(data)
    elif kind == "pdf":
        text = _extract_pdf(data)
    else:
        raise FileParseError("поддерживаются текст, PDF и изображения")

    text = text.strip()
    if not text:
        raise FileParseError("не удалось извлечь текст из файла")
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN] + "\n…(обрезано)"
    return text


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # Бинарные данные cp1251 «декодирует» в любой мусор: если больше ~3%
        # управляющих символов — кодировка не подошла, пробуем следующую.
        controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\r\n")
        if text and controls / len(text) > 0.03:
            continue
        return text
    return data.decode("utf-8", "replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(pages)
    except Exception as e:
        raise FileParseError(f"не удалось прочитать PDF: {type(e).__name__}")
