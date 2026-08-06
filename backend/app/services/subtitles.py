from pathlib import Path

from .clipper import run_command


def srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def transcribe(source: Path, model_name: str, device: str, compute_type: str, srt_path: Path) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(source), vad_filter=True)
    texts: list[str] = []
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        text = segment.text.strip()
        if not text:
            continue
        texts.append(text)
        blocks.append(f"{index}\n{srt_timestamp(segment.start)} --> {srt_timestamp(segment.end)}\n{text}\n")
    if not blocks:
        # libass rejects an empty SRT. Keep the pipeline usable for silent or
        # music-only material while making the degraded result explicit.
        blocks.append("1\n00:00:00,000 --> 00:00:02,000\n[无可识别对白]\n")
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return "\n".join(texts)


def burn_subtitles(ffmpeg: str, source: Path, srt_path: Path, output: Path) -> None:
    escaped = srt_path.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
    style = "FontSize=18,Outline=2,Shadow=1,MarginV=80,Alignment=2"
    run_command([ffmpeg, "-y", "-i", str(source), "-vf", f"subtitles='{escaped}':force_style='{style}'", "-c:v", "libx264", "-c:a", "copy", str(output)])
