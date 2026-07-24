from cryptography.fernet import Fernet
import base64
import hashlib
from backend.config import ENCRYPTION_KEY


def _derive_key():
    key = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key)


_fernet = Fernet(_derive_key())


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
