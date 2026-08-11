import json
import math
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations, islice
from pathlib import Path
from typing import Callable

from sqlmodel import Session, select

from .. import database
from ..config import get_settings
from ..models import Clip, Drama, FactoryJob, GeneratedAsset, HookAsset
from .clipper import MediaCommandError, run_command
from .drama_library import episode_files, read_highlights
from .script_analysis import normalize_high_energy_range


@dataclass(frozen=True)
class TimelinePart:
    path: Path
    episode: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class MetaEpisodePart:
    sequence: int
    parts: tuple[TimelinePart, ...]
    source_episodes: tuple[int, ...]

    @property
    def duration(self) -> float:
        return sum(part.duration for part in self.parts)


@dataclass
class _MetaEpisodeDraft:
    parts: list[TimelinePart]

    @property
    def duration(self) -> float:
        return sum(part.duration for part in self.parts)


PROFILES = {
    "balanced": {"crf": "23", "preset": "veryfast", "audio": "128k"},
    "small": {"crf": "28", "preset": "fast", "audio": "96k"},
    "meta": {"preset": "veryfast", "audio": "192k"},
}


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def hook_clip_range(start: float, end: float, media_duration: float) -> tuple[float, float]:
    """Use the candidate's own duration; only repair legacy ranges outside 15–30s."""
    return normalize_high_energy_range(start, end, media_duration)


