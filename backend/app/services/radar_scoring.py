from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


FULL_TERMS = re.compile(r"\b(full(?:\s+movie|\s+series)?|complete(?:\s+series)?|all\s+episodes?|全集|完整版)\b", re.I)
EPISODE_TERMS = re.compile(r"(?:\b(?:ep|episode|part)\s*\d+\b|第\s*\d+\s*集)", re.I)
URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.I)
OFFICIAL_TERMS = re.compile(r"\b(official|official channel)\b|官方", re.I)
RANK_CHANGE_THRESHOLD = 3
GROWTH_ABSOLUTE_MIN = 1000
GROWTH_RATE_MIN = 0.20


@dataclass(frozen=True)
class RiskDecision:
    classification: str
    score: int
    reasons: list[str]


def _unapproved_domains(description: str, approved_domains: list[str]) -> list[str]:
    approved = tuple(item.lower().lstrip(".") for item in approved_domains)
    domains: list[str] = []
    for raw in URL_RE.findall(description or ""):
        host = (urlparse(raw.rstrip(".,);]}")).hostname or "").lower()
        if host and not any(host == item or host.endswith(f".{item}") for item in approved):
            domains.append(host)
    return list(dict.fromkeys(domains))


def classify_candidate(
    *,
    title: str,
    description: str,
    channel_name: str,
    duration_seconds: int,
    authorized: bool,
    relationship_type: str,
    approved_domains: list[str],
    same_channel_episode_count: int = 0,
) -> RiskDecision:
    if relationship_type in {"own_official", "own_creator"}:
        return RiskDecision("own", 0, ["发布者是我方账号"])
    if authorized:
        return RiskDecision("authorized", 0, ["当前剧目、地区和发布时间授权有效"])
    reasons: list[str] = []
    if duration_seconds >= 20 * 60 and FULL_TERMS.search(title or ""):
        reasons.extend(["视频时长超过20分钟", "标题含全集或完整版表达"])
        return RiskDecision("suspected_full_reupload", 95, reasons)
    domains = _unapproved_domains(description, approved_domains)
    if domains:
        return RiskDecision("suspected_external_redirect", 85, [f"描述含未认可外链：{', '.join(domains[:3])}"])
    if same_channel_episode_count >= 3 and EPISODE_TERMS.search(title or ""):
        return RiskDecision("suspected_episode_reupload", 80, [f"同一频道出现至少{same_channel_episode_count}条连续分集"])
    if OFFICIAL_TERMS.search(f"{channel_name} {title}"):
        return RiskDecision("suspected_impersonation", 70, ["未知或未授权账号使用官方身份表达"])
    return RiskDecision("unknown", 0, [])


def episode_like(title: str) -> bool:
    return bool(EPISODE_TERMS.search(title or ""))
