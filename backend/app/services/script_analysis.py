from __future__ import annotations

import json
import math
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
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
SENSITIVE_TERMS = {
    "暴力": ["杀", "打死", "砍", "枪", "血", "尸体", "绑架", "虐待", "暴力"],
    "色情": ["裸", "床戏", "性侵", "强奸", "色情", "胸部", "脱衣", "性行为"],
}


def analysis_file(folder: Path) -> Path:
    return folder / "factory_analysis.json"


def read_analysis(folder: Path) -> dict[str, Any] | None:
    target = analysis_file(folder)
    if not target.is_file():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def write_analysis(folder: Path, payload: dict[str, Any]) -> dict[str, Any]:
    target = analysis_file(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return payload


def queued_analysis(folder: Path, drama_id: int, title: str, episode_count: int) -> dict[str, Any]:
    return write_analysis(folder, {
        "status": "queued", "progress": 0, "current_step": "等待开始识别", "error_message": "",
        "drama_id": drama_id, "title": title, "episodes": [], "episode_count": episode_count,
        "total_duration": 0, "segment_count": 0, "high_energy_count": 0, "sensitive_count": 0,
        "sampled_frame_count": 0, "api_call_count": 0,
    })


def failed_analysis(folder: Path, drama_id: int, title: str, error: Exception) -> dict[str, Any]:
    previous = read_analysis(folder) or {}
    return write_analysis(folder, {
        **previous, "status": "failed", "progress": 0, "current_step": "识别失败",
        "error_message": str(error)[-2000:], "drama_id": drama_id, "title": title,
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


def _candidate_frames(raw: dict[str, Any], frames: list[Any]) -> list[str]:
    requested: set[int] = set()
    for value in raw.get("frame_indices", []) or []:
        try:
            requested.add(int(value))
        except (TypeError, ValueError):
            continue
    return [row.path.name for row in frames if row.index in requested][:4]


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
        start, end = bounds
        reasons = [str(value) for value in (raw.get("reasons") or []) if value]
        try:
            score = min(100.0, max(0.0, float(raw.get("score", 0))))
        except (TypeError, ValueError):
            score = 0.0
        high_energy.append({
            "start": start, "end": end, "text": _text_for_range(segments, start, end),
            "energy_score": round(score, 1), "energy_reasons": reasons, "high_energy": True,
            "sensitive": {}, "confidence": round(score / 100, 2), "review_status": "pending",
            "evidence": reasons, "frame_files": _candidate_frames(raw, frames), "source": source,
        })
    for raw in data.get("sensitive", []) or []:
        bounds = _candidate_range(raw, window_start, window_end, 2.0)
        if not bounds:
            continue
        start, end = bounds
        category = str(raw.get("category") or "其他")
        reasons = [str(value) for value in (raw.get("reasons") or []) if value]
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        sensitive.append({
            "start": start, "end": end, "text": _text_for_range(segments, start, end),
            "energy_score": 0.0, "energy_reasons": [], "high_energy": False,
            "sensitive": {category: reasons or ["模型结合脚本与画面识别"]},
            "confidence": round(confidence, 2), "review_status": "approved" if confidence >= 0.75 else "pending",
            "evidence": reasons, "frame_files": _candidate_frames(raw, frames), "source": source,
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
) -> dict[str, Any]:
    videos = episode_files(folder)
    if not videos:
        raise RuntimeError("本地剧目目录中没有可分析的视频")
    production_ai = model is None
    if production_ai:
        provider, provider_model = provider_name(settings)
    else:
        provider, provider_model = "test", "injected"
    if model is None:
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
        except Exception as exc:
            raise RuntimeError(f"本地语音识别模型加载失败：{exc}") from exc

    frame_dir = folder / "analysis_frames"
    if frame_dir.is_dir():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    active_words = sorted({*DEFAULT_ENERGY_WORDS, *[word for word in energy_words if word]})
    episode_results: list[dict[str, Any]] = []
    total_segments = total_high_energy = total_sensitive = 0
    total_duration = sampled_frame_count = api_call_count = 0
    window_seconds = max(120, int(getattr(settings, "factory_analysis_window_seconds", 600)))
    max_frames = max(4, min(20, int(getattr(settings, "factory_analysis_frames_per_window", 12))))

    for episode_index, video in enumerate(videos, start=1):
        progress = 5 + round((episode_index - 1) / max(1, len(videos)) * 85)
        write_analysis(folder, {
            "status": "processing", "progress": progress,
            "current_step": f"转写并抽帧 {episode_index}/{len(videos)} · {video.name}", "error_message": "",
            "drama_id": drama_id, "title": title, "provider": provider, "model": provider_model,
            "episodes": episode_results, "episode_count": len(videos), "total_duration": round(total_duration, 2),
            "segment_count": total_segments, "high_energy_count": total_high_energy, "sensitive_count": total_sensitive,
            "sampled_frame_count": sampled_frame_count, "api_call_count": api_call_count,
        })
        try:
            duration = media_duration(settings.ffprobe_binary, video)
            peaks = loudness_peaks(settings.ffmpeg_binary, video)
            transcript, _ = model.transcribe(str(video), vad_filter=True)
            segments = [row for segment in transcript if (row := _segment_row(segment, peaks, active_words))]
        except Exception as exc:
            raise RuntimeError(f"{video.name} 脚本拆解失败：{exc}") from exc

        episode_high: list[dict[str, Any]] = []
        episode_sensitive: list[dict[str, Any]] = []
        summaries: list[str] = []
        window_count = max(1, math.ceil(duration / window_seconds))
        for window_index in range(window_count):
            window_start = window_index * window_seconds
            window_end = min(duration, (window_index + 1) * window_seconds)
            window_segments = [row for row in segments if row["end"] >= window_start and row["start"] <= window_end]
            times = choose_frame_times(window_start, window_end, peaks, max_frames)
            frames = extract_frames(settings, video, frame_dir, episode_index, times)
            sampled_frame_count += len(frames)
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
            high, sensitive = _model_candidates(data, segments, frames, window_start, window_end, provider)
            episode_high.extend(high)
            episode_sensitive.extend(sensitive)
            if data.get("summary"):
                summaries.append(str(data["summary"]))

        episode_results.append({
            "episode": video.name, "duration": round(duration, 2), "segment_count": len(segments),
            "segments": segments, "high_energy": episode_high, "sensitive": episode_sensitive,
            "summary": " ".join(summaries),
        })
        total_duration += duration
        total_segments += len(segments)
        total_high_energy += len(episode_high)
        total_sensitive += len(episode_sensitive)

    result = {
        "status": "completed", "progress": 100, "current_step": "识别完成", "error_message": "",
        "drama_id": drama_id, "title": title, "source": f"local_whisper+ffmpeg+{provider}",
        "provider": provider, "model": provider_model, "generated_at": datetime.now(timezone.utc).isoformat(),
        "episode_count": len(episode_results), "total_duration": round(total_duration, 2),
        "segment_count": total_segments, "high_energy_count": total_high_energy,
        "sensitive_count": total_sensitive, "sampled_frame_count": sampled_frame_count,
        "api_call_count": api_call_count, "episodes": episode_results,
    }
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
    return write_analysis(folder, data)


class FactoryAnalysisPipeline:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._active: set[int] = set()

    def is_active(self, drama_id: int) -> bool:
        with self._guard:
            return drama_id in self._active

    def run(self, folder: Path, drama_id: int, title: str, settings: Settings, words: list[str]) -> None:
        with self._guard:
            if drama_id in self._active:
                return
            self._active.add(drama_id)
        try:
            analyze_drama(folder, drama_id, title, settings, words)
        except Exception as exc:
            failed_analysis(folder, drama_id, title, exc)
        finally:
            with self._guard:
                self._active.discard(drama_id)


factory_analysis_pipeline = FactoryAnalysisPipeline()
