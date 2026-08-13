"""Real social platform calls used by account checks, comments and publishing."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import get_settings
from ..models import Account
from .credentials import CredentialError, resolve_account_secret

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TIKTOK_API = "https://open.tiktokapis.com"
META_GRAPH = "https://graph.facebook.com"
ACCOUNT_INSIGHT_CACHE_TTL = 300
ACCOUNT_MEDIA_CACHE_TTL = 300
_account_insight_cache: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}
_account_media_cache: dict[tuple[int, int], tuple[float, list[dict[str, Any]]]] = {}


def _business_today() -> date:
    """Use the operators' reporting timezone rather than the server's UTC date."""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _cache_insight(key: tuple[int, str, str], result: dict[str, Any]) -> dict[str, Any]:
    _account_insight_cache[key] = (monotonic(), result)
    return result


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


def _youtube_analytics(token: str, video_ids: list[str], start: date | None = None, end: date | None = None) -> dict[str, dict[str, float | str]]:
    """Return only metrics the authorized channel actually exposes."""
    if not video_ids:
        return {}
    common = {
        "ids": "channel==MINE", "startDate": (start or date(2005, 1, 1)).isoformat(), "endDate": (end or _business_today()).isoformat(),
        "dimensions": "video", "filters": f"video=={','.join(video_ids)}", "maxResults": len(video_ids),
    }
    result: dict[str, dict[str, float | str]] = {}
    metric_groups = [
        "views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
        "videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
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
    # Ask Analytics for YouTube's own content classification. Duration is not a
    # reliable Shorts detector now that Shorts can be longer than 60 seconds.
    type_response = httpx.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={**common, "dimensions": "video,creatorContentType", "metrics": "views"},
        headers=bearer_headers(token),
        timeout=30,
    )
    if not type_response.is_error:
        payload = type_response.json()
        headers = [str(item.get("name") or "") for item in payload.get("columnHeaders", [])]
        for values in payload.get("rows", []):
            row = dict(zip(headers, values))
            video_id = str(row.get("video") or "")
            creator_type = str(row.get("creatorContentType") or "")
            if video_id and creator_type:
                result.setdefault(video_id, {})["creatorContentType"] = creator_type
    return result


def _youtube_time_report(token: str, start: date, end: date, metrics: str, dimension: str = "day", content_type: str = "all") -> tuple[list[dict[str, float | str]], str]:
    filters = None
    if content_type == "shorts":
        filters = "creatorContentType==SHORTS"
    elif content_type == "videos":
        filters = "creatorContentType==VIDEO_ON_DEMAND"
    params = {
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimension,
        "metrics": metrics,
        "sort": dimension,
    }
    if filters:
        params["filters"] = filters
    response = httpx.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params=params,
        headers=bearer_headers(token),
        timeout=30,
    )
    if response.is_error:
        return [], _error_detail(response, "YouTube Analytics")
    payload = response.json()
    headers = [str(item.get("name") or "") for item in payload.get("columnHeaders", [])]
    rows = []
    for values in payload.get("rows", []):
        row = dict(zip(headers, values))
        rows.append({
            key: str(value) if key == dimension else float(value)
            for key, value in row.items()
            if value is not None
        })
    return rows, ""


def _change_rate(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return (float(current) - float(previous)) / abs(float(previous)) * 100


def account_insights(account: Account, days: int | str = "all", force_refresh: bool = False, content_type: str = "all") -> dict[str, Any]:
    """Read account-level analytics from official platform APIs without synthetic values."""
    content_type = content_type if content_type in {"all", "videos", "shorts"} else "all"
    cache_key = (int(account.id or 0), str(days).lower(), content_type)
    cached = _account_insight_cache.get(cache_key)
    if not force_refresh and cached and monotonic() - cached[0] < ACCOUNT_INSIGHT_CACHE_TTL:
        return cached[1]
    all_time = str(days).lower() in {"all", "0", "全部"}
    # YouTube Studio's standard ranges use complete processed days. Analytics
    # commonly settles two days behind today (e.g. Aug 13 -> Aug 11).
    today = _business_today()
    end = today - timedelta(days=2) if account.platform == "youtube" else today
    selected_days = None if all_time else max(7, min(int(days), 365))
    start = date(2005, 2, 14) if all_time else end - timedelta(days=selected_days - 1)
    unavailable: list[str] = []

    if account.platform == "youtube":
        token = youtube_access_token(account)
        channel_response = httpx.get(
            f"{YOUTUBE_API}/channels",
            params={"part": "snippet,statistics", "mine": "true"},
            headers=bearer_headers(token),
            timeout=30,
        )
        _raise(channel_response, "YouTube")
        channel = (channel_response.json().get("items") or [{}])[0]
        stats = channel.get("statistics", {})
        published_at = str(channel.get("snippet", {}).get("publishedAt") or "")[:10]
        if all_time and published_at:
            start = date.fromisoformat(published_at)

        dimension = "month" if all_time else "day"
        report_start = start
        report_end = end
        previous_start = None if all_time else start - timedelta(days=selected_days or 0)
        query_start = previous_start or report_start

        daily: dict[str, dict[str, float | str | None]] = {}
        groups = [
            ("核心观看数据", "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost"),
            ("曝光与点击率", "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"),
            ("广告收入", "estimatedRevenue"),
        ]
        for label, metrics in groups:
            rows, error = _youtube_time_report(token, query_start, report_end, metrics, dimension, content_type)
            if error:
                unavailable.append(f"{label}：{error}")
                continue
            for row in rows:
                key = str(row.get(dimension) or "")
                if key:
                    daily.setdefault(key, {"date": key}).update(row)

        series = []
        cursor = query_start
        while cursor <= report_end:
            key = cursor.strftime("%Y-%m") if all_time else cursor.isoformat()
            row = daily.get(key, {"date": key})
            series.append({
                "date": f"{key}-01" if all_time else key,
                "views": int(row.get("views") or 0),
                "watch_time_seconds": round(float(row.get("estimatedMinutesWatched") or 0) * 60),
                "average_view_duration_seconds": float(row["averageViewDuration"]) if row.get("averageViewDuration") is not None else None,
                "impressions": int(row["videoThumbnailImpressions"]) if row.get("videoThumbnailImpressions") is not None else None,
                "ctr": float(row["videoThumbnailImpressionsClickRate"]) if row.get("videoThumbnailImpressionsClickRate") is not None else None,
                "estimated_revenue": float(row["estimatedRevenue"]) if row.get("estimatedRevenue") is not None else None,
                "subscribers_gained": int(row.get("subscribersGained") or 0),
                "subscribers_lost": int(row.get("subscribersLost") or 0),
            })
            if all_time:
                cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
            else:
                cursor += timedelta(days=1)

        current_series = series if all_time else [item for item in series if item["date"][:10] >= start.isoformat()]
        previous_series = []
        if previous_start:
            previous_series = [item for item in series if previous_start.isoformat() <= item["date"][:10] < start.isoformat()]
        views = sum(item["views"] for item in current_series)
        watch_time = sum(item["watch_time_seconds"] for item in current_series)
        impression_rows = [item for item in current_series if item["impressions"] is not None]
        impression_total = sum(int(item["impressions"] or 0) for item in impression_rows)
        weighted_ctr = sum(int(item["impressions"] or 0) * float(item["ctr"] or 0) for item in impression_rows)
        revenue_rows = [item for item in current_series if item["estimated_revenue"] is not None]
        revenue = sum(float(item["estimated_revenue"] or 0) for item in revenue_rows) if revenue_rows else None
        previous_views = sum(int(item["views"]) for item in previous_series) if previous_series else None
        previous_watch = sum(int(item["watch_time_seconds"]) for item in previous_series) if previous_series else None
        previous_impression_rows = [item for item in previous_series if item["impressions"] is not None]
        previous_impressions = sum(int(item["impressions"] or 0) for item in previous_impression_rows) if previous_impression_rows else None
        previous_ctr = (sum(int(item["impressions"] or 0) * float(item["ctr"] or 0) for item in previous_impression_rows) / previous_impressions) if previous_impressions else None
        previous_revenue_rows = [item for item in previous_series if item["estimated_revenue"] is not None]
        previous_revenue = sum(float(item["estimated_revenue"] or 0) for item in previous_revenue_rows) if previous_revenue_rows else None
        previous_net_subscribers = (sum(int(item["subscribers_gained"]) - int(item["subscribers_lost"]) for item in previous_series) if previous_series else None)
        current_net_subscribers = sum(int(item["subscribers_gained"]) - int(item["subscribers_lost"]) for item in current_series)
        current_average = watch_time / views if views else None
        previous_average = previous_watch / previous_views if previous_watch is not None and previous_views else None
        current_rpm = revenue / views * 1000 if revenue is not None and views else None
        previous_rpm = previous_revenue / previous_views * 1000 if previous_revenue is not None and previous_views else None
        followers = int(stats.get("subscriberCount") or account.follower_count or 0)
        return _cache_insight(cache_key, {
            "account_id": account.id,
            "platform": account.platform,
            "range": {"preset": "all" if all_time else str(selected_days), "days": (end - start).days + 1, "start": start.isoformat(), "end": end.isoformat(), "previous_start": previous_start.isoformat() if previous_start else None, "previous_end": (start - timedelta(days=1)).isoformat() if previous_start else None},
            "content_type": content_type,
            "source": "youtube_analytics",
            "series_mode": "daily_activity",
            "totals": {
                "views": views,
                "channel_views": int(stats.get("viewCount") or 0),
                "impressions": impression_total if impression_rows else None,
                "ctr": weighted_ctr / impression_total if impression_total else None,
                "watch_time_seconds": watch_time,
                "average_view_duration_seconds": current_average,
                "estimated_revenue": revenue,
                "rpm": current_rpm,
                "subscribers_gained": sum(item["subscribers_gained"] for item in current_series),
                "subscribers_lost": sum(item["subscribers_lost"] for item in current_series),
                "followers": followers,
                "video_count": int(stats.get("videoCount") or 0),
            },
            "changes": {
                "views": _change_rate(views, previous_views),
                "impressions": _change_rate(impression_total if impression_rows else None, previous_impressions),
                "ctr": _change_rate(weighted_ctr / impression_total if impression_total else None, previous_ctr),
                "watch_time_seconds": _change_rate(watch_time, previous_watch),
                "average_view_duration_seconds": _change_rate(current_average, previous_average),
                "estimated_revenue": _change_rate(revenue, previous_revenue),
                "rpm": _change_rate(current_rpm, previous_rpm),
                "net_subscribers": _change_rate(current_net_subscribers, previous_net_subscribers),
            },
            "series": current_series,
            "unavailable": unavailable,
        })

    media = list_platform_media(account, 50)
    daily_media: dict[str, dict[str, Any]] = {}
    for item in media:
        published = str(item.get("published_at") or "")[:10]
        if not published or published < start.isoformat() or published > end.isoformat():
            continue
        point = daily_media.setdefault(published, {"date": published, "views": 0, "watch_time_seconds": 0, "estimated_revenue": None, "subscribers_gained": 0, "subscribers_lost": 0, "impressions": None, "ctr": None, "average_view_duration_seconds": None})
        point["views"] += int(item.get("views") or 0)
        point["watch_time_seconds"] += int(item.get("watch_time_seconds") or 0)
    series = [daily_media[key] for key in sorted(daily_media)]
    period_media = [item for item in media if start.isoformat() <= str(item.get("published_at") or "")[:10] <= end.isoformat()]
    return _cache_insight(cache_key, {
        "account_id": account.id,
        "platform": account.platform,
        "range": {"preset": "all" if all_time else str(selected_days), "days": (end - start).days + 1, "start": start.isoformat(), "end": end.isoformat(), "previous_start": None, "previous_end": None},
        "content_type": content_type,
        "source": "platform_media",
        "series_mode": "published_content_totals",
        "totals": {
            "views": sum(int(item.get("views") or 0) for item in period_media),
            "channel_views": None,
            "impressions": None,
            "ctr": None,
            "watch_time_seconds": None,
            "average_view_duration_seconds": None,
            "estimated_revenue": None,
            "rpm": None,
            "subscribers_gained": None,
            "subscribers_lost": None,
            "followers": account.follower_count,
            "video_count": len(media),
        },
        "changes": {},
        "series": series,
        "unavailable": ["当前平台官方接口未返回账号级按日观看、广告收入或点击率；趋势图按发布日期汇总已读取内容。"],
    })


def list_platform_media(account: Account, limit: int = 25, force_refresh: bool = False) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    cache_key = (int(account.id or 0), limit)
    cached = _account_media_cache.get(cache_key)
    if cache_key[0] and not force_refresh and cached and monotonic() - cached[0] < ACCOUNT_MEDIA_CACHE_TTL:
        return cached[1]
    rows = _list_platform_media_uncached(account, limit)
    if cache_key[0]:
        _account_media_cache[cache_key] = (monotonic(), rows)
    return rows


def _list_platform_media_uncached(account: Account, limit: int = 25) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    if account.platform == "youtube":
        token = youtube_access_token(account)
        channel = httpx.get(f"{YOUTUBE_API}/channels", params={"part": "contentDetails", "mine": "true"}, headers=bearer_headers(token), timeout=30)
        _raise(channel, "YouTube")
        playlist = ((channel.json().get("items") or [{}])[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"))
        if not playlist:
            return []
        ids: list[str] = []
        page_token = ""
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": min(50, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            playlist_response = httpx.get(f"{YOUTUBE_API}/playlistItems", params=params, headers=bearer_headers(token), timeout=30)
            _raise(playlist_response, "YouTube")
            payload = playlist_response.json()
            ids.extend(str(item.get("contentDetails", {}).get("videoId") or "") for item in payload.get("items", []))
            ids = [item for item in ids if item]
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        if not ids:
            return []
        detail_items: list[dict[str, Any]] = []
        analytics: dict[str, dict[str, float | str]] = {}
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            details = httpx.get(f"{YOUTUBE_API}/videos", params={"part": "snippet,statistics,status,contentDetails", "id": ",".join(batch)}, headers=bearer_headers(token), timeout=30)
            _raise(details, "YouTube")
            detail_items.extend(details.json().get("items", []))
            analytics.update(_youtube_analytics(token, batch))
        rows = []
        for item in detail_items:
            video_id = str(item["id"]); snippet = item.get("snippet", {}); status = item.get("status", {}); stats = item.get("statistics", {}); extra = analytics.get(video_id, {})
            views = int(stats.get("viewCount") or 0); revenue = extra.get("estimatedRevenue")
            published_at = snippet.get("publishedAt")
            scheduled_at = status.get("publishAt")
            privacy_status = str(status.get("privacyStatus") or "")
            # For an owner reading a private upload, YouTube's snippet.publishedAt
            # is the upload time, not a public release time.  Only place it on the
            # calendar when YouTube exposes publishAt or the video is no longer private.
            calendar_at = scheduled_at or (published_at if privacy_status != "private" else None)
            rows.append({
                "id": video_id, "title": str(snippet.get("title") or ""), "published_at": published_at,
                "scheduled_at": scheduled_at, "calendar_at": calendar_at,
                "time_source": "scheduled" if scheduled_at else "published" if calendar_at else "",
                "publication_status": privacy_status,
                "views": views, "likes": int(stats.get("likeCount") or 0), "comments": int(stats.get("commentCount") or 0),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": str(snippet.get("thumbnails", {}).get("medium", {}).get("url") or snippet.get("thumbnails", {}).get("default", {}).get("url") or ""),
                "duration_seconds": _duration_seconds(str(item.get("contentDetails", {}).get("duration") or "")),
                "impressions": int(extra["videoThumbnailImpressions"]) if "videoThumbnailImpressions" in extra else None,
                "clicks": None, "ctr": extra.get("videoThumbnailImpressionsClickRate"),
                "watch_time_seconds": round(extra["estimatedMinutesWatched"] * 60) if "estimatedMinutesWatched" in extra else None,
                "average_view_duration_seconds": extra.get("averageViewDuration"),
                "estimated_revenue": revenue, "rpm": revenue / views * 1000 if revenue is not None and views else None,
                "subscribers_gained": int(extra["subscribersGained"]) if "subscribersGained" in extra else None,
                "content_type": {
                    "SHORTS": "shorts",
                    "VIDEO_ON_DEMAND": "videos",
                    "LIVE_STREAM": "live",
                }.get(str(extra.get("creatorContentType") or ""), "unknown"),
            })
        return rows
    token = tiktok_access_token(account) if account.platform == "tiktok" else resolve_account_secret(account, "access_token")
    if account.platform == "tiktok":
        response = httpx.post(f"{TIKTOK_API}/v2/video/list/", params={"fields": "id,title,video_description,create_time,view_count,like_count,comment_count,share_url,cover_image_url,duration"}, headers=bearer_headers(token), json={"max_count": min(limit, 20)}, timeout=30)
        _raise(response, "TikTok")
        return [{
            "id": str(item["id"]), "title": str(item.get("title") or item.get("video_description") or ""),
            "published_at": datetime.fromtimestamp(int(item.get("create_time") or 0)).isoformat() if item.get("create_time") else None,
            "scheduled_at": None,
            "calendar_at": datetime.fromtimestamp(int(item.get("create_time") or 0)).isoformat() if item.get("create_time") else None,
            "time_source": "published", "publication_status": "published",
            "views": int(item.get("view_count") or 0), "likes": int(item.get("like_count") or 0), "comments": int(item.get("comment_count") or 0),
            "url": str(item.get("share_url") or ""), "thumbnail_url": str(item.get("cover_image_url") or ""),
            "duration_seconds": int(item.get("duration") or 0) or None, "impressions": None, "clicks": None, "ctr": None,
            "watch_time_seconds": None, "average_view_duration_seconds": None, "estimated_revenue": None, "rpm": None, "subscribers_gained": None,
            "content_type": "unknown",
        } for item in response.json().get("data", {}).get("videos", [])]
    node = str(account.credentials_json.get("page_id" if account.platform == "facebook" else "ig_user_id") or account.platform_user_id)
    edge = "videos" if account.platform == "facebook" else "media"
    fields = "id,title,description,created_time,permalink_url,picture,views,likes.summary(true),comments.summary(true)" if account.platform == "facebook" else "id,caption,timestamp,permalink,thumbnail_url,media_url,like_count,comments_count,media_type"
    response = httpx.get(f"{META_GRAPH}/{graph_version(account)}/{node}/{edge}", params={"fields": fields, "limit": limit, "access_token": token}, timeout=30)
    _raise(response, "Meta")
    rows = []
    for item in response.json().get("data", []):
        published_at = item.get("timestamp") or item.get("created_time")
        rows.append({
            "id": str(item["id"]), "title": str(item.get("title") or item.get("caption") or item.get("description") or "")[:160],
            "published_at": published_at, "scheduled_at": None, "calendar_at": published_at,
            "time_source": "published", "publication_status": "published", "views": int(item.get("views") or 0),
            "likes": int(item.get("like_count") or item.get("likes", {}).get("summary", {}).get("total_count") or 0),
            "comments": int(item.get("comments_count") or item.get("comments", {}).get("summary", {}).get("total_count") or 0),
            "url": str(item.get("permalink") or item.get("permalink_url") or ""),
            "thumbnail_url": str(item.get("thumbnail_url") or item.get("picture") or item.get("media_url") or ""),
            "duration_seconds": None, "impressions": None, "clicks": None, "ctr": None, "watch_time_seconds": None, "average_view_duration_seconds": None,
            "estimated_revenue": None, "rpm": None, "subscribers_gained": None, "content_type": "unknown",
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


def publish_first_comment(account: Account, video_id: str, message: str) -> str:
    """Create a real top-level comment on a newly published platform video."""
    text = message.strip()
    if not text:
        return ""
    if account.platform == "youtube":
        response = httpx.post(
            f"{YOUTUBE_API}/commentThreads",
            params={"part": "snippet"},
            headers=bearer_headers(youtube_access_token(account)),
            json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}},
            timeout=30,
        )
        _raise(response, "YouTube 首条评论")
    elif account.platform in {"facebook", "instagram"}:
        response = httpx.post(
            f"{META_GRAPH}/{graph_version(account)}/{video_id}/comments",
            params={"access_token": resolve_account_secret(account, "access_token"), "message": text},
            timeout=30,
        )
        _raise(response, "Meta 首条评论")
    else:
        raise RuntimeError("TikTok 当前官方商业 API 不支持创建评论；首条评论不能伪造为发布成功")
    comment_id = str(response.json().get("id") or "")
    if not comment_id:
        raise RuntimeError("平台未返回评论 ID，首条评论未记录为成功")
    return comment_id
