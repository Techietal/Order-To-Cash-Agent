"""Password hashing helpers.

Passlib 1.7's bcrypt backend expects bcrypt's historical 72-byte truncation
behavior during backend detection. bcrypt 5 raises instead, so this small shim
keeps Passlib bcrypt usable with the installed dependency set.
"""
import bcrypt as _bcrypt
from passlib.context import CryptContext


if not hasattr(_bcrypt, "__about__"):
    _bcrypt.__about__ = type("__about__", (), {"__version__": _bcrypt.__version__})

if not getattr(_bcrypt, "_passlib_compat_hashpw", False):
    _original_hashpw = _bcrypt.hashpw

    def _hashpw_with_passlib_compat(password, salt):
        if isinstance(password, (bytes, bytearray)) and len(password) > 72:
            password = password[:72]
        return _original_hashpw(password, salt)

    _bcrypt.hashpw = _hashpw_with_passlib_compat
    _bcrypt._passlib_compat_hashpw = True


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        return pwd_context.verify(plain, stored_hash)
    except ValueError:
        return False


def is_legacy_sha256_hash(stored_hash: str) -> bool:
    return bool(stored_hash) and len(stored_hash) == 64 and all(c in "0123456789abcdef" for c in stored_hash.lower())
