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
    lines = []
    for item in pieces:
        escaped = item.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'\n")
    concat_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path.write_text("".join(lines), encoding="utf-8")
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
                    body_duration = render_timeline_slice(timeline, body_target, work / "clean_full", job.compression_profile)
                    if "clean_full" in modes:
                        clip = Clip(
                            drama_id=drama.id, template_name="clean_full", source_eps=[path.name for path in sources],
                            duration=body_duration, file_path=str(body_target.resolve()), status="approved", progress=100,
                            current_step="completed", factory_job_id=job.id, asset_kind="clean_full",
                        )
                        session.add(clip)
                        session.commit()
                        session.refresh(clip)
                        session.add(GeneratedAsset(
                            factory_job_id=job.id, drama_id=drama.id, kind="clean_full", sequence=1,
                            file_path=str(body_target.resolve()), filename=body_filename, duration=body_duration,
                            size_bytes=body_target.stat().st_size, clip_id=clip.id,
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
                            hook_end = min(hook.end, hook.start + job.hook_duration_seconds)
                            if hook.id not in encoded_hooks:
                                hook_file = hooks_dir / f"H{hook.id:04d}.mp4"
                                _encode_piece(settings.ffmpeg_binary, settings.ffprobe_binary, TimelinePart(hook_source, hook.episode, hook.start, hook_end), hook_file, job.compression_profile)
                                encoded_hooks[hook.id] = hook_file
                                hook.file_path = str(hook_file.resolve())
                            hook_files.append(encoded_hooks[hook.id])
                            hook_seconds += hook_end - hook.start
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
                        clip = Clip(
                            drama_id=drama.id, template_name="hook_full", source_eps=[hook.episode for hook in valid_hooks],
                            source_start=first.start, source_end=min(first.end, first.start + job.hook_duration_seconds),
                            duration=duration, file_path=str(target.resolve()), status="approved", progress=100,
                            current_step="completed", hook_asset_id=first.id, factory_job_id=job.id, asset_kind="hook_full",
                        )
                        session.add(clip)
                        session.commit()
                        session.refresh(clip)
                        session.add(GeneratedAsset(
                            factory_job_id=job.id, drama_id=drama.id, kind="hook_full", sequence=index,
                            file_path=str(target.resolve()), filename=filename, duration=duration,
                            size_bytes=target.stat().st_size, hook_asset_id=first.id, hook_asset_ids=hook_ids, clip_id=clip.id,
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
                    sequence = 0
                    total_sources = len(source_info)
                    for episode_index, (source, duration) in enumerate(source_info, start=1):
                        lengths = balanced_lengths(duration, float(job.max_duration_seconds))
                        offset = 0.0
                        for part_index, length in enumerate(lengths, start=1):
                            sequence += 1
                            self._save(session, job, f"生成 Meta 单集 {episode_index}/{total_sources} · 分段 {part_index}/{len(lengths)}", 72 + round(episode_index / total_sources * 23))
                            suffix = source.suffix.casefold() if len(lengths) == 1 else ".mp4"
                            filename = f"J{job.id:04d}_E{episode_index:03d}_P{part_index:02d}{suffix}"
                            target = meta_dir / filename
                            if len(lengths) == 1:
                                shutil.copy2(source, target)
                                actual = duration
                            else:
                                actual = render_timeline_slice(
                                    [TimelinePart(source, source.name, offset, offset + length)], target,
                                    work / f"meta_{episode_index:03d}_{part_index:02d}", job.compression_profile,
                                )
                            offset += length
                            meta_files.append(target)
                            session.add(GeneratedAsset(
                                factory_job_id=job.id, drama_id=drama.id, kind="meta_episode", sequence=sequence,
                                file_path=str(target.resolve()), filename=filename, duration=actual, size_bytes=target.stat().st_size,
                            ))
                    session.commit()
                    job.meta_count = len(meta_files)
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
