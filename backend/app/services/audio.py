import random
import shutil
import subprocess
import sys
from pathlib import Path

from .clipper import run_command

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


def find_bgm(media_root: Path, genres: list[str]) -> Path | None:
    candidates: list[Path] = []
    for genre in genres:
        folder = media_root / "bgm" / genre
        if folder.is_dir():
            candidates.extend(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)
    return random.choice(candidates) if candidates else None


def replace_background_music(ffmpeg: str, source: Path, genres: list[str], media_root: Path, output: Path, work: Path) -> tuple[Path, Path | None, bool]:
    """失败时复制原片作为输出，返回值明确标识没有替换音频。"""
    bgm = find_bgm(media_root, genres)
    if not bgm:
        shutil.copy2(source, output)
        return output, None, False
    try:
        demucs_out = work / "demucs"
        demucs_input = work / "demucs_input.wav"
        run_command([ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100", str(demucs_input)])
        env = dict(__import__('os').environ)
        ffmpeg_parent = str(Path(ffmpeg).resolve().parent) if Path(ffmpeg).exists() else ""
        if ffmpeg_parent: env["PATH"] = ffmpeg_parent + __import__('os').pathsep + env.get("PATH", "")
        result = subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", str(demucs_out), str(demucs_input)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        vocals = next(demucs_out.rglob("vocals.wav"))
        # 新 BGM 相对人声降低约 14dB，并循环到视频结束。
        run_command([ffmpeg, "-y", "-i", str(source), "-i", str(vocals), "-stream_loop", "-1", "-i", str(bgm), "-filter_complex", "[2:a]volume=-14dB[bgm];[1:a][bgm]amix=inputs=2:duration=first:normalize=0[mix]", "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output)])
        return output, vocals, True
    except Exception:
        shutil.copy2(source, output)
        return output, None, False