def probe_media(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            "format=format_name,duration,size,bit_rate:stream=codec_type,codec_name,width,height,channels,bit_rate",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise MediaCommandError(result.stderr[-1500:] or f"无法读取视频：{path.name}")
    data = json.loads(result.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise MediaCommandError(f"视频时长无效：{path.name}")
    streams = data.get("streams") or []
    video = next((row for row in streams if row.get("codec_type") == "video"), {})
    audio = next((row for row in streams if row.get("codec_type") == "audio"), {})
    media_format = data.get("format") or {}
    return {
        "duration": duration,
        "size": int(media_format.get("size") or path.stat().st_size),
        "format": str(media_format.get("format_name") or "").lower(),
        "has_audio": bool(audio),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or "").lower(),
        "video_bitrate": int(video.get("bit_rate") or media_format.get("bit_rate") or 0),
        "audio_codec": str(audio.get("codec_name") or "").lower(),
        "audio_channels": int(audio.get("channels") or 0),
    }


def meta_video_is_compliant(info: dict) -> bool:
    return (
        "mp4" in str(info.get("format") or "")
        and info.get("video_codec") == "h264"
        and int(info.get("width") or 0) == 1080
        and int(info.get("height") or 0) == 1920
        and int(info.get("video_bitrate") or 0) >= 2_500_000
        and info.get("audio_codec") == "aac"
        and int(info.get("audio_channels") or 0) == 2
        and 60 <= float(info.get("duration") or 0) <= 180
        and int(info.get("size") or 0) <= 2 * 1024**3
    )


def merge_ranges(ranges: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    normalized = sorted((max(0.0, start), min(duration, end)) for start, end in ranges if end > start)
    merged: list[list[float]] = []
    for start, end in normalized:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(row[0], row[1]) for row in merged]


def safe_ranges(duration: float, blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cursor = 0.0
    safe: list[tuple[float, float]] = []
    for start, end in merge_ranges(blocked, duration):
        if start > cursor + 0.08:
            safe.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.08:
        safe.append((cursor, duration))
    return safe


def balanced_lengths(total: float, maximum: float) -> list[float]:
    if total <= 0 or maximum <= 0:
        return []
    count = max(1, math.ceil(total / maximum))
    each = total / count
    values = [each] * count
    values[-1] = total - sum(values[:-1])
    return values


def _split_meta_draft(draft: _MetaEpisodeDraft, duration: float) -> tuple[_MetaEpisodeDraft, _MetaEpisodeDraft]:
    total = draft.duration
    left_parts = slice_timeline(draft.parts, 0, duration)
    right_parts = slice_timeline(draft.parts, duration, max(0.0, total - duration))
    return (
        _MetaEpisodeDraft(left_parts),
        _MetaEpisodeDraft(right_parts),
    )


def build_meta_episode_plan(
    source_info: list[tuple[Path, float]],
    maximum: float,
    minimum: float = 60.0,
    operations: list[str] | None = None,
) -> list[MetaEpisodePart]:
    """Build globally numbered Meta episodes and guarantee every output is 60–180 seconds."""
    if maximum < minimum:
        raise ValueError("Meta 单集最大时长不能小于最小时长")

    drafts: list[_MetaEpisodeDraft] = []
    episode_by_name: dict[str, int] = {}
    for episode_index, (source, duration) in enumerate(source_info, start=1):
        episode_by_name[source.name] = episode_index
        lengths = balanced_lengths(duration, maximum)
        offset = 0.0
        for length in lengths:
            drafts.append(_MetaEpisodeDraft(
                parts=[TimelinePart(source, source.name, offset, offset + length)],
            ))
            offset += length
        if len(lengths) > 1 and operations is not None:
            operations.append(
                f"原第 {episode_index} 集（{source.name}）时长 {duration:.1f} 秒，超过 {maximum:.0f} 秒，"
                f"将均分为 {len(lengths)} 段"
            )

    if drafts and sum(draft.duration for draft in drafts) + 0.01 < minimum:
        raise ValueError(f"整部剧总时长不足 {minimum:.0f} 秒，无法生成符合 Meta 要求的单集")

    def draft_episode_label(draft: _MetaEpisodeDraft) -> str:
        episodes = dict.fromkeys(episode_by_name[part.episode] for part in draft.parts)
        return "、".join(str(episode) for episode in episodes)

    index = 0
    while index < len(drafts):
        current = drafts[index]
        if current.duration + 0.01 >= minimum:
            index += 1
            continue

        if index + 1 < len(drafts):
            following = drafts[index + 1]
            before = current.duration
            current_sources = draft_episode_label(current)
            following_sources = draft_episode_label(following)
            if current.duration + following.duration <= maximum + 0.01:
                current.parts.extend(following.parts)
                drafts.pop(index + 1)
                if operations is not None:
                    operations.append(
                        f"原第 {current_sources} 集时长 {before:.1f} 秒，不足 {minimum:.0f} 秒，"
                        f"已与原第 {following_sources} 集完整合并为新第 {index + 1} 集（{current.duration:.1f} 秒）；"
                        "后续集数依次前移"
                    )
                continue

            needed = minimum - current.duration
            borrowed, remainder = _split_meta_draft(following, needed)
            current.parts.extend(borrowed.parts)
            drafts[index + 1] = remainder
            if operations is not None:
                operations.append(
                    f"原第 {current_sources} 集时长 {before:.1f} 秒，不足 {minimum:.0f} 秒，"
                    f"已从原第 {following_sources} 集片头补入 {needed:.1f} 秒，组成新第 {index + 1} 集"
                    f"（{current.duration:.1f} 秒）；下一集剩余 {remainder.duration:.1f} 秒并顺延重排"
                )
            index += 1
            continue

        if index == 0:
            raise ValueError(f"整部剧总时长不足 {minimum:.0f} 秒，无法生成符合 Meta 要求的单集")

        previous = drafts[index - 1]
        before = current.duration
        current_sources = draft_episode_label(current)
        previous_sources = draft_episode_label(previous)
        if previous.duration + current.duration <= maximum + 0.01:
            previous.parts.extend(current.parts)
            drafts.pop(index)
            if operations is not None:
                operations.append(
                    f"末尾原第 {current_sources} 集时长 {before:.1f} 秒，不足 {minimum:.0f} 秒，"
                    f"已与原第 {previous_sources} 集合并为新的第 {index} 集（{previous.duration:.1f} 秒）"
                )
            index = max(0, index - 1)
            continue

        needed = minimum - current.duration
        retained, borrowed = _split_meta_draft(previous, previous.duration - needed)
        current.parts = [*borrowed.parts, *current.parts]
        drafts[index - 1] = retained
        if operations is not None:
            operations.append(
                f"末尾原第 {current_sources} 集时长 {before:.1f} 秒，不足 {minimum:.0f} 秒，"
                f"已从原第 {previous_sources} 集末尾补入 {needed:.1f} 秒，"
                f"调整后前一集 {retained.duration:.1f} 秒、末集 {current.duration:.1f} 秒"
            )
        index += 1

    result = [
        MetaEpisodePart(
            sequence=sequence,
            parts=tuple(draft.parts),
            source_episodes=tuple(dict.fromkeys(episode_by_name[part.episode] for part in draft.parts)),
        )
        for sequence, draft in enumerate(drafts, start=1)
    ]
    invalid = [part for part in result if part.duration < minimum - 0.05 or part.duration > maximum + 0.05]
    if invalid:
        raise ValueError("Meta 单集时长整理失败，仍存在不符合 60–180 秒要求的文件")
    return result


def build_hook_groups(hooks: list[HookAsset], variant_count: int, hooks_per_variant: int) -> list[list[HookAsset]]:
    """生成互不重复的片头组合；同一成品内不会重复使用同一个高能点。"""
    if variant_count <= 0 or not hooks:
        return []
    group_size = min(max(1, hooks_per_variant), len(hooks))
    return [list(group) for group in islice(combinations(hooks, group_size), variant_count)]


def slice_timeline(parts: list[TimelinePart], offset: float, duration: float) -> list[TimelinePart]:
    end_at = offset + duration
    cursor = 0.0
    result: list[TimelinePart] = []
    for part in parts:
        part_end = cursor + part.duration
        overlap_start = max(offset, cursor)
        overlap_end = min(end_at, part_end)
        if overlap_end > overlap_start + 0.01:
            local_start = part.start + overlap_start - cursor
            result.append(TimelinePart(part.path, part.episode, local_start, local_start + overlap_end - overlap_start))
        cursor = part_end
        if cursor >= end_at:
            break
    return result


def read_sensitive_ranges(drama_dir: Path) -> dict[str, list[tuple[float, float]]]:
    path = drama_dir / "factory_analysis.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[tuple[float, float]]] = {}
    for episode in data.get("episodes", []):
        result[str(episode.get("episode", ""))] = [
            (max(0.0, float(row.get("start", 0)) - 0.25), float(row.get("end", 0)) + 0.25)
            for row in episode.get("sensitive", [])
            if row.get("review_status", "approved") != "rejected"
            and float(row.get("end", 0)) > float(row.get("start", 0))
        ]
    return result


def sync_hook_assets(session: Session, drama: Drama) -> list[HookAsset]:
    existing = session.exec(select(HookAsset).where(HookAsset.drama_id == drama.id)).all()
    keys = {(row.episode, round(row.start, 2), round(row.end, 2)): row for row in existing}
    candidates: list[tuple[str, float, float, str, str, float]] = [
        (row.episode, row.start, row.end, row.note, "manual", 0) for row in read_highlights(Path(drama.file_dir))
    ]
    analysis_path = Path(drama.file_dir) / "factory_analysis.json"
    if analysis_path.is_file():
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
        for episode in data.get("episodes", []):
            for row in episode.get("high_energy", []):
                if row.get("review_status", "approved") != "approved":
                    continue
                candidates.append((
                    str(episode.get("episode", "")), float(row.get("start", 0)), float(row.get("end", 0)),
                    "；".join(row.get("energy_reasons", [])) or str(row.get("text", ""))[:80], "analysis", float(row.get("energy_score", 0)),
                ))
    changed = False
    for episode, start, end, note, source, score in candidates:
        key = (episode, round(start, 2), round(end, 2))
        if not episode or end <= start or key in keys:
            continue
        item = HookAsset(drama_id=drama.id, episode=episode, start=start, end=end, note=note, source=source, energy_score=score)
        session.add(item)
        existing.append(item)
        keys[key] = item
        changed = True
    if changed:
        session.commit()
        for item in existing:
            session.refresh(item)
    return existing


def _run_ffmpeg_with_progress(args: list[str], duration: float, on_progress: Callable[[float], None]) -> None:
    command = [*args[:2], "-nostats", "-loglevel", "error", "-progress", "pipe:1", *args[2:]]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    last_percent = -1
    for line in process.stdout:
        key, _, raw_value = line.strip().partition("=")
        if key not in {"out_time_us", "out_time_ms"} or duration <= 0:
            continue
        try:
            percent = min(99, max(0, int(float(raw_value) / 1_000_000 / duration * 100)))
        except ValueError:
            continue
        if percent != last_percent:
            last_percent = percent
            on_progress(percent / 100)
    stderr = process.stderr.read() if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise MediaCommandError(stderr[-2000:] or "媒体命令执行失败")
    on_progress(1.0)


def _encode_piece(
    ffmpeg: str,
    ffprobe: str,
    part: TimelinePart,
    output: Path,
    profile_name: str,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    profile = PROFILES[profile_name]
    info = probe_media(ffprobe, part.path)
    output.parent.mkdir(parents=True, exist_ok=True)
    base = [ffmpeg, "-y", "-ss", f"{part.start:.3f}", "-i", str(part.path), "-t", f"{part.duration:.3f}"]
    if info["has_audio"]:
        mapping = ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        base += ["-f", "lavfi", "-t", f"{part.duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        mapping = ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    if profile_name == "meta":
        video_filter = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=25"
        video_options = [
            "-vf", video_filter, "-c:v", "libx264", "-preset", profile["preset"], "-pix_fmt", "yuv420p",
            "-b:v", "3M", "-minrate", "3M", "-maxrate", "3M", "-bufsize", "6M",
            "-x264-params", "nal-hrd=cbr:force-cfr=1",
        ]
    else:
        video_filter = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=30"
        video_options = [
            "-vf", video_filter, "-c:v", "libx264", "-preset", profile["preset"], "-crf", profile["crf"],
            "-pix_fmt", "yuv420p",
        ]
    command = base + mapping + video_options + [
        "-c:a", "aac", "-b:a", profile["audio"], "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(output),
    ]
    if on_progress:
        _run_ffmpeg_with_progress(command, part.duration, on_progress)
    else:
        run_command(command)


def _concat_files(ffmpeg: str, pieces: list[Path], output: Path, concat_path: Path) -> None:
    lines = []
    for item in pieces:
        escaped = item.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'\n")
    concat_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path.write_text("".join(lines), encoding="utf-8")
    run_command([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path.resolve()), "-c", "copy", "-movflags", "+faststart", str(output.resolve())])


def render_timeline_slice(
    parts: list[TimelinePart],
    output: Path,
    work: Path,
    profile: str,
    on_progress: Callable[[float], None] | None = None,
) -> float:
    settings = get_settings()
    encoded: list[Path] = []
    total_duration = sum(item.duration for item in parts)
    completed_duration = 0.0
    for index, part in enumerate(parts, start=1):
        piece = work / f"part_{index:04d}.mp4"
        def report_piece(ratio: float, *, before: float = completed_duration, length: float = part.duration) -> None:
            if on_progress and total_duration > 0:
                on_progress(min(1.0, (before + length * ratio) / total_duration))

        _encode_piece(settings.ffmpeg_binary, settings.ffprobe_binary, part, piece, profile, report_piece if on_progress else None)
        encoded.append(piece)
        completed_duration += part.duration
    if not encoded:
        raise ValueError("没有可输出的安全内容")
    _concat_files(settings.ffmpeg_binary, encoded, output, work / "concat.txt")
    if on_progress:
        on_progress(1.0)
    return total_duration


def _write_meta_manifest(drama_dir: Path, job_id: int, files: list[Path]) -> None:
    manifest = drama_dir / "generated" / "meta_current.json"
    manifest.write_text(json.dumps({
        "factory_job_id": job_id,
        "files": [str(path.resolve()) for path in files],
        "generated_at": _utcnow().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FactoryPipeline:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _save(self, session: Session, job: FactoryJob, step: str, progress: int) -> None:
        job.current_step = step
        job.progress = progress
        session.add(job)
        session.commit()
        session.refresh(job)

    def process_queued(self) -> None:
        with self._lock:
            while True:
                with Session(database.engine) as session:
                    job = session.exec(select(FactoryJob).where(FactoryJob.status == "queued").order_by(FactoryJob.id)).first()
                    if not job:
                        return
                    job.status = "processing"
                    job.started_at = _utcnow()
                    session.add(job)
                    session.commit()
                    job_id = job.id
                self.process_one(job_id)

    def process_one(self, job_id: int) -> None:
        settings = get_settings()
        with Session(database.engine) as session:
            job = session.get(FactoryJob, job_id)
            if not job:
                return
            drama = session.get(Drama, job.drama_id)
            work = Path(drama.file_dir) / ".factory" / f"job_{job.id:04d}" if drama else settings.media_root / ".factory" / str(job.id)
            try:
                if not drama:
                    raise ValueError("剧目不存在")
                sources = sorted(episode_files(Path(drama.file_dir)), key=lambda path: natural_key(path.name))
                if not sources:
                    raise ValueError("请先导入原片视频")
                modes = set(job.output_modes or ["clean_full", "hook_variants"])
                if not modes & {"clean_full", "hook_variants", "meta_split"}:
                    raise ValueError("至少选择一种产出流程")
                work.mkdir(parents=True, exist_ok=True)
                generated_dir = Path(drama.file_dir) / "generated"
                hooks_dir = Path(drama.file_dir) / "hooks"
                meta_dir = generated_dir / "meta" / f"J{job.id:04d}"
                generated_dir.mkdir(parents=True, exist_ok=True)
                hooks_dir.mkdir(parents=True, exist_ok=True)
                stale_assets = session.exec(select(GeneratedAsset).where(GeneratedAsset.factory_job_id == job.id)).all()
                for asset in stale_assets:
                    if asset.clip_id:
                        stale_clip = session.get(Clip, asset.clip_id)
                        if stale_clip:
                            session.delete(stale_clip)
                    session.delete(asset)
                for stale_file in generated_dir.glob(f"J{job.id:04d}_*.mp4"):
                    if stale_file.is_file():
                        stale_file.unlink()
                if meta_dir.is_dir():
                    shutil.rmtree(meta_dir)
                job.clean_count = 0
                job.publish_count = 0
                job.meta_count = 0
                job.output_bytes = 0
                job.error_message = ""
                job.warnings = []
                session.commit()
                job.output_dir = str(generated_dir.resolve())
                job.source_files = [path.name for path in sources]
                self._save(session, job, "读取源文件", 5)

                source_info: list[tuple[Path, float]] = []
                for source in sources:
                    duration = probe_media(settings.ffprobe_binary, source)["duration"]
                    source_info.append((source, duration))

                meta_plan: list[MetaEpisodePart] = []
                if "meta_split" in modes:
                    meta_operations: list[str] = []
                    meta_plan = build_meta_episode_plan(
                        source_info,
                        float(job.max_duration_seconds),
                        minimum=60.0,
                        operations=meta_operations,
                    )
                    job.warnings = [
                        *job.warnings,
                        *meta_operations,
                        f"Meta 时长整理：{len(source_info)} 个有效原片将生成 {len(meta_plan)} 个投递文件，"
                        "每集时长均为 60–180 秒",
                    ]
                    self._save(session, job, "已完成 Meta 超时拆分与短集合并检查", 8)

                body_target: Path | None = None
                body_duration = 0.0
                if modes & {"clean_full", "hook_variants"}:
                    sensitive = read_sensitive_ranges(Path(drama.file_dir)) if job.remove_sensitive else {}
                    timeline: list[TimelinePart] = []
                    removed = 0.0
                    for source, duration in source_info:
                        blocked = sensitive.get(source.name, [])
                        removed += sum(end - start for start, end in merge_ranges(blocked, duration))
                        ranges = safe_ranges(duration, blocked) if blocked else [(0.0, duration)]
                        timeline.extend(TimelinePart(source, source.name, start, end) for start, end in ranges)
                    body_duration = sum(row.duration for row in timeline)
                    if body_duration <= 0:
                        raise ValueError("敏感内容剔除后没有可用视频")
                    job.total_duration = body_duration
                    job.removed_seconds = removed
                    body_filename = f"J{job.id:04d}_clean_full.mp4"
                    body_target = generated_dir / body_filename if "clean_full" in modes else work / body_filename
                    self._save(session, job, "按剧集顺序合并并移除敏感内容", 18)
                    reported_progress = 18

                    def report_clean(ratio: float) -> None:
                        nonlocal reported_progress
                        progress = 18 + round(ratio * 22)
                        if progress <= reported_progress:
                            return
                        reported_progress = progress
                        self._save(
                            session,
                            job,
                            f"正在合并净化视频 · {progress}%",
                            progress,
                        )

                    body_duration = render_timeline_slice(
                        timeline,
                        body_target,
                        work / "clean_full",
                        job.compression_profile,
                        report_clean,
                    )
                    if "clean_full" in modes:
                        clip = Clip(
                            drama_id=drama.id, template_name="clean_full", source_eps=[path.name for path in sources],
                            duration=body_duration, file_path=str(body_target.resolve()), status="approved", progress=100,
                            current_step="completed", factory_job_id=job.id, asset_kind="clean_full", owner_user_id=job.owner_user_id,
                        )
                        session.add(clip)
                        session.commit()
                        session.refresh(clip)
                        session.add(GeneratedAsset(
                            factory_job_id=job.id, drama_id=drama.id, kind="clean_full", sequence=1,
                            file_path=str(body_target.resolve()), filename=body_filename, duration=body_duration,
                            size_bytes=body_target.stat().st_size, clip_id=clip.id, owner_user_id=job.owner_user_id,
                        ))
                        session.commit()
                        job.clean_count = 1

                if "hook_variants" in modes:
                    if not body_target:
                        raise ValueError("高能片头版本缺少完整原剧")
                    hooks = sync_hook_assets(session, drama)
                    if job.selected_hook_ids:
                        selected = [session.get(HookAsset, hook_id) for hook_id in dict.fromkeys(job.selected_hook_ids)]
                        hooks = [row for row in selected if row and row.active]
                    else:
                        hooks = sorted((row for row in hooks if row.active), key=lambda row: (row.energy_score, -row.id), reverse=True)
                    groups = build_hook_groups(hooks, job.publish_variant_count, job.hooks_per_variant)
                    possible = math.comb(len(hooks), min(job.hooks_per_variant, len(hooks))) if hooks else 0
                    if not hooks:
                        job.warnings = [*job.warnings, "没有可用高能点，未生成高能片头版本"]
                    elif job.hooks_per_variant > len(hooks):
                        job.warnings = [*job.warnings, f"可用高能点只有 {len(hooks)} 个，每版已改用 {len(hooks)} 个"]
                    if groups and len(groups) < job.publish_variant_count:
                        job.warnings = [*job.warnings, f"不重复片头组合最多 {possible} 组，本次生成 {len(groups)} 个版本"]

                    encoded_hooks: dict[int, Path] = {}
                    encoded_hook_ranges: dict[int, tuple[float, float]] = {}
                    for index, group in enumerate(groups, start=1):
                        self._save(session, job, f"生成高能片头版本 {index}/{len(groups)}", 42 + round(index / max(1, len(groups)) * 28))
                        hook_files: list[Path] = []
                        hook_seconds = 0.0
                        valid_hooks: list[HookAsset] = []
                        for hook in group:
                            source_drama = session.get(Drama, hook.drama_id)
                            hook_source = next((path for path in episode_files(Path(source_drama.file_dir)) if path.name == hook.episode), None) if source_drama else None
                            if not hook_source:
                                job.warnings = [*job.warnings, f"高能点 #{hook.id} 的原片不存在，已跳过该版本"]
                                valid_hooks = []
                                break
                            hook_start, hook_end = hook_clip_range(
                                hook.start,
                                hook.end,
                                probe_media(settings.ffprobe_binary, hook_source)["duration"],
                            )
                            if hook.id not in encoded_hooks:
                                hook_file = hooks_dir / f"H{hook.id:04d}.mp4"
                                _encode_piece(settings.ffmpeg_binary, settings.ffprobe_binary, TimelinePart(hook_source, hook.episode, hook_start, hook_end), hook_file, job.compression_profile)
                                encoded_hooks[hook.id] = hook_file
                                encoded_hook_ranges[hook.id] = (hook_start, hook_end)
                                hook.file_path = str(hook_file.resolve())
                            hook_files.append(encoded_hooks[hook.id])
                            hook_seconds += hook_end - hook_start
                            valid_hooks.append(hook)
                        if not valid_hooks:
                            continue
                        hook_ids = [hook.id for hook in valid_hooks]
                        suffix = "_".join(f"H{hook_id:04d}" for hook_id in hook_ids)
                        filename = f"J{job.id:04d}_hook_{index:03d}_{suffix}.mp4"
                        target = generated_dir / filename
                        _concat_files(settings.ffmpeg_binary, [*hook_files, body_target], target, work / f"hook_{index:03d}.txt")
                        duration = hook_seconds + body_duration
                        first = valid_hooks[0]
                        first_start, first_end = encoded_hook_ranges[first.id]
                        clip = Clip(
                            drama_id=drama.id, template_name="hook_full", source_eps=[hook.episode for hook in valid_hooks],
                            source_start=first_start, source_end=first_end,
                            duration=duration, file_path=str(target.resolve()), status="approved", progress=100,
                            current_step="completed", hook_asset_id=first.id, factory_job_id=job.id, asset_kind="hook_full", owner_user_id=job.owner_user_id,
                        )
                        session.add(clip)
                        session.commit()
                        session.refresh(clip)
                        session.add(GeneratedAsset(
                            factory_job_id=job.id, drama_id=drama.id, kind="hook_full", sequence=index,
                            file_path=str(target.resolve()), filename=filename, duration=duration,
                            size_bytes=target.stat().st_size, hook_asset_id=first.id, hook_asset_ids=hook_ids, clip_id=clip.id,
                            owner_user_id=job.owner_user_id,
                        ))
                        for hook in valid_hooks:
                            hook.use_count += 1
                            hook.last_used_at = _utcnow()
                            session.add(hook)
                        session.commit()
                        job.publish_count += 1

                if "meta_split" in modes:
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    meta_files: list[Path] = []
                    source_durations = {source.resolve(): duration for source, duration in source_info}
                    for part in meta_plan:
                        source_label = "、".join(str(episode) for episode in part.source_episodes)
                        self._save(
                            session,
                            job,
                            f"生成 Meta 单集 {part.sequence}/{len(meta_plan)} · 来源原片第 {source_label} 集",
                            72 + round(part.sequence / max(1, len(meta_plan)) * 23),
                        )
                        only_part = part.parts[0] if len(part.parts) == 1 else None
                        original_duration = source_durations.get(only_part.path.resolve(), 0.0) if only_part else 0.0
                        source_media = probe_media(settings.ffprobe_binary, only_part.path) if only_part else {}
                        direct_copy = bool(
                            only_part
                            and abs(only_part.start) <= 0.05
                            and abs(only_part.end - original_duration) <= 0.05
                            and meta_video_is_compliant(source_media)
                        )
                        filename = f"J{job.id:04d}_E{part.sequence:03d}.mp4"
                        target = meta_dir / filename
                        if direct_copy and only_part:
                            shutil.copy2(only_part.path, target)
                            actual = only_part.duration
                        else:
                            actual = render_timeline_slice(
                                list(part.parts), target,
                                work / f"meta_{part.sequence:03d}", "meta",
                            )
                        from .meta_sfs import _verify_output
                        compliance_errors = _verify_output(target)
                        if compliance_errors:
                            raise MediaCommandError(
                                f"Meta 单集 {part.sequence} 生成后规格不合规：{'；'.join(compliance_errors)}"
                            )
                        meta_files.append(target)
                        session.add(GeneratedAsset(
                            factory_job_id=job.id, drama_id=drama.id, kind="meta_episode", sequence=part.sequence,
                            file_path=str(target.resolve()), filename=filename, duration=actual, size_bytes=target.stat().st_size,
                            owner_user_id=job.owner_user_id,
                        ))
                    session.commit()
                    job.meta_count = len(meta_files)
                    drama.total_episode_count = max(1, len(meta_files))
                    drama.promotion_episode_count = min(drama.promotion_episode_count, drama.total_episode_count)
                    session.add(drama)
                    if not modes & {"clean_full", "hook_variants"}:
                        job.total_duration = sum(duration for _, duration in source_info)
                        job.removed_seconds = 0
                    _write_meta_manifest(Path(drama.file_dir), job.id, meta_files)

                assets = session.exec(select(GeneratedAsset).where(GeneratedAsset.factory_job_id == job.id)).all()
                job.output_bytes = sum(row.size_bytes for row in assets)
                job.status = "completed"
                job.current_step = "已完成"
                job.progress = 100
                job.completed_at = _utcnow()
                session.add(job)
                session.commit()
            except Exception as exc:
                if drama:
                    generated_root = (Path(drama.file_dir) / "generated").resolve()
                    manifest = generated_root / "meta_current.json"
                    if manifest.is_file():
                        try:
                            if json.loads(manifest.read_text(encoding="utf-8")).get("factory_job_id") == job.id:
                                manifest.unlink()
                        except Exception:
                            pass
                    partial_assets = session.exec(select(GeneratedAsset).where(GeneratedAsset.factory_job_id == job.id)).all()
                    for asset in partial_assets:
                        target = Path(asset.file_path).resolve()
                        if generated_root in target.parents and target.is_file():
                            target.unlink()
                        if asset.clip_id:
                            clip = session.get(Clip, asset.clip_id)
                            if clip:
                                session.delete(clip)
                        session.delete(asset)
                job.status = "failed"
                job.current_step = "处理失败"
                job.error_message = str(exc)[-2000:]
                job.completed_at = _utcnow()
                session.add(job)
                session.commit()
            finally:
                if work.is_dir():
                    shutil.rmtree(work, ignore_errors=True)


factory_pipeline = FactoryPipeline()


def resume_factory_jobs() -> None:
    with Session(database.engine) as session:
        interrupted = session.exec(select(FactoryJob).where(FactoryJob.status == "processing")).all()
        for job in interrupted:
            job.status = "queued"
            job.current_step = "服务器重启，等待恢复"
            session.add(job)
        queued = bool(interrupted or session.exec(select(FactoryJob).where(FactoryJob.status == "queued")).first())
        session.commit()
    if queued:
        threading.Thread(target=factory_pipeline.process_queued, name="factory-recovery", daemon=True).start()
