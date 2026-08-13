from __future__ import annotations

import json
import shutil
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import Settings, get_settings
from .drama_library import episode_files
from .factory_multimodal import (
    FactoryAIUnavailableError,
    analyze_window,
    choose_frame_times,
    extract_frames,
    provider_name,
)
from .hook_recommender import loudness_peaks, media_duration


DEFAULT_ENERGY_WORDS = ["打脸", "离婚", "背叛", "真相", "复仇", "后悔", "秘密", "竟然", "居然", "身份"]
ANALYSIS_VERSION = 5
MAX_HIGH_ENERGY_CANDIDATES = 10
MIN_HIGH_ENERGY_SECONDS = 15.0
MAX_HIGH_ENERGY_SECONDS = 30.0
RISK_SCORE_KEYS = ("body_focus", "action", "dialogue_context", "expression_audio", "scene_context")
SEXUAL_CATEGORIES = {"软色情", "低俗擦边", "暴露", "裸露", "性暗示", "色情", "性行为", "性暴力"}
SEXUAL_SIGNAL_TERMS = {
    "比基尼", "泳装", "情趣内衣", "内衣", "低领", "暴露", "裸露", "裸体", "裸上身", "赤裸",
    "床戏", "性爱", "软色情", "低俗擦边", "性暗示", "性行为", "性暴力", "裙底", "胸部", "臀部",
    "胯部", "大腿", "压床", "脱衣", "换衣", "湿身", "抚摸", "骨盆", "呻吟", "喘息", "挑逗",
}
SEXUAL_SCENE_PADDING_BEFORE = 5.0
SEXUAL_SCENE_PADDING_AFTER = 15.0
SEXUAL_SCENE_MERGE_GAP = 15.0
SENSITIVE_TERMS = {
    "暴力": ["杀", "打死", "砍", "枪", "血", "尸体", "绑架", "虐待", "暴力"],
    "色情": ["裸", "床戏", "性侵", "强奸", "色情", "胸部", "脱衣", "性行为"],
}


def analysis_file(folder: Path) -> Path:
    return folder / "factory_analysis.json"


def manual_sensitive_file(folder: Path) -> Path:
    return folder / "manual_sensitive.json"


