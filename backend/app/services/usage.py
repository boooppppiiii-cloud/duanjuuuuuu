from __future__ import annotations

from datetime import datetime
import re
import time
from typing import Any

from sqlmodel import Session, select

from ..database import engine
from ..models import UsageEvent
from .auth import current_user_id


def normalized_endpoint(path: str) -> str:
    value = re.sub(r"/\d+(?=/|$)", "/{id}", path)
    value = re.sub(r"/chunks/[^/]+$", "/chunks/{chunk}", value)
    return value


def feature_for(method: str, path: str) -> str:
    p = normalized_endpoint(path)
    rules = (
        ("/factory/{id}/analyze", "内容识别"),
        ("/factory/{id}/process", "内容加工"),
        ("/factory/assets/{id}/cloud", "上传云剧库"),
        ("/creative/titles", "标题文案生成"),
        ("/strategies/summarize", "运营策略提炼"),
        ("/publish/jobs", "发布任务"),
        ("/engagement/comments/analyze", "评论分析"),
        ("/engagement/sync", "评论同步"),
        ("/dramas/uploads/{id}/complete", "文件上传"),
        ("/meta-sfs/build", "Meta 文件夹生成"),
    )
    for needle, label in rules:
        if needle in p:
            return label
    return f"{method.upper()} {p.removeprefix('/api/')}"


def record_usage(
    feature: str,
    *,
    user_id: int | None = None,
    event_kind: str = "feature",
    endpoint: str = "",
    provider: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    api_calls: int = 0,
    success: bool = True,
    cache_hit: bool = False,
    duration_ms: int = 0,
    client_event_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    resolved_user_id = user_id or current_user_id()
    if not resolved_user_id:
        return False
    for attempt in range(3):
        try:
            with Session(engine) as session:
                if client_event_id and session.exec(select(UsageEvent).where(UsageEvent.client_event_id == client_event_id)).first():
                    return True
                total = max(int(total_tokens or 0), int(input_tokens or 0) + int(output_tokens or 0))
                session.add(UsageEvent(
                    user_id=resolved_user_id, event_kind=event_kind, feature=feature,
                    endpoint=normalized_endpoint(endpoint) if endpoint else "", provider=provider, model=model,
                    input_tokens=max(0, int(input_tokens or 0)), output_tokens=max(0, int(output_tokens or 0)),
                    total_tokens=max(0, total), api_calls=max(0, int(api_calls or 0)), success=success,
                    cache_hit=cache_hit, duration_ms=max(0, int(duration_ms or 0)),
                    client_event_id=client_event_id, details_json=details or {}, created_at=datetime.utcnow(),
                ))
                session.commit()
            return True
        except Exception:
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
    # Metering must never corrupt or falsely mark the user's production task as failed.
    return False


def record_model_usage(provider: str, model: str, response: Any, *, feature: str) -> None:
    input_tokens = output_tokens = total_tokens = 0
    if provider == "gemini":
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        total_tokens = int(getattr(usage, "total_token_count", 0) or 0)
    elif isinstance(response, dict):
        usage = response.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
    record_usage(
        feature, event_kind="model_call", provider=provider, model=model, api_calls=1,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        details={"token_source": "provider_response" if total_tokens or input_tokens or output_tokens else "provider_did_not_report"},
    )
