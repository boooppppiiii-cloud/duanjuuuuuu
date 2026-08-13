from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request
from sqlmodel import Session, select

from ..config import get_settings
from .. import database
from ..models import AppUser, Clip, FactoryJob, GeneratedAsset, MetaDeliveryPackage, Post, PublishJob, UserSession


_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise ValueError("请输入有效邮箱地址")
    return email


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32,
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login_session(session: Session, user: AppUser, request: Request) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    now = datetime.utcnow()
    session.add(UserSession(
        user_id=int(user.id), token_hash=token_hash(raw),
        expires_at=now + timedelta(days=max(1, settings.auth_session_days)),
        user_agent=(request.headers.get("user-agent") or "")[:500],
        ip_address=(request.client.host if request.client else "")[:80],
    ))
    user.last_login_at = now
    session.add(user)
    session.commit()
    return raw


def resolve_user(session: Session, raw_token: str) -> tuple[AppUser, UserSession] | None:
    if not raw_token:
        return None
    login = session.exec(select(UserSession).where(UserSession.token_hash == token_hash(raw_token))).first()
    now = datetime.utcnow()
    if not login or login.revoked_at is not None or login.expires_at <= now:
        return None
    user = session.get(AppUser, login.user_id)
    if not user or not user.is_active:
        return None
    if (now - login.last_seen_at).total_seconds() >= 3600:
        login.last_seen_at = now
        session.add(login)
        session.commit()
        # SQLAlchemy expires every ORM object in the session after commit.
        # The authentication middleware intentionally keeps these two objects
        # after this session closes, so load their values again while they are
        # still attached.  Otherwise the first request after the hourly
        # last-seen update can fail with DetachedInstanceError.
        session.refresh(user)
        session.refresh(login)
    return user, login


def current_user_id() -> int | None:
    return _current_user_id.get()


def bind_current_user(user_id: int | None):
    return _current_user_id.set(user_id)


def reset_current_user(token) -> None:
    _current_user_id.reset(token)


def get_current_user(request: Request) -> AppUser:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def get_developer_user(user: AppUser = None, request: Request = None) -> AppUser:
    item = user or (get_current_user(request) if request else None)
    if not item or not item.is_developer:
        raise HTTPException(403, "仅开发者账号可访问")
    return item


def initialize_auth() -> None:
    """Seed the reserved developer account and attach pre-auth private rows to it."""
    settings = get_settings()
    email = normalize_email(settings.developer_email)
    # Resolve the engine at call time. This matters for database restores,
    # migrations and test environments that replace the active engine.
    with Session(database.engine) as session:
        developer = session.exec(select(AppUser).where(AppUser.email == email)).first()
        if not developer and settings.developer_initial_password:
            developer = AppUser(
                email=email, password_hash=hash_password(settings.developer_initial_password),
                is_developer=True, is_active=True, email_verified=True,
            )
            session.add(developer)
            session.commit()
            session.refresh(developer)
        elif developer and not developer.is_developer:
            developer.is_developer = True
            session.add(developer)
            session.commit()
        if not developer:
            return
        # Preserve all work created before login existed without exposing it to new users.
        for model in (Clip, FactoryJob, GeneratedAsset, Post, PublishJob, MetaDeliveryPackage):
            rows = session.exec(select(model).where(model.owner_user_id.is_(None))).all()
            for row in rows:
                row.owner_user_id = developer.id
                session.add(row)
        session.commit()
