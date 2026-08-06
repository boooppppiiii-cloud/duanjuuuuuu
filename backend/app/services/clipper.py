import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    start: float
    duration: float


class MediaCommandError(RuntimeError):
    pass


def run_command(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise MediaCommandError(result.stderr[-2000:] or "媒体命令执行失败")


def load_template(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for section in ("hook", "body", "output"):
        if section not in data:
            raise ValueError(f"模板缺少字段：{section}")
    for section in ("hook", "body"):
        if float(data[section]["offset"]) < 0 or float(data[section]["duration"]) <= 0:
            raise ValueError(f"模板 {section} 时间参数不合法")
    return data


def cut_hook_and_body(ffmpeg: str, source: Path, highlight_start: float, template: dict, output: Path, work: Path) -> float:
    """分别切出 hook/body，再无重编码拼接成中间片。"""
    work.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    total = 0.0
    for name in ("hook", "body"):
        spec = template[name]
        duration = float(spec["duration"])
        piece = work / f"{name}.mp4"
        run_command([ffmpeg, "-y", "-ss", str(highlight_start + float(spec["offset"])), "-i", str(source), "-t", str(duration), "-c:v", "libx264", "-c:a", "aac", str(piece)])
        pieces.append(piece)
        total += duration
    concat = work / "concat.txt"
    # FFmpeg resolves relative entries against concat.txt's directory. Absolute
    # entries prevent a relative work directory from being duplicated.
    concat.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces), encoding="utf-8")
    run_command([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat.resolve()), "-c", "copy", str(output.resolve())])
    return total


def normalize_vertical(ffmpeg: str, source: Path, output: Path, template: dict) -> None:
    spec = template["output"]
    width, height, fps = int(spec["width"]), int(spec["height"]), int(spec["fps"])
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    run_command([ffmpeg, "-y", "-i", str(source), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(output)])


def make_preview(ffmpeg: str, source: Path, output: Path, duration: float) -> None:
    interval = max(duration / 6, 0.1)
    vf = f"fps=1/{interval},scale=360:-1,tile=3x2:padding=6:margin=6"
    run_command([ffmpeg, "-y", "-i", str(source), "-vf", vf, "-frames:v", "1", str(output)])
