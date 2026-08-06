from __future__ import annotations

import secrets
import time
from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Account, PlatformApp
from ..schemas import PlatformAppConfigRequest
from ..services.credentials import decrypt_secret, encrypt_secret, store_secret_fields
from ..services.social_integrations import META_GRAPH, TIKTOK_API, YOUTUBE_API, bearer_headers

router = APIRouter(prefix="/api/integrations", tags=["平台真实连接"])
_oauth_states: dict[str, tuple[str, float]] = {}


def callbacks() -> dict[str, str]:
    origin = get_settings().api_origin
    return {platform: f"{origin}/api/integrations/oauth/{platform}/callback" for platform in ("youtube", "tiktok", "meta")}


def _app(session: Session, platform: str) -> PlatformApp:
    item = session.exec(select(PlatformApp).where(PlatformApp.platform == platform)).first()
    if not item or not item.client_id or not item.client_secret_encrypted:
        raise HTTPException(422, f"请先配置 {platform} 开发者应用的 Client ID 和 Client Secret")
    return item


def _app_view(item: PlatformApp | None) -> dict:
    return {"client_id": item.client_id if item else "", "client_secret_set": bool(item and item.client_secret_encrypted), "updated_at": item.updated_at if item else None}


@router.get("/config")
def integration_config(session: Session = Depends(get_session)):
    apps = {item.platform: item for item in session.exec(select(PlatformApp)).all()}
    return {
        "vault_ready": bool(get_settings().credential_secret),
        "public_media_ready": bool(get_settings().credential_secret and get_settings().public_media_base_url.startswith("https://")),
        "callbacks": callbacks(),
        "apps": {platform: _app_view(apps.get(platform)) for platform in ("youtube", "meta", "tiktok")},
    }


@router.put("/config/{platform}")
def save_integration_config(platform: str, payload: PlatformAppConfigRequest, session: Session = Depends(get_session)):
    if platform not in {"youtube", "meta", "tiktok"}:
        raise HTTPException(404, "平台不存在")
    item = session.exec(select(PlatformApp).where(PlatformApp.platform == platform)).first() or PlatformApp(platform=platform)
    if payload.client_id.strip():
        item.client_id = payload.client_id.strip()
    if payload.client_secret:
        try:
            item.client_secret_encrypted = encrypt_secret(payload.client_secret)
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
    if not item.client_id or not item.client_secret_encrypted:
        raise HTTPException(422, "Client ID 与 Client Secret 均为必填")
    item.updated_at = datetime.now()
    session.add(item); session.commit(); session.refresh(item)
    return _app_view(item)


@router.delete("/config/{platform}")
def clear_integration_config(platform: str, session: Session = Depends(get_session)):
    item = session.exec(select(PlatformApp).where(PlatformApp.platform == platform)).first()
    if item:
        session.delete(item); session.commit()
    return {"deleted": bool(item)}


