from __future__ import annotations
from passlib.hash import pbkdf2_sha256
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from app.config import get_settings

_SALT = "hm-session"
_MAX_AGE = 60 * 60 * 24 * 30  # 30 дней


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().effective_secret_key(), salt=_SALT)


# ── Пароли ────────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pbkdf2_sha256.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pbkdf2_sha256.verify(plain, hashed)


# ── Сессии (подписанная cookie) ────────────────────────────────────────────────

def make_session_token(username: str) -> str:
    return _signer().dumps({"u": username})


def decode_session_token(token: str) -> str | None:
    try:
        data = _signer().loads(token, max_age=_MAX_AGE)
        return data["u"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


# ── Dependency ────────────────────────────────────────────────────────────────

COOKIE_NAME = "hm_session"


def get_current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = decode_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Session expired")
    return username
