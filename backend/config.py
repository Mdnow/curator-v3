import os
import secrets
import tempfile

_project_root = os.path.join(os.path.dirname(__file__), "..")
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() not in os.environ:
                    os.environ[key.strip()] = val.strip()

SECRET_KEY = os.getenv("CURATOR_SECRET") or secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 720

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

ZEN_API_KEY = os.getenv("ZEN_API_KEY", "")
ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"

DATABASE_URL = os.getenv("DATABASE_URL", "")

ENCRYPTION_KEY = os.getenv("CURATOR_ENCRYPTION_KEY") or secrets.token_hex(32)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TMP_DIR = os.getenv("TMP_DIR", "") or os.path.join(tempfile.gettempdir(), "tiktok")