@router.post("/oauth/{platform}/start")
def oauth_start(platform: str, session: Session = Depends(get_session)):
    item = _app(session, platform)
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (platform, time.time() + 600)
    callback = callbacks()[platform]
    if platform == "youtube":
        query = urlencode({"client_id": item.client_id, "redirect_uri": callback, "response_type": "code", "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "scope": "openid email https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/yt-analytics-monetary.readonly", "state": state})
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
    elif platform == "tiktok":
        query = urlencode({"client_key": item.client_id, "redirect_uri": callback, "response_type": "code", "scope": "user.info.basic,user.info.stats,video.list,video.publish", "state": state})
        url = f"https://www.tiktok.com/v2/auth/authorize/?{query}"
    else:
        graph = get_settings().meta_graph_version
        query = urlencode({"client_id": item.client_id, "redirect_uri": callback, "response_type": "code", "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,read_insights,instagram_basic,instagram_content_publish,instagram_manage_comments,instagram_manage_insights,business_management", "state": state})
        url = f"https://www.facebook.com/{graph}/dialog/oauth?{query}"
    return {"authorization_url": url, "expires_in": 600}


def _consume_state(state: str, platform: str) -> None:
    record = _oauth_states.pop(state, None)
    if not record or record[0] != platform or record[1] < time.time():
        raise HTTPException(400, "OAuth state 无效或已过期，请回到账号矩阵重新连接")


def _upsert_account(session: Session, platform: str, platform_id: str, name: str, credentials: dict, avatar_url: str = "", profile_url: str = "", followers: int = 0, capabilities: list[str] | None = None) -> Account:
    account = session.exec(select(Account).where(Account.platform == platform, Account.platform_user_id == platform_id)).first()
    if not account:
        placeholders = session.exec(select(Account).where(Account.platform == platform, Account.platform_user_id == "")).all()
        if len(placeholders) == 1:
            account = placeholders[0]
    if not account:
        account = Account(platform=platform, platform_user_id=platform_id, name=name, account_type="official")
    account.platform_user_id = platform_id
    account.name = name; account.credentials_json = credentials; account.avatar_url = avatar_url; account.profile_url = profile_url
    account.follower_count = followers; account.capabilities = capabilities or []; account.status = "connected"
    account.last_error = ""; account.last_checked_at = datetime.now(); account.connected_at = account.connected_at or datetime.now()
    session.add(account); session.commit(); session.refresh(account)
    return account


def _redirect(platform: str, count: int) -> RedirectResponse:
    ui = get_settings().public_ui_origin.rstrip("/")
    return RedirectResponse(f"{ui}/matrix?oauth=success&platform={platform}&accounts={count}")


@router.get("/oauth/{platform}/callback")
def oauth_callback(platform: str, code: str = "", state: str = "", error: str = "", session: Session = Depends(get_session)):
    if error:
        raise HTTPException(400, f"平台拒绝授权：{error}")
    if not code:
        raise HTTPException(400, "OAuth 回调缺少 code")
    _consume_state(state, platform)
    app = _app(session, platform)
    secret = decrypt_secret(app.client_secret_encrypted)
    callback = callbacks()[platform]
    if platform == "youtube":
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={"client_id": app.client_id, "client_secret": secret, "code": code, "grant_type": "authorization_code", "redirect_uri": callback}, timeout=30)
        if token_response.is_error:
            raise HTTPException(422, f"YouTube OAuth 交换失败：{token_response.text[:500]}")
        tokens = token_response.json(); access_token = str(tokens.get("access_token") or "")
        profile = httpx.get(f"{YOUTUBE_API}/channels", params={"part": "snippet,statistics", "mine": "true"}, headers=bearer_headers(access_token), timeout=30)
        if profile.is_error or not profile.json().get("items"):
            raise HTTPException(422, "YouTube 授权成功但无法读取频道")
        item = profile.json()["items"][0]
        credentials = store_secret_fields({"channel_id": str(item["id"]), "default_privacy": "private"}, {"access_token": access_token, "refresh_token": str(tokens.get("refresh_token") or ""), "client_id": app.client_id, "client_secret": secret}, {})
        _upsert_account(session, "youtube", str(item["id"]), str(item["snippet"].get("title") or "YouTube"), credentials, str(item["snippet"].get("thumbnails", {}).get("default", {}).get("url") or ""), f"https://www.youtube.com/channel/{item['id']}", int(item.get("statistics", {}).get("subscriberCount") or 0), ["publish", "metrics", "comments", "reply"])
        return _redirect(platform, 1)
    if platform == "tiktok":
        token_response = httpx.post(f"{TIKTOK_API}/v2/oauth/token/", data={"client_key": app.client_id, "client_secret": secret, "code": code, "grant_type": "authorization_code", "redirect_uri": callback}, timeout=30)
        if token_response.is_error:
            raise HTTPException(422, f"TikTok OAuth 交换失败：{token_response.text[:500]}")
        tokens = token_response.json(); access_token = str(tokens.get("access_token") or "")
        fields = "open_id,display_name,avatar_url,profile_deep_link,follower_count"
        profile = httpx.get(f"{TIKTOK_API}/v2/user/info/", params={"fields": fields}, headers=bearer_headers(access_token), timeout=30)
        user = profile.json().get("data", {}).get("user", {}) if not profile.is_error else {}
        if not user.get("open_id"):
            raise HTTPException(422, "TikTok 授权成功但无法读取账号")
        credentials = store_secret_fields({"open_id": str(user["open_id"])}, {"access_token": access_token, "refresh_token": str(tokens.get("refresh_token") or ""), "client_id": app.client_id, "client_secret": secret}, {})
        _upsert_account(session, "tiktok", str(user["open_id"]), str(user.get("display_name") or "TikTok"), credentials, str(user.get("avatar_url") or ""), str(user.get("profile_deep_link") or ""), int(user.get("follower_count") or 0), ["publish", "publish_status", "metrics"])
        return _redirect(platform, 1)
    graph = get_settings().meta_graph_version
    token_response = httpx.get(f"{META_GRAPH}/{graph}/oauth/access_token", params={"client_id": app.client_id, "client_secret": secret, "redirect_uri": callback, "code": code}, timeout=30)
    if token_response.is_error:
        raise HTTPException(422, f"Meta OAuth 交换失败：{token_response.text[:500]}")
    user_token = str(token_response.json().get("access_token") or "")
    pages_response = httpx.get(f"{META_GRAPH}/{graph}/me/accounts", params={"access_token": user_token, "fields": "id,name,access_token,fan_count,picture{url},instagram_business_account{id,username,profile_picture_url,followers_count,media_count}", "limit": 100}, timeout=30)
    if pages_response.is_error:
        raise HTTPException(422, f"Meta 主页读取失败：{pages_response.text[:500]}")
    count = 0
    for page in pages_response.json().get("data", []):
        page_id = str(page.get("id") or ""); page_token = str(page.get("access_token") or "")
        if not page_id or not page_token:
            continue
        fb_credentials = store_secret_fields({"page_id": page_id, "graph_version": graph}, {"access_token": page_token}, {})
        _upsert_account(session, "facebook", page_id, str(page.get("name") or "Facebook Page"), fb_credentials, str(page.get("picture", {}).get("data", {}).get("url") or ""), f"https://www.facebook.com/{page_id}", int(page.get("fan_count") or 0), ["publish", "metrics", "comments", "reply"]); count += 1
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_id = str(ig["id"])
            ig_credentials = store_secret_fields({"ig_user_id": ig_id, "page_id": page_id, "graph_version": graph}, {"access_token": page_token}, {})
            _upsert_account(session, "instagram", ig_id, str(ig.get("username") or "Instagram"), ig_credentials, str(ig.get("profile_picture_url") or ""), f"https://www.instagram.com/{ig.get('username')}/", int(ig.get("followers_count") or 0), ["publish", "metrics", "comments", "reply"]); count += 1
    if not count:
        raise HTTPException(422, "Meta 授权完成，但没有读取到可管理的 Facebook Page 或关联 Instagram 专业账号")
    return _redirect(platform, count)
