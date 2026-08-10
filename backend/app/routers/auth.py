from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import AppUser, UserSession
from ..services.auth import create_login_session, get_current_user, hash_password, normalize_email, token_hash, verify_password


router = APIRouter(prefix="/api/auth", tags=["登录与用户"])


class Credentials(BaseModel):
    email: str
    password: str


def user_view(user: AppUser) -> dict:
    return {
        "id": user.id, "email": user.email, "is_developer": user.is_developer,
        "email_verified": user.email_verified, "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def login_response(user: AppUser, raw_token: str) -> JSONResponse:
    settings = get_settings()
    response = JSONResponse({"user": user_view(user)})
    response.set_cookie(
        settings.auth_cookie_name, raw_token, max_age=max(1, settings.auth_session_days) * 86400,
        httponly=True, secure=settings.public_ui_origin.lower().startswith("https://"), samesite="lax", path="/",
    )
    return response


@router.post("/register")
def register(payload: Credentials, request: Request, session: Session = Depends(get_session)):
    try:
        email = normalize_email(payload.email)
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if session.exec(select(AppUser).where(AppUser.email == email)).first():
        raise HTTPException(409, "该邮箱已经注册，请直接登录")
    settings = get_settings()
    developer = email == normalize_email(settings.developer_email)
    user = AppUser(
        email=email, password_hash=password_hash, is_developer=developer,
        email_verified=developer, created_at=datetime.utcnow(),
    )
    session.add(user); session.commit(); session.refresh(user)
    return login_response(user, create_login_session(session, user, request))


@router.post("/login")
def login(payload: Credentials, request: Request, session: Session = Depends(get_session)):
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user = session.exec(select(AppUser).where(AppUser.email == email)).first()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    return login_response(user, create_login_session(session, user, request))


@router.get("/me")
def me(user: AppUser = Depends(get_current_user)):
    return {"user": user_view(user), "email_delivery_configured": bool(get_settings().smtp_host)}


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    raw = request.cookies.get(settings.auth_cookie_name, "")
    if raw:
        item = session.exec(select(UserSession).where(UserSession.token_hash == token_hash(raw))).first()
        if item:
            item.revoked_at = datetime.utcnow(); session.add(item); session.commit()
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(settings.auth_cookie_name, path="/")
    return response
