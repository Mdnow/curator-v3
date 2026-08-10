import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, SECRET_KEY

security = HTTPBearer()


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
    return salt + ":" + h.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt, h = stored.split(":", 1)
    check = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
    return secrets.compare_digest(check.hex(), h)


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "exp": exp}, SECRET_KEY, algorithm=JWT_ALGORITHM
    )


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        uid = payload.get("sub")
        if uid is None:
            raise HTTPException(401, "невалидный токен")
        return int(uid)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "невалидный токен")


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    return decode_token(cred.credentials)
