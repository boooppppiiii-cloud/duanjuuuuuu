"""Real social platform calls used by account checks, comments and publishing."""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

import httpx

from ..config import get_settings
from ..models import Account
from .credentials import CredentialError, resolve_account_secret

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TIKTOK_API = "https://open.tiktokapis.com"
META_GRAPH = "https://graph.facebook.com"


def _error_detail(response: httpx.Response, platform: str) -> str:
    try:
        data = response.json()
        error = data.get("error") or data
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        return str(error)
    except Exception:
        return response.text[:500] or f"HTTP {response.status_code}"


def _raise(response: httpx.Response, platform: str) -> None:
    if response.is_error:
        raise RuntimeError(f"{platform} 接口失败：{_error_detail(response, platform)}")


def graph_version(account: Account) -> str:
    return str(account.credentials_json.get("graph_version") or get_settings().meta_graph_version).strip()


def youtube_access_token(account: Account) -> str:
    refresh_token = resolve_account_secret(account, "refresh_token", required=False)
    if refresh_token:
        client_id = resolve_account_secret(account, "client_id")
        client_secret = resolve_account_secret(account, "client_secret")
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=30,
        )
        _raise(response, "YouTube OAuth")
        token = str(response.json().get("access_token") or "")
        if not token:
            raise CredentialError("YouTube OAuth 未返回 access_token")
        return token
    return resolve_account_secret(account, "access_token")


