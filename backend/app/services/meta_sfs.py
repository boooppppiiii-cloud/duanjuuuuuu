"""Meta Shortform Series (SFS) 本地投递包生成与严格预检。"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from ..config import get_settings
from ..models import Drama
from ..schemas import MetaSFSRequest
from .drama_library import IMAGE_SUFFIXES, episode_files, files_with_suffix

ALLOWED_GENRES = {
    "Action", "Adventure", "Animated", "Comedy", "Crime", "Documentary",
    "Drama", "Family", "Fantasy", "Historical", "Horror", "Musical",
    "Mystery", "Noir", "Reality", "Romance", "Science fiction", "Sports",
    "Thriller", "Western",
}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def suggest_slug(title: str, drama_id: int) -> str:
    raw = title.strip().casefold().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", raw)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or f"short-drama-{drama_id}"


def _binary(name: str) -> str:
    configured = getattr(get_settings(), f"{name}_binary")
    found = shutil.which(configured)
    if not found:
        raise RuntimeError(f"找不到 {name}，请先运行环境体检")
    return found


def inspect_video(path: Path) -> dict:
    command = [_binary("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True)
    data = json.loads(result.stdout)
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    audio = next((item for item in data.get("streams", []) if item.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    return {
        "duration": float(fmt.get("duration") or video.get("duration") or 0),
        "size": int(fmt.get("size") or path.stat().st_size),
        "format": str(fmt.get("format_name") or ""),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or ""),
        "video_bitrate": int(video.get("bit_rate") or fmt.get("bit_rate") or 0),
        "audio_codec": str(audio.get("codec_name") or ""),
        "audio_channels": int(audio.get("channels") or 0),
        "has_audio": bool(audio),
    }


def _cover_candidates(drama_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for folder in (drama_dir / "stills", drama_dir / "basemaps", drama_dir):
        candidates.extend(files_with_suffix(folder, IMAGE_SUFFIXES))
    return candidates


def _cover_info(path: Path | None) -> dict:
    if not path:
        return {"path": "", "width": 0, "height": 0}
    with Image.open(path) as image:
        return {"path": str(path), "width": image.width, "height": image.height}


def preflight(drama: Drama, payload: MetaSFSRequest) -> dict:
    drama_dir = Path(drama.file_dir)
    sources = episode_files(drama_dir)
    expected_total = max(int(drama.total_episode_count or 0), 1)
    effective_description = drama.description.strip() or payload.description.strip()
    effective_genres = drama.genres or payload.genres
    slug = payload.series_slug.strip() or suggest_slug(drama.title, drama.id or 0)
    blockers: list[str] = []
    fixable: list[str] = []
    if not SLUG_RE.fullmatch(slug):
        blockers.append("系列英文标识必须是 kebab-case，只能包含小写字母、数字和短横线")
    if not sources:
        blockers.append("剧目目录中没有可投递的视频")
    elif len(sources) != expected_total:
        blockers.append(f"剧目任务登记为 {expected_total} 集，但当前选择了 {len(sources)} 个视频；Meta 要求视频数量、文件名总集数与系列 CSV 完全一致")
    if not effective_description:
        blockers.append("剧目任务缺少剧情简介")
    if not effective_genres or any(item not in ALLOWED_GENRES for item in effective_genres):
        blockers.append("Genre 必须从 Meta 官方类型列表中选择")
    try:
        datetime.strptime(payload.release_date, "%m/%d/%Y")
    except ValueError:
        blockers.append("Release Date 必须使用 MM/DD/YYYY，例如 06/26/2026")

    assets = []
    for index, source in enumerate(sources, 1):
        try:
            info = inspect_video(source)
            issues = []
            if not 60 <= info["duration"] <= 180:
                issues.append("时长必须在 60 秒到 3 分钟之间")
                blockers.append(f"第 {index} 集时长 {info['duration']:.1f} 秒，不符合 60 秒到 3 分钟要求")
            if info["size"] > 2 * 1024**3:
                issues.append("文件超过 2GB")
                blockers.append(f"第 {index} 集文件超过 2GB")
            if (info["width"], info["height"]) != (1080, 1920): issues.append("将自动转为 1080x1920")
            if info["video_codec"] != "h264": issues.append("将自动转为 H.264")
            if info["video_bitrate"] < 2_500_000: issues.append("将自动提升视频码率到 3Mbps")
            if info["audio_codec"] != "aac" or info["audio_channels"] != 2: issues.append("将自动转为 AAC 双声道")
            if issues and not any("时长" in item or "2GB" in item for item in issues):
                fixable.append(f"第 {index} 集：" + "、".join(issues))
            assets.append({"episode": index, "source": str(source), "target": f"{slug}_ep{index:03}_{expected_total:03}.mp4", "info": info, "issues": issues})
        except Exception as exc:
            blockers.append(f"第 {index} 集媒体信息读取失败：{exc}")
            assets.append({"episode": index, "source": str(source), "target": "", "info": {}, "issues": [str(exc)]})

    cover = _cover_candidates(drama_dir)
    cover_info = _cover_info(cover[0] if cover else None)
    if not cover:
        blockers.append("缺少剧照或底图，无法自动生成必需的 3:4 封面与方形封面")
    else:
        fixable.append("将从首张剧照自动生成 1440x1920 竖版封面和 1200x1200 方形封面")
    return {
        "ready": not blockers,
        "series_slug": slug,
        "episode_count": expected_total,
        "assets": assets,
        "cover_source": cover_info,
        "blockers": list(dict.fromkeys(blockers)),
        "automatic_fixes": list(dict.fromkeys(fixable)),
        "requirements": {
            "video": "MP4/H.264 · 9:16 · 1080x1920 · 60秒-3分钟 · 视频码率≥2.5Mbps · AAC双声道 · 单文件≤2GB",
            "cover": "3:4，至少 1440x1920",
            "square_cover": "1:1，至少 1200x1200",
            "naming": "<series-name>_epXXX_<total>.mp4，集数和总集数均为三位数字",
        },
    }


def _render_cover(source: Path, target: Path, size: tuple[int, int]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source).convert("RGB") as image:
        ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.42)).save(target, quality=94, subsampling=0)


def _normalize_video(source: Path, target: Path, has_audio: bool) -> None:
    ffmpeg = _binary("ffmpeg")
    command = [ffmpeg, "-y", "-i", str(source)]
    if not has_audio:
        command += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    command += [
        "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-shortest",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=25",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-b:v", "3M",
        "-minrate", "3M", "-maxrate", "3M", "-bufsize", "6M", "-x264-params", "nal-hrd=cbr:force-cfr=1",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-movflags", "+faststart", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:] or "ffmpeg 转码失败")


def _verify_output(path: Path) -> list[str]:
    info = inspect_video(path)
    errors = []
    if info["video_codec"] != "h264": errors.append("视频编码不是 H.264")
    if (info["width"], info["height"]) != (1080, 1920): errors.append("分辨率不是 1080x1920")
    if not 59.5 <= info["duration"] <= 180.5: errors.append("时长不在 60 秒到 3 分钟之间")
    if info["video_bitrate"] < 2_500_000: errors.append("视频码率低于 2.5Mbps")
    if info["audio_codec"] != "aac" or info["audio_channels"] != 2: errors.append("音频不是 AAC 双声道")
    if info["size"] > 2 * 1024**3: errors.append("文件超过 2GB")
    return errors


def build_package(drama: Drama, payload: MetaSFSRequest) -> tuple[Path, dict]:
    check = preflight(drama, payload)
    if check["blockers"]:
        raise ValueError("；".join(check["blockers"]))
    settings = get_settings()
    slug = check["series_slug"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_root = settings.media_root / "packages" / "meta_sfs" / f"{slug}_{stamp}"
    series_dir = package_root / slug
    series_dir.mkdir(parents=True, exist_ok=False)

    sources = episode_files(Path(drama.file_dir))
    total = max(int(drama.total_episode_count or 0), 1)
    description = drama.description.strip() or payload.description.strip()
    genres = drama.genres or payload.genres
    output_checks = []
    for index, source in enumerate(sources, 1):
        name = f"{slug}_ep{index:03}_{total:03}.mp4"
        target = series_dir / name
        info = inspect_video(source)
        _normalize_video(source, target, info["has_audio"])
        errors = _verify_output(target)
        if errors:
            raise RuntimeError(f"{name} 转码后仍不合规：{'；'.join(errors)}")
        output_checks.append({"file": name, "status": "passed", "info": inspect_video(target)})
        for subtitle_ext in (".srt", ".vtt"):
            subtitle = source.with_suffix(subtitle_ext)
            if subtitle.exists():
                shutil.copy2(subtitle, series_dir / f"{slug}_ep{index:03}_{total:03}.{payload.locale}{subtitle_ext}")
                break
        if payload.include_thumbnails:
            thumb = series_dir / f"{slug}_ep{index:03}_{total:03}_thumbnail.jpg"
            result = subprocess.run([_binary("ffmpeg"), "-y", "-ss", "1", "-i", str(target), "-frames:v", "1", "-q:v", "2", str(thumb)], capture_output=True, timeout=90)
            if result.returncode != 0: raise RuntimeError(f"{name} 缩略图生成失败")

    cover_source = Path(check["cover_source"]["path"])
    _render_cover(cover_source, series_dir / f"{slug}_cover.jpg", (1440, 1920))
    _render_cover(cover_source, series_dir / f"{slug}_cover_square.jpg", (1200, 1200))

    series_headers = ["Title", "Description", "Total Number of Episodes", "Locale", "Genre", "Release Date", "Cast List & IG Handles", "Tags", "Geogating", "AI Content", "Dubbed Content"]
    with (series_dir / f"{slug}_series.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(series_headers)
        writer.writerow([drama.title, description, total, payload.locale, ",".join(genres), payload.release_date, ",".join(payload.cast_list), ",".join(payload.tags), ",".join(payload.geogating), "yes" if drama.is_ai_generated else "no", "yes" if drama.is_dubbed_content else "no"])
    if payload.include_episode_csv:
        with (series_dir / f"{slug}_episodes.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream); writer.writerow(["Episode", "Description", "Tags"])
            for index in range(1, total + 1): writer.writerow([index, f"{drama.title} Episode {index}", ",".join(payload.tags)])

    manifest = {
        "spec": "Meta Shortform Series MVP Partner Onboarding Instructions v260626",
        "status": "passed", "series_slug": slug, "episode_count": total,
        "validated_at": datetime.now().isoformat(), "checks": output_checks,
        "next_steps": ["上传整个包根目录到 Google Drive", "至少以 Viewer 权限共享给 Meta SFS 服务账号", "登录已获准的 Instagram 账号", "打开 https://www.instagram.com/sfs_tools 并提交 Google Drive 文件夹链接"],
    }
    (package_root / "validation-report.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_root / "README-投递步骤.txt").write_text(
        "Meta SFS 官方投递包\n\n1. 不要修改系列文件夹内的文件名。\n2. 将整个包根目录上传到 Google Drive。\n3. 共享给 sfs-viewer-drive-reader@sfs-content-viewer.iam.gserviceaccount.com（Viewer 或更高）。\n4. 登录已获准的 Instagram 账号。\n5. 打开 https://www.instagram.com/sfs_tools，粘贴 Google Drive 文件夹链接并主动提交。\n",
        encoding="utf-8",
    )
    return package_root, manifest
