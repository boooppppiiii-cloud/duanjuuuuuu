from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from .drama_library import episode_files
from .hook_recommender import loudness_peaks, media_duration


DEFAULT_ENERGY_WORDS = ["打脸", "离婚", "背叛", "真相", "复仇", "后悔", "秘密", "竟然", "居然"]
SENSITIVE_TERMS = {
    "暴力": ["杀", "打死", "砍", "枪", "血", "尸体", "绑架", "强迫", "虐待", "暴力"],
    "色情": ["裸", "床戏", "性侵", "强奸", "色情", "胸部", "脱衣", "亲密行为"],
}


def analysis_file(folder: Path) -> Path:
    return folder / "factory_analysis.json"


def read_analysis(folder: Path) -> dict[str, Any] | None:
    target = analysis_file(folder)
    if not target.is_file():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _segment_row(segment: Any, peaks: list[tuple[float, float]], energy_words: list[str]) -> dict[str, Any] | None:
    text = str(segment.text or "").strip()
    if not text:
        return None
    start, end = float(segment.start), float(segment.end)
    energy_hits = sorted({word for word in energy_words if word and word in text})
    nearby_jumps = [jump for second, jump in peaks if start - 1 <= second <= end + 1]
    loudness_jump = max(nearby_jumps, default=0.0)
    sensitive = {
        category: sorted({word for word in words if word in text})
        for category, words in SENSITIVE_TERMS.items()
    }
    sensitive = {category: hits for category, hits in sensitive.items() if hits}
    reasons: list[str] = []
    if energy_hits:
        reasons.append("情绪词：" + "、".join(energy_hits))
    if loudness_jump > 2:
        reasons.append(f"音量突增 +{loudness_jump:.1f} LU")
    return {
        "start": round(start, 2),
        "end": round(end, 2),
        "text": text,
        "energy_score": round(len(energy_hits) * 4 + loudness_jump, 2),
        "energy_reasons": reasons,
        "high_energy": False,
        "sensitive": sensitive,
    }


def analyze_drama(folder: Path, drama_id: int, title: str, settings: Settings, energy_words: list[str], model: Any = None) -> dict[str, Any]:
    videos = episode_files(folder)
    if not videos:
        raise RuntimeError("本地剧目目录中没有可分析的视频")
    if model is None:
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
        except Exception as exc:
            raise RuntimeError(f"本地语音识别模型加载失败：{exc}") from exc

    active_words = sorted({*DEFAULT_ENERGY_WORDS, *[word for word in energy_words if word]})
    episode_results: list[dict[str, Any]] = []
    total_segments = total_high_energy = total_sensitive = 0
    total_duration = 0.0

    for video in videos:
        try:
            duration = media_duration(settings.ffprobe_binary, video)
            peaks = loudness_peaks(settings.ffmpeg_binary, video)
            transcript, _ = model.transcribe(str(video), vad_filter=True)
            segments = [row for segment in transcript if (row := _segment_row(segment, peaks, active_words))]
        except Exception as exc:
            raise RuntimeError(f"{video.name} 脚本拆解失败：{exc}") from exc

        ranked = sorted(
            (index for index, row in enumerate(segments) if row["energy_score"] > 0),
            key=lambda index: segments[index]["energy_score"],
            reverse=True,
        )[:5]
        for index in ranked:
            segments[index]["high_energy"] = True

        high_energy = [row for row in segments if row["high_energy"]]
        sensitive = [row for row in segments if row["sensitive"]]
        episode_results.append(
            {
                "episode": video.name,
                "duration": round(duration, 2),
                "segment_count": len(segments),
                "segments": segments,
                "high_energy": high_energy,
                "sensitive": sensitive,
            }
        )
        total_duration += duration
        total_segments += len(segments)
        total_high_energy += len(high_energy)
        total_sensitive += len(sensitive)

    result = {
        "status": "completed",
        "drama_id": drama_id,
        "title": title,
        "source": "local_whisper+ffmpeg",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "episode_count": len(episode_results),
        "total_duration": round(total_duration, 2),
        "segment_count": total_segments,
        "high_energy_count": total_high_energy,
        "sensitive_count": total_sensitive,
        "episodes": episode_results,
    }
    target = analysis_file(folder)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return result