def tiktok_access_token(account: Account) -> str:
    refresh_token = resolve_account_secret(account, "refresh_token", required=False)
    if refresh_token:
        client_key = resolve_account_secret(account, "client_id")
        client_secret = resolve_account_secret(account, "client_secret")
        response = httpx.post(
            f"{TIKTOK_API}/v2/oauth/token/",
            data={"client_key": client_key, "client_secret": client_secret, "grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=30,
        )
        _raise(response, "TikTok OAuth")
        token = str(response.json().get("access_token") or "")
        if not token:
            raise CredentialError("TikTok OAuth 未返回 access_token")
        return token
    return resolve_account_secret(account, "access_token")


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def check_account(account: Account) -> dict[str, Any]:
    if account.platform == "youtube":
        token = youtube_access_token(account)
        params: dict[str, Any] = {"part": "snippet,statistics", "mine": "true"}
        channel_id = str(account.credentials_json.get("channel_id") or "")
        if channel_id:
            params = {"part": "snippet,statistics", "id": channel_id}
        response = httpx.get(f"{YOUTUBE_API}/channels", params=params, headers=bearer_headers(token), timeout=30)
        _raise(response, "YouTube")
        item = (response.json().get("items") or [None])[0]
        if not item:
            raise RuntimeError("YouTube 未返回频道，请确认账号授权范围和 Channel ID")
        return {
            "platform_user_id": str(item["id"]), "name": str(item["snippet"].get("title") or account.name),
            "avatar_url": str(item["snippet"].get("thumbnails", {}).get("default", {}).get("url") or ""),
            "profile_url": f"https://www.youtube.com/channel/{item['id']}",
            "follower_count": int(item.get("statistics", {}).get("subscriberCount") or 0),
            "capabilities": ["publish", "metrics", "comments", "reply"],
        }
    if account.platform == "tiktok":
        token = tiktok_access_token(account)
        fields = "open_id,display_name,avatar_url,profile_deep_link,follower_count,video_count,likes_count"
        response = httpx.get(f"{TIKTOK_API}/v2/user/info/", params={"fields": fields}, headers=bearer_headers(token), timeout=30)
        _raise(response, "TikTok")
        error = response.json().get("error", {})
        if error.get("code") not in {None, "", "ok"}:
            raise RuntimeError(f"TikTok 接口失败：{error.get('message') or error.get('code')}")
        user = response.json().get("data", {}).get("user", {})
        if not user.get("open_id"):
            raise RuntimeError("TikTok 未返回账号身份")
        return {
            "platform_user_id": str(user["open_id"]), "name": str(user.get("display_name") or account.name),
            "avatar_url": str(user.get("avatar_url") or ""), "profile_url": str(user.get("profile_deep_link") or ""),
            "follower_count": int(user.get("follower_count") or 0),
            "capabilities": ["publish", "publish_status", "metrics"],
        }
    if account.platform in {"facebook", "instagram"}:
        token = resolve_account_secret(account, "access_token")
        key = "page_id" if account.platform == "facebook" else "ig_user_id"
        node_id = str(account.credentials_json.get(key) or account.platform_user_id or "")
        if not node_id:
            raise CredentialError(f"{key} 尚未配置")
        fields = "id,name,fan_count,picture{url}" if account.platform == "facebook" else "id,username,profile_picture_url,followers_count,media_count"
        response = httpx.get(f"{META_GRAPH}/{graph_version(account)}/{node_id}", params={"fields": fields, "access_token": token}, timeout=30)
        _raise(response, "Meta")
        item = response.json()
        name = str(item.get("name") or item.get("username") or account.name)
        return {
            "platform_user_id": str(item["id"]), "name": name,
            "avatar_url": str(item.get("profile_picture_url") or item.get("picture", {}).get("data", {}).get("url") or ""),
            "profile_url": f"https://www.facebook.com/{item['id']}" if account.platform == "facebook" else f"https://www.instagram.com/{name}/",
            "follower_count": int(item.get("fan_count") or item.get("followers_count") or 0),
            "capabilities": ["publish", "metrics", "comments", "reply"],
        }
    raise RuntimeError(f"不支持的平台：{account.platform}")


def tiktok_creator_info(account: Account) -> dict[str, Any]:
    token = tiktok_access_token(account)
    response = httpx.post(f"{TIKTOK_API}/v2/post/publish/creator_info/query/", headers=bearer_headers(token), json={}, timeout=30)
    _raise(response, "TikTok")
    data = response.json()
    error = data.get("error", {})
    if error.get("code") != "ok":
        raise RuntimeError(f"TikTok Creator Info 失败：{error.get('message') or error.get('code')}")
    creator = data.get("data", {})
    return {
        "privacy_level_options": creator.get("privacy_level_options") or [],
        "comment_disabled": bool(creator.get("comment_disabled")),
        "duet_disabled": bool(creator.get("duet_disabled")),
        "stitch_disabled": bool(creator.get("stitch_disabled")),
        "max_video_post_duration_sec": int(creator.get("max_video_post_duration_sec") or 0),
    }


def _duration_seconds(value: str) -> int | None:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return None
    hours, minutes, seconds = (int(item or 0) for item in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _youtube_analytics(token: str, video_ids: list[str]) -> dict[str, dict[str, float]]:
    """Return only metrics the authorized channel actually exposes."""
    if not video_ids:
        return {}
    common = {
        "ids": "channel==MINE", "startDate": "2005-01-01", "endDate": date.today().isoformat(),
        "dimensions": "video", "filters": f"video=={','.join(video_ids)}", "maxResults": len(video_ids),
    }
    result: dict[str, dict[str, float]] = {}
    metric_groups = [
        "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,impressions,impressionClickThroughRate",
        "estimatedRevenue",
    ]
    for metrics in metric_groups:
        response = httpx.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={**common, "metrics": metrics}, headers=bearer_headers(token), timeout=30,
        )
        if response.is_error:
            continue
        payload = response.json()
        headers = [str(item.get("name") or "") for item in payload.get("columnHeaders", [])]
        for values in payload.get("rows", []):
            row = dict(zip(headers, values))
            video_id = str(row.pop("video", ""))
            if video_id:
                result.setdefault(video_id, {}).update({key: float(value) for key, value in row.items() if value is not None})
    return result


def list_platform_media(account: Account, limit: int = 25) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    if account.platform == "youtube":
        token = youtube_access_token(account)
        channel = httpx.get(f"{YOUTUBE_API}/channels", params={"part": "contentDetails", "mine": "true"}, headers=bearer_headers(token), timeout=30)
        _raise(channel, "YouTube")
        playlist = ((channel.json().get("items") or [{}])[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"))
        if not playlist:
            return []
        playlist_response = httpx.get(f"{YOUTUBE_API}/playlistItems", params={"part": "contentDetails", "playlistId": playlist, "maxResults": limit}, headers=bearer_headers(token), timeout=30)
        _raise(playlist_response, "YouTube")
        ids = [item.get("contentDetails", {}).get("videoId") for item in playlist_response.json().get("items", [])]
        ids = [item for item in ids if item]
        if not ids:
            return []
        details = httpx.get(f"{YOUTUBE_API}/videos", params={"part": "snippet,statistics,status,contentDetails", "id": ",".join(ids)}, headers=bearer_headers(token), timeout=30)
        _raise(details, "YouTube")
        analytics = _youtube_analytics(token, ids)
        rows = []
        for item in details.json().get("items", []):
            video_id = str(item["id"]); snippet = item.get("snippet", {}); stats = item.get("statistics", {}); extra = analytics.get(video_id, {})
            views = int(stats.get("viewCount") or 0); revenue = extra.get("estimatedRevenue")
            rows.append({
                "id": video_id, "title": str(snippet.get("title") or ""), "published_at": snippet.get("publishedAt"),
                "views": views, "likes": int(stats.get("likeCount") or 0), "comments": int(stats.get("commentCount") or 0),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": str(snippet.get("thumbnails", {}).get("medium", {}).get("url") or snippet.get("thumbnails", {}).get("default", {}).get("url") or ""),
                "duration_seconds": _duration_seconds(str(item.get("contentDetails", {}).get("duration") or "")),
                "impressions": int(extra["impressions"]) if "impressions" in extra else None,
                "clicks": None, "ctr": extra.get("impressionClickThroughRate"),
                "watch_time_seconds": round(extra["estimatedMinutesWatched"] * 60) if "estimatedMinutesWatched" in extra else None,
                "estimated_revenue": revenue, "rpm": revenue / views * 1000 if revenue is not None and views else None,
                "subscribers_gained": int(extra["subscribersGained"]) if "subscribersGained" in extra else None,
            })
        return rows
    token = tiktok_access_token(account) if account.platform == "tiktok" else resolve_account_secret(account, "access_token")
    if account.platform == "tiktok":
        response = httpx.post(f"{TIKTOK_API}/v2/video/list/", params={"fields": "id,title,video_description,create_time,view_count,like_count,comment_count,share_url,cover_image_url,duration"}, headers=bearer_headers(token), json={"max_count": min(limit, 20)}, timeout=30)
        _raise(response, "TikTok")
        return [{
            "id": str(item["id"]), "title": str(item.get("title") or item.get("video_description") or ""),
            "published_at": datetime.fromtimestamp(int(item.get("create_time") or 0)).isoformat() if item.get("create_time") else None,
            "views": int(item.get("view_count") or 0), "likes": int(item.get("like_count") or 0), "comments": int(item.get("comment_count") or 0),
            "url": str(item.get("share_url") or ""), "thumbnail_url": str(item.get("cover_image_url") or ""),
            "duration_seconds": int(item.get("duration") or 0) or None, "impressions": None, "clicks": None, "ctr": None,
            "watch_time_seconds": None, "estimated_revenue": None, "rpm": None, "subscribers_gained": None,
        } for item in response.json().get("data", {}).get("videos", [])]
    node = str(account.credentials_json.get("page_id" if account.platform == "facebook" else "ig_user_id") or account.platform_user_id)
    edge = "videos" if account.platform == "facebook" else "media"
    fields = "id,title,description,created_time,permalink_url,picture,views,likes.summary(true),comments.summary(true)" if account.platform == "facebook" else "id,caption,timestamp,permalink,thumbnail_url,media_url,like_count,comments_count,media_type"
    response = httpx.get(f"{META_GRAPH}/{graph_version(account)}/{node}/{edge}", params={"fields": fields, "limit": limit, "access_token": token}, timeout=30)
    _raise(response, "Meta")
    rows = []
    for item in response.json().get("data", []):
        rows.append({
            "id": str(item["id"]), "title": str(item.get("title") or item.get("caption") or item.get("description") or "")[:160],
            "published_at": item.get("timestamp") or item.get("created_time"), "views": int(item.get("views") or 0),
            "likes": int(item.get("like_count") or item.get("likes", {}).get("summary", {}).get("total_count") or 0),
            "comments": int(item.get("comments_count") or item.get("comments", {}).get("summary", {}).get("total_count") or 0),
            "url": str(item.get("permalink") or item.get("permalink_url") or ""),
            "thumbnail_url": str(item.get("thumbnail_url") or item.get("picture") or item.get("media_url") or ""),
            "duration_seconds": None, "impressions": None, "clicks": None, "ctr": None, "watch_time_seconds": None,
            "estimated_revenue": None, "rpm": None, "subscribers_gained": None,
        })
    return rows


def list_comments(account: Account, limit: int = 100) -> list[dict[str, Any]]:
    if account.platform == "tiktok":
        raise RuntimeError("TikTok 商业 Content Posting/Display API 不提供评论列表；本功能不会伪造评论，可使用平台导出文件导入")
    media = list_platform_media(account, min(20, limit))
    token = youtube_access_token(account) if account.platform == "youtube" else resolve_account_secret(account, "access_token")
    rows: list[dict[str, Any]] = []
    for video in media:
        if len(rows) >= limit:
            break
        if account.platform == "youtube":
            response = httpx.get(f"{YOUTUBE_API}/commentThreads", params={"part": "snippet", "videoId": video["id"], "textFormat": "plainText", "order": "time", "maxResults": min(100, limit - len(rows))}, headers=bearer_headers(token), timeout=30)
            if response.status_code == 403:
                continue
            _raise(response, "YouTube")
            for thread in response.json().get("items", []):
                top = thread.get("snippet", {}).get("topLevelComment", {})
                snippet = top.get("snippet", {})
                rows.append({"external_id": str(top.get("id") or ""), "video_id": video["id"], "video_title": video["title"], "video_url": video.get("url", ""), "author_name": str(snippet.get("authorDisplayName") or ""), "author_handle": str(snippet.get("authorChannelId", {}).get("value") or ""), "text_original": str(snippet.get("textOriginal") or snippet.get("textDisplay") or ""), "like_count": int(snippet.get("likeCount") or 0), "published_at": snippet.get("publishedAt")})
        else:
            fields = "id,from,message,like_count,created_time" if account.platform == "facebook" else "id,text,username,timestamp,like_count"
            response = httpx.get(f"{META_GRAPH}/{graph_version(account)}/{video['id']}/comments", params={"fields": fields, "limit": min(100, limit - len(rows)), "access_token": token}, timeout=30)
            _raise(response, "Meta")
            for item in response.json().get("data", []):
                rows.append({"external_id": str(item.get("id") or ""), "video_id": video["id"], "video_title": video["title"], "video_url": video.get("url", ""), "author_name": str(item.get("username") or item.get("from", {}).get("name") or ""), "author_handle": str(item.get("username") or ""), "text_original": str(item.get("text") or item.get("message") or ""), "like_count": int(item.get("like_count") or 0), "published_at": item.get("timestamp") or item.get("created_time")})
    return rows[:limit]


def reply_to_comment(account: Account, external_id: str, message: str) -> str:
    if account.platform == "youtube":
        response = httpx.post(f"{YOUTUBE_API}/comments", params={"part": "snippet"}, headers=bearer_headers(youtube_access_token(account)), json={"snippet": {"parentId": external_id, "textOriginal": message}}, timeout=30)
        _raise(response, "YouTube")
    elif account.platform in {"facebook", "instagram"}:
        edge = "comments" if account.platform == "facebook" else "replies"
        response = httpx.post(f"{META_GRAPH}/{graph_version(account)}/{external_id}/{edge}", params={"access_token": resolve_account_secret(account, "access_token"), "message": message}, timeout=30)
        _raise(response, "Meta")
    else:
        raise RuntimeError("TikTok 当前官方商业 API 不支持评论回复")
    reply_id = str(response.json().get("id") or "")
    if not reply_id:
        raise RuntimeError("平台未返回回复 ID，未记录为成功")
    return reply_id
