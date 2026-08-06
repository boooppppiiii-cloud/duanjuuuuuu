import json
import math
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from .. import database
from ..config import get_settings
from ..models import Clip, Drama, FactoryJob, GeneratedAsset, HookAsset
from .clipper import MediaCommandError, run_command
from .drama_library import episode_files, read_highlights


@dataclass(frozen=True)
class TimelinePart:
    path: Path
    episode: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


PROFILES = {
    "balanced": {"crf": "23", "preset": "medium", "audio": "128k"},
    "small": {"crf": "28", "preset": "slow", "audio": "96k"},
}


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def probe_media(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
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
    return {"duration": duration, "has_audio": any(row.get("codec_type") == "audio" for row in streams)}


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
            if float(row.get("end", 0)) > float(row.get("start", 0))
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


def _encode_piece(ffmpeg: str, ffprobe: str, part: TimelinePart, output: Path, profile_name: str) -> None:
    profile = PROFILES[profile_name]
    info = probe_media(ffprobe, part.path)
    output.parent.mkdir(parents=True, exist_ok=True)
    base = [ffmpeg, "-y", "-ss", f"{part.start:.3f}", "-i", str(part.path), "-t", f"{part.duration:.3f}"]
    if info["has_audio"]:
        mapping = ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        base += ["-f", "lavfi", "-t", f"{part.duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        mapping = ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    video_filter = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=30"
    run_command(base + mapping + [
        "-vf", video_filter, "-c:v", "libx264", "-preset", profile["preset"], "-crf", profile["crf"],
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", profile["audio"], "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(output),
    ])


def _concat_files(ffmpeg: str, pieces: list[Path], output: Path, concat_path: Path) -> None:
    concat_path.write_text("".join(f"file '{item.resolve().as_posix()}'\n" for item in pieces), encoding="utf-8")
    run_command([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path.resolve()), "-c", "copy", "-movflags", "+faststart", str(output.resolve())])


def render_timeline_slice(parts: list[TimelinePart], output: Path, work: Path, profile: str) -> float:
    settings = get_settings()
    encoded: list[Path] = []
    for index, part in enumerate(parts, start=1):
        piece = work / f"part_{index:04d}.mp4"
        _encode_piece(settings.ffmpeg_binary, settings.ffprobe_binary, part, piece, profile)
        encoded.append(piece)
    if not encoded:
        raise ValueError("没有可输出的安全内容")
    _concat_files(settings.ffmpeg_binary, encoded, output, work / "concat.txt")
    return sum(item.duration for item in parts)


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
                work.mkdir(parents=True, exist_ok=True)
                generated_dir = Path(drama.file_dir) / "generated"
                hooks_dir = Path(drama.file_dir) / "hooks"
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
                job.clean_count = 0
                job.publish_count = 0
                job.output_bytes = 0
                job.error_message = ""
                session.commit()
                job.output_dir = str(generated_dir.resolve())
                job.source_files = [path.name for path in sources]
                self._save(session, job, "读取原片与敏感区间", 5)

                sensitive = read_sensitive_ranges(Path(drama.file_dir)) if job.remove_sensitive else {}
                timeline: list[TimelinePart] = []
                removed = 0.0
                for source in sources:
                    duration = probe_media(settings.ffprobe_binary, source)["duration"]
                    blocked = sensitive.get(source.name, [])
                    removed += sum(end - start for start, end in merge_ranges(blocked, duration))
                    ranges = safe_ranges(duration, blocked) if blocked else [(0.0, duration)]
                    timeline.extend(TimelinePart(source, source.name, start, end) for start, end in ranges)
                total = sum(row.duration for row in timeline)
                if total <= 0:
                    raise ValueError("敏感内容剔除后没有可用视频")
                job.total_duration = total
                job.removed_seconds = removed

                hooks = sync_hook_assets(session, drama)
                if job.selected_hook_ids:
                    selected = [session.get(HookAsset, hook_id) for hook_id in dict.fromkeys(job.selected_hook_ids)]
                    hooks = [row for row in selected if row and row.active]
                else:
                    hooks = sorted((row for row in hooks if row.active), key=lambda row: (row.energy_score, -row.id), reverse=True)
                requested_variants = min(job.publish_variant_count, len(hooks))
                if job.publish_variant_count and not hooks:
                    job.warnings = [*job.warnings, "没有可用高能点，本次只生成无钩子的完整分段"]
                elif requested_variants < job.publish_variant_count:
                    job.warnings = [*job.warnings, f"可用高能点只有 {len(hooks)} 个，已生成 {requested_variants} 个不重复钩子版本"]

                body_limit = float(job.max_duration_seconds - job.hook_duration_seconds) if requested_variants else float(job.max_duration_seconds)
                lengths = balanced_lengths(total, body_limit)
                offset = 0.0
                clean_assets: list[GeneratedAsset] = []
                for index, length in enumerate(lengths, start=1):
                    self._save(session, job, f"生成原剧分段 {index}/{len(lengths)}", 10 + round(index / len(lengths) * 55))
                    portions = slice_timeline(timeline, offset, length)
                    filename = f"J{job.id:04d}_原剧_{index:03d}.mp4"
                    target = generated_dir / filename
                    actual = render_timeline_slice(portions, target, work / f"clean_{index:03d}", job.compression_profile)
                    asset = GeneratedAsset(factory_job_id=job.id, drama_id=drama.id, kind="clean", sequence=index, file_path=str(target.resolve()), filename=filename, duration=actual, size_bytes=target.stat().st_size)
                    session.add(asset)
                    clean_assets.append(asset)
                    offset += length
                session.commit()
                for asset in clean_assets:
                    session.refresh(asset)
                job.clean_count = len(clean_assets)

                publish_count = min(requested_variants, len(clean_assets))
                for index in range(publish_count):
                    hook = hooks[index]
                    source_drama = session.get(Drama, hook.drama_id)
                    if not source_drama:
                        job.warnings = [*job.warnings, f"高能点 #{hook.id} 的剧目不存在，已跳过"]
                        continue
                    hook_source = next((path for path in episode_files(Path(source_drama.file_dir)) if path.name == hook.episode), None)
                    if not hook_source:
                        job.warnings = [*job.warnings, f"高能点 #{hook.id} 的原片不存在，已跳过"]
                        continue
                    self._save(session, job, f"生成差异化钩子版本 {index + 1}/{publish_count}", 68 + round((index + 1) / max(1, publish_count) * 27))
                    hook_file = hooks_dir / f"H{hook.id:04d}.mp4"
                    hook_end = min(hook.end, hook.start + job.hook_duration_seconds)
                    _encode_piece(settings.ffmpeg_binary, settings.ffprobe_binary, TimelinePart(hook_source, hook.episode, hook.start, hook_end), hook_file, job.compression_profile)
                    hook.file_path = str(hook_file.resolve())
                    hook.use_count += 1
                    hook.last_used_at = _utcnow()
                    body = clean_assets[index]
                    filename = f"J{job.id:04d}_发布_{index + 1:03d}_H{hook.id:04d}.mp4"
                    target = generated_dir / filename
                    _concat_files(settings.ffmpeg_binary, [hook_file, Path(body.file_path)], target, work / f"publish_{index + 1:03d}.txt")
                    duration = min(float(job.max_duration_seconds), job.hook_duration_seconds + body.duration)
                    clip = Clip(
                        drama_id=drama.id, template_name="unique_3s_hook", source_eps=[hook.episode], source_start=hook.start,
                        source_end=hook_end, duration=duration, file_path=str(target.resolve()), status="approved", progress=100,
                        current_step="completed", hook_asset_id=hook.id, factory_job_id=job.id, asset_kind="publish",
                    )
                    session.add(clip)
                    session.commit()
                    session.refresh(clip)
                    session.add(GeneratedAsset(
                        factory_job_id=job.id, drama_id=drama.id, kind="publish", sequence=index + 1, file_path=str(target.resolve()),
                        filename=filename, duration=duration, size_bytes=target.stat().st_size, hook_asset_id=hook.id, clip_id=clip.id,
                    ))
                    session.add(hook)
                    session.commit()
                    job.publish_count += 1

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