def _reason_list(value: Any) -> list[str]:
    """Accept provider strings and repair historical arrays split into characters."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        rows = [str(item).strip() for item in value if item is not None and str(item).strip()]
        if len(rows) >= 4 and all(len(item) <= 1 for item in rows):
            text = "".join(rows).strip()
            return [text] if text else []
        return rows
    text = str(value).strip()
    return [text] if text else []


def _normalize_analysis_reasons(payload: dict[str, Any]) -> bool:
    changed = False
    for episode in payload.get("episodes", []) or []:
        if not isinstance(episode, dict):
            continue
        for collection in ("segments", "high_energy", "sensitive"):
            for row in episode.get(collection, []) or []:
                if not isinstance(row, dict):
                    continue
                for field in ("energy_reasons", "evidence"):
                    if field in row:
                        normalized = _reason_list(row.get(field))
                        if normalized != row.get(field):
                            row[field] = normalized
                            changed = True
                sensitive = row.get("sensitive")
                if isinstance(sensitive, dict):
                    for category, reasons in list(sensitive.items()):
                        normalized = _reason_list(reasons)
                        if normalized != reasons:
                            sensitive[category] = normalized
                            changed = True
    return changed


def _frame_time(path: Path) -> float | None:
    try:
        return int(path.stem.rsplit("_", 1)[1]) / 1000
    except (IndexError, TypeError, ValueError):
        return None


def _stored_edge_frames(folder: Path, episode_index: int, start: float, end: float) -> list[str]:
    candidates = [
        (second, path.name) for path in (folder / "analysis_frames").glob(f"E{episode_index:03d}_*.jpg")
        if (second := _frame_time(path)) is not None
    ]
    if not candidates:
        return []
    first = min(candidates, key=lambda item: abs(item[0] - start))
    last = min(candidates, key=lambda item: abs(item[0] - end))
    return list(dict.fromkeys([first[1], last[1]]))


def _normalize_evidence_frames(folder: Path, payload: dict[str, Any]) -> bool:
    changed = False
    for episode_index, episode in enumerate(payload.get("episodes", []) or [], start=1):
        if not isinstance(episode, dict):
            continue
        for collection in ("high_energy", "sensitive"):
            for row in episode.get(collection, []) or []:
                if not isinstance(row, dict):
                    continue
                frames = _stored_edge_frames(folder, episode_index, float(row.get("start", 0)), float(row.get("end", 0)))
                if frames and frames != row.get("frame_files"):
                    row["frame_files"] = frames
                    changed = True
    return changed


def _limit_high_energy(payload: dict[str, Any], maximum: int = MAX_HIGH_ENERGY_CANDIDATES) -> bool:
    episodes = [item for item in payload.get("episodes", []) or [] if isinstance(item, dict)]
    ranked = [row for episode in episodes for row in episode.get("high_energy", []) or [] if isinstance(row, dict)]
    keep = {id(row) for row in sorted(ranked, key=lambda row: float(row.get("energy_score", 0)), reverse=True)[:maximum]}
    changed = False
    for episode in episodes:
        rows = episode.get("high_energy", []) or []
        limited = [row for row in rows if id(row) in keep]
        if len(limited) != len(rows):
            episode["high_energy"] = limited
            changed = True
    count = sum(len(episode.get("high_energy", []) or []) for episode in episodes)
    if payload.get("high_energy_count") != count:
        payload["high_energy_count"] = count
        changed = True
    return changed


def _analysis_windows(duration: float, seconds: int, overlap: int) -> list[tuple[float, float]]:
    if duration <= 0:
        return [(0.0, 0.0)]
    seconds = max(30, seconds)
    overlap = max(0, min(seconds // 2, overlap))
    step = max(1, seconds - overlap)
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + seconds)
        windows.append((round(start, 2), round(end, 2)))
        if end >= duration:
            break
        start += step
    return windows


def _fit_high_energy_range(start: float, end: float, lower: float, upper: float) -> tuple[float, float]:
    lower, upper = float(lower), max(float(lower), float(upper))
    available = upper - lower
    if available <= 0:
        return round(lower, 2), round(upper, 2)
    start = max(lower, min(float(start), upper))
    end = max(start, min(float(end), upper))
    current = end - start
    target = min(available, max(MIN_HIGH_ENERGY_SECONDS, min(MAX_HIGH_ENERGY_SECONDS, current)))
    center = (start + end) / 2 if current > 0 else start
    fitted_start, fitted_end = center - target / 2, center + target / 2
    if fitted_start < lower:
        fitted_end += lower - fitted_start
        fitted_start = lower
    if fitted_end > upper:
        fitted_start -= fitted_end - upper
        fitted_end = upper
    return round(max(lower, fitted_start), 2), round(min(upper, fitted_end), 2)


def normalize_high_energy_range(start: float, end: float, duration: float) -> tuple[float, float]:
    """Keep the detected moment centered while enforcing a 15–30s usable hook."""
    return _fit_high_energy_range(start, end, 0.0, duration)


def _candidate_categories(row: dict[str, Any]) -> set[str]:
    value = row.get("sensitive")
    return {str(key) for key in value} if isinstance(value, dict) else set()


def _is_sexual_candidate(row: dict[str, Any]) -> bool:
    if _candidate_categories(row) & SEXUAL_CATEGORIES:
        return True
    sensitive = row.get("sensitive") if isinstance(row.get("sensitive"), dict) else {}
    evidence = " ".join([
        *_reason_list(row.get("evidence")),
        *[str(value) for values in sensitive.values() for value in _reason_list(values)],
    ]).casefold()
    if any(term.casefold() in evidence for term in SEXUAL_SIGNAL_TERMS):
        return True
    scores = row.get("risk_scores") if isinstance(row.get("risk_scores"), dict) else {}
    body = int(scores.get("body_focus") or 0)
    context = max(int(scores.get(key) or 0) for key in ("action", "expression_audio", "scene_context"))
    return body >= 35 and context >= 25


def _merge_text_values(left: Any, right: Any) -> list[str]:
    return list(dict.fromkeys([*_reason_list(left), *_reason_list(right)]))


def _manual_ranges(row: dict[str, Any]) -> list[dict[str, float]]:
    values = row.get("manual_ranges")
    ranges = [
        {"start": round(float(item.get("start", 0)), 2), "end": round(float(item.get("end", 0)), 2)}
        for item in values or [] if isinstance(item, dict) and float(item.get("end", 0)) > float(item.get("start", 0))
    ]
    if not ranges and row.get("source") == "manual":
        ranges = [{"start": round(float(row.get("start", 0)), 2), "end": round(float(row.get("end", 0)), 2)}]
    return ranges


def _merge_sensitive_candidates(
    rows: list[dict[str, Any]], duration: float, segments: list[dict[str, Any]], *, expand_sexual: bool = True,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for original in rows:
        row = deepcopy(original)
        manual_ranges = _manual_ranges(row)
        if manual_ranges:
            row["manual_ranges"] = manual_ranges
        if expand_sexual and _is_sexual_candidate(row):
            detected_start, detected_end = float(row.get("start", 0)), float(row.get("end", 0))
            row["detected_start"] = round(detected_start, 2)
            row["detected_end"] = round(detected_end, 2)
            row["boundary_padding_seconds"] = {
                "before": SEXUAL_SCENE_PADDING_BEFORE, "after": SEXUAL_SCENE_PADDING_AFTER,
            }
            row["start"] = round(max(0.0, detected_start - SEXUAL_SCENE_PADDING_BEFORE), 2)
            row["end"] = round(min(duration, detected_end + SEXUAL_SCENE_PADDING_AFTER), 2)
            # High-recall mode removes suspected sexual content unless a reviewer explicitly keeps it.
            row["review_status"] = "approved"
        prepared.append(row)
    prepared.sort(key=lambda row: (float(row.get("start", 0)), float(row.get("end", 0))))
    merged: list[dict[str, Any]] = []
    for row in prepared:
        if not merged:
            merged.append(row)
            continue
        previous = merged[-1]
        same_sexual_scene = _is_sexual_candidate(previous) and _is_sexual_candidate(row)
        gap = float(row.get("start", 0)) - float(previous.get("end", 0))
        # Any overlapping risk intervals describe one removal range even when
        # the model labels their sub-events differently (for example sexual
        # violence followed by violence). Sexual candidates also use a small
        # gap so one continuous scene is not fragmented by window boundaries.
        overlaps = gap <= 0
        if not (overlaps or (same_sexual_scene and gap <= SEXUAL_SCENE_MERGE_GAP)):
            merged.append(row)
            continue
        previous["start"] = min(float(previous.get("start", 0)), float(row.get("start", 0)))
        previous["end"] = max(float(previous.get("end", 0)), float(row.get("end", 0)))
        previous["detected_start"] = min(float(previous.get("detected_start", previous["start"])), float(row.get("detected_start", row["start"])))
        previous["detected_end"] = max(float(previous.get("detected_end", previous["end"])), float(row.get("detected_end", row["end"])))
        previous["confidence"] = max(float(previous.get("confidence", 0)), float(row.get("confidence", 0)))
        previous["overall_risk_score"] = max(int(previous.get("overall_risk_score", 0)), int(row.get("overall_risk_score", 0)))
        review_states = {str(previous.get("review_status") or "pending"), str(row.get("review_status") or "pending")}
        previous["review_status"] = "approved" if "approved" in review_states else "pending" if "pending" in review_states else "rejected"
        previous["evidence"] = _merge_text_values(previous.get("evidence"), row.get("evidence"))
        frames = list(dict.fromkeys([*(previous.get("frame_files") or []), *(row.get("frame_files") or [])]))
        previous["frame_files"] = frames if len(frames) <= 2 else [frames[0], frames[-1]]
        combined_manual = [*_manual_ranges(previous), *_manual_ranges(row)]
        if combined_manual:
            previous["manual_ranges"] = list({(item["start"], item["end"]): item for item in combined_manual}.values())
            previous["source"] = "manual"
        previous_scores = previous.setdefault("risk_scores", {})
        for key, value in (row.get("risk_scores") or {}).items():
            previous_scores[key] = max(int(previous_scores.get(key, 0)), int(value or 0))
        previous_sensitive = previous.setdefault("sensitive", {})
        for category, reasons in (row.get("sensitive") or {}).items():
            previous_sensitive[category] = _merge_text_values(previous_sensitive.get(category), reasons)
    for row in merged:
        row["start"] = round(float(row.get("start", 0)), 2)
        row["end"] = round(float(row.get("end", 0)), 2)
        row["text"] = _text_for_range(segments, row["start"], row["end"])
    return merged


def _consolidate_existing_sensitive(payload: dict[str, Any]) -> bool:
    """Merge overlapping stored ranges without padding them a second time."""
    changed = False
    episodes = [item for item in payload.get("episodes", []) or [] if isinstance(item, dict)]
    for episode in episodes:
        rows = [item for item in episode.get("sensitive", []) or [] if isinstance(item, dict)]
        consolidated = _merge_sensitive_candidates(
            rows, float(episode.get("duration", 0)), episode.get("segments", []) or [], expand_sexual=False,
        )
        if consolidated != rows:
            episode["sensitive"] = consolidated
            changed = True
    count = sum(len(episode.get("sensitive", []) or []) for episode in episodes)
    if payload.get("sensitive_count") != count:
        payload["sensitive_count"] = count
        changed = True
    return changed


def _normalize_sensitive_padding(payload: dict[str, Any]) -> bool:
    """Migrate early v4 rows from 4s/6s padding to the calibrated 5s/15s profile."""
    if int(payload.get("analysis_version", 0)) != ANALYSIS_VERSION:
        return False
    changed = False
    for episode in payload.get("episodes", []) or []:
        if not isinstance(episode, dict):
            continue
        duration = float(episode.get("duration", 0))
        for row in episode.get("sensitive", []) or []:
            if not isinstance(row, dict) or row.get("source") == "manual" or not _is_sexual_candidate(row):
                continue
            profile = row.get("boundary_padding_seconds")
            if isinstance(profile, dict) and "detected_start" in row and "detected_end" in row:
                detected_start = float(row["detected_start"])
                detected_end = float(row["detected_end"])
            elif profile is None:
                detected_start = float(row.get("start", 0)) + 4.0
                detected_end = max(detected_start, float(row.get("end", 0)) - 6.0)
            else:
                continue
            start = round(max(0.0, detected_start - SEXUAL_SCENE_PADDING_BEFORE), 2)
            end = round(min(duration or detected_end + SEXUAL_SCENE_PADDING_AFTER, detected_end + SEXUAL_SCENE_PADDING_AFTER), 2)
            expected_profile = {"before": SEXUAL_SCENE_PADDING_BEFORE, "after": SEXUAL_SCENE_PADDING_AFTER}
            if row.get("start") != start or row.get("end") != end or profile != expected_profile:
                row["start"], row["end"] = start, end
                row["detected_start"], row["detected_end"] = round(detected_start, 2), round(detected_end, 2)
                row["boundary_padding_seconds"] = expected_profile
                row["text"] = _text_for_range(episode.get("segments", []), start, end)
                changed = True
    return changed


def _dedupe_high_energy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: float(item.get("energy_score", 0)), reverse=True):
        start, end = float(row.get("start", 0)), float(row.get("end", 0))
        if any(start <= float(existing.get("end", 0)) and end >= float(existing.get("start", 0)) for existing in selected):
            continue
        selected.append(row)
    return sorted(selected, key=lambda item: float(item.get("start", 0)))


def _normalize_high_energy_candidates(payload: dict[str, Any]) -> bool:
    changed = False
    episodes = [item for item in payload.get("episodes", []) or [] if isinstance(item, dict)]
    for episode in episodes:
        duration = float(episode.get("duration", 0) or 0)
        rows = [item for item in episode.get("high_energy", []) or [] if isinstance(item, dict)]
        if duration > 0:
            for row in rows:
                start, end = normalize_high_energy_range(
                    float(row.get("start", 0)), float(row.get("end", 0)), duration,
                )
                if row.get("start") != start or row.get("end") != end:
                    row["start"], row["end"] = start, end
                    row["text"] = _text_for_range(episode.get("segments", []) or [], start, end)
                    changed = True
        deduped = _dedupe_high_energy(rows)
        if deduped != rows:
            episode["high_energy"] = deduped
            changed = True
    count = sum(len(episode.get("high_energy", []) or []) for episode in episodes)
    if payload.get("high_energy_count") != count:
        payload["high_energy_count"] = count
        changed = True
    return changed


def _read_manual_sensitive(folder: Path) -> list[dict[str, Any]]:
    path = manual_sensitive_file(folder)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _merge_manual_sensitive(folder: Path, payload: dict[str, Any]) -> bool:
    changed = False
    episodes = [item for item in payload.get("episodes", []) or [] if isinstance(item, dict)]
    by_name = {str(item.get("episode")): (index, item) for index, item in enumerate(episodes, start=1)}
    for manual in _read_manual_sensitive(folder):
        match = by_name.get(str(manual.get("episode")))
        if not match:
            continue
        episode_index, episode = match
        start, end = float(manual.get("start", 0)), float(manual.get("end", 0))
        rows = episode.setdefault("sensitive", [])
        existing = next((
            row for row in rows
            if any(abs(item["start"] - start) < .11 and abs(item["end"] - end) < .11 for item in _manual_ranges(row))
        ), None)
        note = str(manual.get("note") or "人工确认色情内容，必须剪除")
        row = {
            "start": start, "end": end, "text": _text_for_range(episode.get("segments", []), start, end),
            "energy_score": 0.0, "energy_reasons": [], "high_energy": False,
            "sensitive": {str(manual.get("category") or "色情"): [note]},
            "confidence": 1.0, "overall_risk_score": 100,
            "risk_scores": {key: 100 for key in RISK_SCORE_KEYS},
            "review_status": "approved", "evidence": [note],
            "frame_files": _stored_edge_frames(folder, episode_index, start, end), "source": "manual",
            "manual_ranges": [{"start": round(start, 2), "end": round(end, 2)}],
        }
        if existing is None:
            rows.append(row)
            changed = True
        else:
            before = deepcopy(existing)
            existing["source"] = "manual"
            existing["review_status"] = "approved"
            existing["confidence"] = max(1.0, float(existing.get("confidence", 0)))
            existing["overall_risk_score"] = max(100, int(existing.get("overall_risk_score", 0)))
            existing["manual_ranges"] = list({
                (item["start"], item["end"]): item
                for item in [*_manual_ranges(existing), {"start": round(start, 2), "end": round(end, 2)}]
            }.values())
            existing["evidence"] = _merge_text_values(existing.get("evidence"), [note])
            existing_scores = existing.setdefault("risk_scores", {})
            for key in RISK_SCORE_KEYS:
                existing_scores[key] = max(100, int(existing_scores.get(key, 0)))
            existing_sensitive = existing.setdefault("sensitive", {})
            category = str(manual.get("category") or "色情")
            existing_sensitive[category] = _merge_text_values(existing_sensitive.get(category), [note])
            changed = changed or existing != before
    count = sum(len(episode.get("sensitive", []) or []) for episode in episodes)
    if payload.get("sensitive_count") != count:
        payload["sensitive_count"] = count
        changed = True
    return changed


def read_analysis(folder: Path) -> dict[str, Any] | None:
    target = analysis_file(folder)
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    repaired = any((
        _normalize_analysis_reasons(payload),
        _normalize_sensitive_padding(payload),
        _normalize_high_energy_candidates(payload),
        _normalize_evidence_frames(folder, payload),
        _limit_high_energy(payload),
        _merge_manual_sensitive(folder, payload),
        _consolidate_existing_sensitive(payload),
    ))
    if repaired and payload.get("status") == "completed":
        write_analysis(folder, payload)
    return payload


def write_analysis(folder: Path, payload: dict[str, Any]) -> dict[str, Any]:
    target = analysis_file(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return payload


def add_manual_sensitive(folder: Path, episode_name: str, start: float, end: float, category: str, note: str) -> dict[str, Any]:
    analysis = read_analysis(folder)
    if not analysis or analysis.get("status") != "completed":
        raise ValueError("请先完成内容识别")
    episode = next((item for item in analysis.get("episodes", []) if item.get("episode") == episode_name), None)
    if not episode:
        raise ValueError("未找到指定剧集")
    duration = float(episode.get("duration", 0))
    start = round(max(0.0, start), 2)
    end = round(min(duration or end, end), 2)
    if end <= start:
        raise ValueError("必剪片段结束时间必须晚于开始时间")
    rows = _read_manual_sensitive(folder)
    item = {"episode": episode_name, "start": start, "end": end, "category": category or "色情", "note": note or "人工确认色情内容，必须剪除"}
    existing = next((row for row in rows if row.get("episode") == episode_name and abs(float(row.get("start", 0)) - start) < .11 and abs(float(row.get("end", 0)) - end) < .11), None)
    if existing is None:
        rows.append(item)
    else:
        existing.clear(); existing.update(item)
    path = manual_sensitive_file(folder)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _merge_manual_sensitive(folder, analysis)
    _consolidate_existing_sensitive(analysis)
    return write_analysis(folder, analysis)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def queued_analysis(folder: Path, drama_id: int, title: str, episode_count: int) -> dict[str, Any]:
    return write_analysis(folder, {
        "status": "queued", "progress": 0, "current_step": "等待开始识别", "error_message": "",
        "drama_id": drama_id, "title": title, "episodes": [], "episode_count": episode_count,
        "total_duration": 0, "segment_count": 0, "high_energy_count": 0, "sensitive_count": 0,
        "sampled_frame_count": 0, "api_call_count": 0, "started_at": utc_timestamp(),
        "updated_at": utc_timestamp(), "resume_count": 0, "analysis_version": ANALYSIS_VERSION,
    })


def queued_resume_analysis(folder: Path, drama_id: int, title: str, episode_count: int) -> dict[str, Any]:
    previous = read_analysis(folder) or {}
    completed = len(previous.get("episodes", []))
    return write_analysis(folder, {
        **previous, "status": "queued", "current_step": f"准备从 {completed}/{episode_count} 集继续",
        "error_message": "", "drama_id": drama_id, "title": title, "episode_count": episode_count,
        "updated_at": utc_timestamp(),
    })


def failed_analysis(folder: Path, drama_id: int, title: str, error: Exception) -> dict[str, Any]:
    previous = read_analysis(folder) or {}
    return write_analysis(folder, {
        **previous, "status": "failed", "current_step": "识别中断，可从已完成剧集继续",
        "error_message": str(error)[-2000:], "drama_id": drama_id, "title": title, "updated_at": utc_timestamp(),
    })


def _segment_row(segment: Any, peaks: list[tuple[float, float]], energy_words: list[str]) -> dict[str, Any] | None:
    text = str(segment.text or "").strip()
    if not text:
        return None
    start, end = float(segment.start), float(segment.end)
    energy_hits = sorted({word for word in energy_words if word and word in text})
    nearby_jumps = [jump for second, jump in peaks if start - 1 <= second <= end + 1]
    loudness_jump = max(nearby_jumps, default=0.0)
    reasons: list[str] = []
    if energy_hits:
        reasons.append("情绪词：" + "、".join(energy_hits))
    if loudness_jump > 2:
        reasons.append(f"音量突增 +{loudness_jump:.1f} LU")
    return {
        "start": round(start, 2), "end": round(end, 2), "text": text,
        "energy_score": round(len(energy_hits) * 4 + loudness_jump, 2),
        "energy_reasons": reasons, "high_energy": False, "sensitive": {},
        "confidence": 0.0, "review_status": "not_applicable", "evidence": [], "frame_files": [],
    }


def _text_for_range(segments: list[dict[str, Any]], start: float, end: float) -> str:
    rows = [row["text"] for row in segments if float(row["end"]) >= start and float(row["start"]) <= end]
    return " ".join(rows)[:600]


def _candidate_range(raw: dict[str, Any], start_bound: float, end_bound: float, default_seconds: float = 3.0) -> tuple[float, float] | None:
    try:
        start = max(start_bound, float(raw.get("start", start_bound)))
        end = min(end_bound, float(raw.get("end", start + default_seconds)))
    except (TypeError, ValueError):
        return None
    if end <= start + 0.2:
        end = min(end_bound, start + default_seconds)
    return (round(start, 2), round(end, 2)) if end > start + 0.2 else None


def _candidate_frames(frames: list[Any], start: float, end: float) -> list[str]:
    if not frames:
        return []
    first = min(frames, key=lambda row: abs(float(row.second) - start))
    last = min(frames, key=lambda row: abs(float(row.second) - end))
    return list(dict.fromkeys([first.path.name, last.path.name]))


def _model_candidates(
    data: dict[str, Any], segments: list[dict[str, Any]], frames: list[Any],
    window_start: float, window_end: float, source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    high_energy: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    for raw in data.get("high_energy", []) or []:
        bounds = _candidate_range(raw, window_start, window_end)
        if not bounds:
            continue
        start, end = _fit_high_energy_range(bounds[0], bounds[1], window_start, window_end)
        reasons = _reason_list(raw.get("reasons"))
        try:
            score = min(100.0, max(0.0, float(raw.get("score", 0))))
        except (TypeError, ValueError):
            score = 0.0
        high_energy.append({
            "start": start, "end": end, "text": _text_for_range(segments, start, end),
            "energy_score": round(score, 1), "energy_reasons": reasons, "high_energy": True,
            "sensitive": {}, "confidence": round(score / 100, 2), "review_status": "pending",
            "evidence": reasons, "frame_files": _candidate_frames(frames, start, end), "source": source,
        })
    for raw in data.get("sensitive", []) or []:
        bounds = _candidate_range(raw, window_start, window_end, 2.0)
        if not bounds:
            continue
        start, end = bounds
        category = str(raw.get("category") or "其他")
        reasons = _reason_list(raw.get("reasons"))
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        risk_scores: dict[str, int] = {}
        raw_scores = raw.get("risk_scores") if isinstance(raw.get("risk_scores"), dict) else {}
        for key in RISK_SCORE_KEYS:
            try:
                risk_scores[key] = round(min(100.0, max(0.0, float(raw_scores.get(key, 0)))))
            except (TypeError, ValueError):
                risk_scores[key] = 0
        try:
            overall_risk_score = round(min(100.0, max(0.0, float(raw.get("overall_risk_score", 0)))))
        except (TypeError, ValueError):
            overall_risk_score = 0
        if not overall_risk_score and any(risk_scores.values()):
            overall_risk_score = round(max(risk_scores.values()))
        probe = {"sensitive": {category: reasons}, "evidence": reasons, "risk_scores": risk_scores}
        sexual_signal = _is_sexual_candidate(probe)
        threshold = 10 if sexual_signal else 30
        if "overall_risk_score" in raw and overall_risk_score < threshold:
            continue
        confidence = max(confidence, overall_risk_score / 100)
        sensitive.append({
            "start": start, "end": end, "text": _text_for_range(segments, start, end),
            "energy_score": 0.0, "energy_reasons": [], "high_energy": False,
            "sensitive": {category: reasons or ["模型结合脚本与画面识别"]},
            "confidence": round(confidence, 2),
            "overall_risk_score": overall_risk_score,
            "risk_scores": risk_scores,
            "review_status": "approved" if sexual_signal or overall_risk_score >= 60 or confidence >= 0.75 else "pending",
            "evidence": reasons, "frame_files": _candidate_frames(frames, start, end), "source": source,
        })
    return high_energy, sensitive


def _local_test_result(segments: list[dict[str, Any]], window_start: float, window_end: float) -> dict[str, Any]:
    """Compatibility path for injected test transcribers; production always requires a real multimodal provider."""
    high = sorted((row for row in segments if row["energy_score"] > 0), key=lambda row: row["energy_score"], reverse=True)[:5]
    sensitive = []
    for row in segments:
        hits = {category: [word for word in words if word in row["text"]] for category, words in SENSITIVE_TERMS.items()}
        for category, words in hits.items():
            if words:
                sensitive.append({"start": row["start"], "end": row["end"], "category": category, "confidence": .9, "reasons": words, "frame_indices": []})
    return {
        "summary": "测试转写信号", "sensitive": sensitive,
        "high_energy": [{"start": row["start"], "end": row["end"], "score": min(100, row["energy_score"] * 10), "reasons": row["energy_reasons"], "frame_indices": []} for row in high],
    }


def analyze_drama(
    folder: Path,
    drama_id: int,
    title: str,
    settings: Settings,
    energy_words: list[str],
    model: Any = None,
    ai_analyzer: Callable[..., Any] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    videos = episode_files(folder)
    if not videos:
        raise RuntimeError("本地剧目目录中没有可分析的视频")
    production_ai = model is None and ai_analyzer is None
    if production_ai:
        provider, provider_model = provider_name(settings)
    elif ai_analyzer is not None:
        # Injected speech + vision analyzers form a local test pipeline. The
        # production proxy does not inject a speech model and keeps its managed
        # provider label for usage tracking.
        provider, provider_model = (
            ("test", "injected") if model is not None else ("server_proxy", "server_managed")
        )
    else:
        provider, provider_model = "test", "injected"
    previous = read_analysis(folder) if resume else None
    if previous and int(previous.get("analysis_version", 0)) != ANALYSIS_VERSION:
        previous = None
        resume = False
    started_at = str((previous or {}).get("started_at") or utc_timestamp())
    resume_count = int((previous or {}).get("resume_count", 0)) + int(resume)
    if model is None:
        completed_before_load = len((previous or {}).get("episodes", []))
        write_analysis(folder, {
            **(previous or {}),
            "status": "processing",
            "progress": max(1, int((previous or {}).get("progress", 1))),
            "current_step": "正在加载本地语音识别模型（首次运行需下载，后续自动复用）",
            "error_message": "",
            "drama_id": drama_id,
            "title": title,
            "provider": provider,
            "model": provider_model,
            "episode_count": len(videos),
            "completed_episode_count": completed_before_load,
            "started_at": started_at,
            "updated_at": utc_timestamp(),
            "resume_count": resume_count,
            "analysis_version": ANALYSIS_VERSION,
        })
        try:
            from faster_whisper import WhisperModel

            cache_dir = Path(getattr(settings, "whisper_cache_dir", "backend/data/whisper"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            model = WhisperModel(
                settings.whisper_model, device=settings.whisper_device,
                compute_type=settings.whisper_compute_type, download_root=str(cache_dir),
            )
        except Exception as exc:
            raise RuntimeError(f"本地语音识别模型加载失败：{exc}") from exc

    video_names = {video.name for video in videos}
    completed_by_name = {
        str(item.get("episode")): item for item in (previous or {}).get("episodes", [])
        if isinstance(item, dict) and item.get("episode") in video_names
    }
    frame_dir = folder / "analysis_frames"
    if frame_dir.is_dir() and not resume:
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    active_words = sorted({*DEFAULT_ENERGY_WORDS, *[word for word in energy_words if word]})
    episode_results: list[dict[str, Any]] = list(completed_by_name.values())
    total_segments = sum(len(item.get("segments", [])) for item in episode_results)
    total_high_energy = sum(len(item.get("high_energy", [])) for item in episode_results)
    total_sensitive = sum(len(item.get("sensitive", [])) for item in episode_results)
    total_duration = sum(float(item.get("duration", 0)) for item in episode_results)
    sampled_frame_count = int((previous or {}).get("sampled_frame_count", 0)) if resume else 0
    api_call_count = int((previous or {}).get("api_call_count", 0)) if resume else 0
    window_seconds = max(30, int(getattr(settings, "factory_analysis_window_seconds", 60)))
    window_overlap = max(0, int(getattr(settings, "factory_analysis_window_overlap_seconds", 15)))
    max_frames = max(8, min(48, int(getattr(settings, "factory_analysis_frames_per_window", 36))))
    beam_size = max(1, min(5, int(getattr(settings, "factory_whisper_beam_size", 1))))
    video_order = {video.name: index for index, video in enumerate(videos)}

    def ordered_results() -> list[dict[str, Any]]:
        return sorted(episode_results, key=lambda item: video_order.get(str(item.get("episode")), len(videos)))

    def checkpoint(progress: float, step: str) -> dict[str, Any]:
        return write_analysis(folder, {
            **(previous or {}), "status": "processing", "progress": min(99, max(1, round(progress))),
            "current_step": step, "error_message": "", "drama_id": drama_id, "title": title,
            "source": f"local_whisper+ffmpeg+{provider}", "provider": provider, "model": provider_model,
            "episodes": ordered_results(), "episode_count": len(videos), "source_files": [video.name for video in videos],
            "total_duration": round(total_duration, 2), "segment_count": total_segments,
            "high_energy_count": total_high_energy, "sensitive_count": total_sensitive,
            "sampled_frame_count": sampled_frame_count, "api_call_count": api_call_count,
            "started_at": started_at, "updated_at": utc_timestamp(), "resume_count": resume_count,
            "analysis_version": ANALYSIS_VERSION,
        })

    if resume:
        checkpoint(5 + len(completed_by_name) / max(1, len(videos)) * 90, f"已恢复 {len(completed_by_name)}/{len(videos)} 集，继续识别")

    for episode_index, video in enumerate(videos, start=1):
        if video.name in completed_by_name:
            continue
        completed_count = len(completed_by_name)
        episode_base = 5 + completed_count / max(1, len(videos)) * 90
        episode_share = 90 / max(1, len(videos))
        checkpoint(episode_base, f"本地转写 {completed_count + 1}/{len(videos)} · {video.name}")
        try:
            duration = media_duration(settings.ffprobe_binary, video)
            peaks = loudness_peaks(settings.ffmpeg_binary, video)
            try:
                transcript, _ = model.transcribe(
                    str(video), vad_filter=True, beam_size=beam_size, condition_on_previous_text=False,
                )
            except TypeError:
                transcript, _ = model.transcribe(str(video), vad_filter=True)
            segments = [row for segment in transcript if (row := _segment_row(segment, peaks, active_words))]
        except Exception as exc:
            raise RuntimeError(f"{video.name} 脚本拆解失败：{exc}") from exc
        checkpoint(episode_base + episode_share * .42, f"转写完成，准备抽帧 · {video.name}")

        episode_high: list[dict[str, Any]] = []
        episode_sensitive: list[dict[str, Any]] = []
        summaries: list[str] = []
        episode_sampled_frames = episode_api_calls = 0
        windows = _analysis_windows(duration, window_seconds, window_overlap)
        window_count = len(windows)
        for window_index, (window_start, window_end) in enumerate(windows):
            window_segments = [row for row in segments if row["end"] >= window_start and row["start"] <= window_end]
            checkpoint(
                episode_base + episode_share * (.42 + .5 * window_index / window_count),
                f"抽取证据帧 {completed_count + 1}/{len(videos)} · 窗口 {window_index + 1}/{window_count}",
            )
            times = choose_frame_times(window_start, window_end, peaks, max_frames)
            frames = extract_frames(settings, video, frame_dir, episode_index, times)
            sampled_frame_count += len(frames)
            episode_sampled_frames += len(frames)
            checkpoint(
                episode_base + episode_share * (.48 + .44 * window_index / window_count),
                f"AI 审查 {completed_count + 1}/{len(videos)} · 窗口 {window_index + 1}/{window_count}",
            )
            if ai_analyzer:
                raw = ai_analyzer(video.name, window_start, window_end, window_segments, frames)
                if isinstance(raw, tuple):
                    data, provider, provider_model = raw
                else:
                    data = raw
            elif production_ai:
                data, provider, provider_model = analyze_window(settings, video.name, window_start, window_end, window_segments, frames)
            else:
                data = _local_test_result(window_segments, window_start, window_end)
            api_call_count += int(production_ai or ai_analyzer is not None)
            episode_api_calls += int(production_ai or ai_analyzer is not None)
            high, sensitive = _model_candidates(data, segments, frames, window_start, window_end, provider)
            episode_high.extend(high)
            episode_sensitive.extend(sensitive)
            if data.get("summary"):
                summaries.append(str(data["summary"]))

        episode_high = _dedupe_high_energy(episode_high)
        episode_sensitive = _merge_sensitive_candidates(episode_sensitive, duration, segments)

        episode_results.append({
            "episode": video.name, "duration": round(duration, 2), "segment_count": len(segments),
            "segments": segments, "high_energy": episode_high, "sensitive": episode_sensitive,
            "summary": " ".join(summaries), "sampled_frame_count": episode_sampled_frames,
            "api_call_count": episode_api_calls,
        })
        completed_by_name[video.name] = episode_results[-1]
        total_duration += duration
        total_segments += len(segments)
        total_high_energy += len(episode_high)
        total_sensitive += len(episode_sensitive)
        checkpoint(5 + len(completed_by_name) / max(1, len(videos)) * 90, f"已完成 {len(completed_by_name)}/{len(videos)} 集")

    result = {
        "status": "completed", "progress": 100, "current_step": "识别完成", "error_message": "",
        "drama_id": drama_id, "title": title, "source": f"local_whisper+ffmpeg+{provider}",
        "provider": provider, "model": provider_model, "generated_at": utc_timestamp(),
        "episode_count": len(episode_results), "source_files": [video.name for video in videos],
        "total_duration": round(total_duration, 2),
        "segment_count": total_segments, "high_energy_count": total_high_energy,
        "sensitive_count": total_sensitive, "sampled_frame_count": sampled_frame_count,
        "api_call_count": api_call_count, "episodes": ordered_results(), "started_at": started_at,
        "updated_at": utc_timestamp(), "resume_count": resume_count,
        "analysis_version": ANALYSIS_VERSION,
    }
    _normalize_high_energy_candidates(result)
    _limit_high_energy(result)
    _merge_manual_sensitive(folder, result)
    return write_analysis(folder, result)


def update_review(
    folder: Path, episode_name: str, kind: str, start: float, end: float,
    decision: str, new_start: float | None = None, new_end: float | None = None,
) -> dict[str, Any]:
    data = read_analysis(folder)
    if not data or data.get("status") != "completed":
        raise ValueError("请先完成内容识别")
    key = "high_energy" if kind == "high_energy" else "sensitive"
    target: dict[str, Any] | None = None
    for episode in data.get("episodes", []):
        if episode.get("episode") != episode_name:
            continue
        for row in episode.get(key, []):
            if abs(float(row.get("start", 0)) - start) < .11 and abs(float(row.get("end", 0)) - end) < .11:
                target = row
                break
    if target is None:
        raise ValueError("未找到待复核片段")
    if new_start is not None:
        target["start"] = round(max(0.0, new_start), 2)
    if new_end is not None:
        target["end"] = round(max(float(target["start"]) + .2, new_end), 2)
    target["review_status"] = decision
    if kind == "sensitive":
        _consolidate_existing_sensitive(data)
    return write_analysis(folder, data)


class FactoryAnalysisPipeline:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._active: set[int] = set()

    def is_active(self, drama_id: int) -> bool:
        with self._guard:
            return drama_id in self._active

    def run(self, folder: Path, drama_id: int, title: str, settings: Settings, words: list[str], resume: bool = False) -> None:
        self.run_with_analyzer(folder, drama_id, title, settings, words, resume=resume)

    def run_with_analyzer(
        self, folder: Path, drama_id: int, title: str, settings: Settings, words: list[str],
        *, resume: bool = False, ai_analyzer: Callable[..., Any] | None = None,
    ) -> None:
        with self._guard:
            if drama_id in self._active:
                return
            self._active.add(drama_id)
        try:
            analyze_drama(folder, drama_id, title, settings, words, ai_analyzer=ai_analyzer, resume=resume)
        except Exception as exc:
            failed_analysis(folder, drama_id, title, exc)
        finally:
            with self._guard:
                self._active.discard(drama_id)


factory_analysis_pipeline = FactoryAnalysisPipeline()


def resume_factory_analyses() -> int:
    """Continue interrupted analyses after a backend restart without redoing completed episodes."""
    from sqlmodel import Session, select

    from ..database import engine
    from ..models import Drama, EmotionWord

    settings = get_settings()
    try:
        provider_name(settings)
    except FactoryAIUnavailableError:
        return 0
    with Session(engine) as session:
        dramas = list(session.exec(select(Drama)).all())
        words = [item.word for item in session.exec(select(EmotionWord).where(EmotionWord.enabled == True)).all()]  # noqa: E712
    resumed = 0
    for drama in dramas:
        folder = Path(drama.file_dir)
        data = read_analysis(folder)
        if not data or data.get("status") not in {"queued", "processing"}:
            continue
        threading.Thread(
            target=factory_analysis_pipeline.run,
            args=(folder, drama.id, drama.title, settings, words),
            kwargs={"resume": True},
            name=f"factory-analysis-recovery-{drama.id}",
            daemon=True,
        ).start()
        resumed += 1
    return resumed
