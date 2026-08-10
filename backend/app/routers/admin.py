from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..database import get_session
from ..models import AppUser, CloudAsset, UsageEvent
from ..services.auth import get_current_user
from ..services.usage import record_usage


router = APIRouter(prefix="/api", tags=["用量统计"])


class TelemetryItem(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=120)
    feature: str = Field(min_length=1, max_length=100)
    success: bool = True
    duration_ms: int = Field(default=0, ge=0)
    details: dict = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    events: list[TelemetryItem] = Field(max_length=100)


@router.post("/telemetry/events")
def telemetry(payload: TelemetryBatch, user: AppUser = Depends(get_current_user)):
    accepted = 0
    for event in payload.events:
        accepted += int(record_usage(
            event.feature, user_id=user.id, event_kind="client_feature", success=event.success,
            duration_ms=event.duration_ms, client_event_id=event.client_event_id,
            details={**event.details, "source": "browser_outbox"},
        ))
    return {"accepted": accepted}


@router.get("/admin/analytics")
def analytics(days: int = 30, user: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if not user.is_developer:
        raise HTTPException(403, "仅开发者账号可访问")
    days = min(3650, max(1, days))
    since = datetime.utcnow() - timedelta(days=days)
    users = session.exec(select(AppUser).order_by(AppUser.created_at)).all()
    events = session.exec(select(UsageEvent).where(UsageEvent.created_at >= since).order_by(UsageEvent.created_at)).all()
    clouds = session.exec(select(CloudAsset)).all()
    user_map = {row.id: row for row in users}
    by_user: dict[int, dict] = {
        row.id: {
            "user_id": row.id, "email": row.email, "api_calls": 0, "model_calls": 0,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "feature_actions": 0, "failures": 0,
        }
        for row in users
    }
    by_feature: dict[str, dict] = {}
    daily: dict[str, dict] = defaultdict(lambda: {"api_calls": 0, "model_calls": 0, "tokens": 0, "success": 0, "failure": 0})
    feature_users: dict[str, set[int]] = defaultdict(set)
    for event in events:
        account = by_user.setdefault(event.user_id, {
            "user_id": event.user_id, "email": user_map.get(event.user_id).email if user_map.get(event.user_id) else "已删除用户",
            "api_calls": 0, "model_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "feature_actions": 0, "failures": 0,
        })
        account["api_calls"] += event.api_calls if event.event_kind == "api_request" else 0
        account["model_calls"] += event.api_calls if event.event_kind == "model_call" else 0
        account["input_tokens"] += event.input_tokens
        account["output_tokens"] += event.output_tokens
        account["total_tokens"] += event.total_tokens
        account["feature_actions"] += int(event.event_kind in {"api_request", "client_feature"})
        account["failures"] += int(not event.success)
        feature = by_feature.setdefault(event.feature, {
            "feature": event.feature, "uses": 0, "successes": 0, "failures": 0, "cache_hits": 0,
            "model_calls": 0, "tokens": 0, "active_users": 0, "usage_rate": 0.0, "success_rate": None, "hit_rate": None,
            "_cache_events": 0,
        })
        if event.event_kind in {"api_request", "client_feature"}:
            feature["uses"] += 1
            feature["successes"] += int(event.success)
            feature["failures"] += int(not event.success)
            feature_users[event.feature].add(event.user_id)
        if event.event_kind == "feature":
            feature["_cache_events"] += 1
            feature["cache_hits"] += int(event.cache_hit)
        if event.event_kind == "model_call":
            feature["model_calls"] += event.api_calls
            feature["tokens"] += event.total_tokens
        bucket = daily[event.created_at.date().isoformat()]
        bucket["api_calls"] += event.api_calls if event.event_kind == "api_request" else 0
        bucket["model_calls"] += event.api_calls if event.event_kind == "model_call" else 0
        bucket["tokens"] += event.total_tokens
        bucket["success" if event.success else "failure"] += 1
    registered = max(1, len(users))
    for name, row in by_feature.items():
        row["active_users"] = len(feature_users[name])
        row["usage_rate"] = round(row["active_users"] / registered * 100, 2)
        row["success_rate"] = round(row["successes"] / row["uses"] * 100, 2) if row["uses"] else None
        row["hit_rate"] = round(row["cache_hits"] / row["_cache_events"] * 100, 2) if row["_cache_events"] else None
        row.pop("_cache_events", None)
    return {
        "range_days": days,
        "totals": {
            "users": len(users), "active_users": len({event.user_id for event in events}),
            "api_calls": sum(row["api_calls"] for row in by_user.values()),
            "model_calls": sum(row["model_calls"] for row in by_user.values()),
            "tokens": sum(row["total_tokens"] for row in by_user.values()),
            "cloud_assets": len(clouds), "cloud_bytes": sum(row.size_bytes for row in clouds),
        },
        "users": list(by_user.values()),
        "features": sorted(by_feature.values(), key=lambda row: (row["uses"], row["tokens"]), reverse=True),
        "daily": [{"date": day, **daily[day]} for day in sorted(daily)],
        "definitions": {
            "usage_rate": "周期内使用过该功能的账号数 / 当前注册账号总数",
            "success_rate": "服务器实际收到的该功能成功事件 / 该功能全部事件",
            "hit_rate": "命中共享缓存并避免重复计算的事件 / 该功能全部事件",
            "tokens": "模型供应商响应中返回的真实 token 用量；供应商未返回时记 0，不进行估算",
            "local_events": "本地功能通过浏览器持久化 outbox 联网上报；未联网且尚未上报的事件不会提前计入",
        },
    }
