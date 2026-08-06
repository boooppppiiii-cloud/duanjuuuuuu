import shutil
from pathlib import Path

from .clipper import run_command


def finalize_video(ffmpeg: str, clean_video: Path, account_type: str, assets: Path, cache_root: Path) -> Path:
    output = cache_root / f"clip_{clean_video.stem}_{account_type}.mp4"
    if output.exists():
        return output
    cache_root.mkdir(parents=True, exist_ok=True)
    decorated = cache_root / f"{output.stem}_decorated.mp4"
    if account_type == "official":
        logo = assets / "logo.png"
        if logo.exists():
            run_command([ffmpeg, "-y", "-i", str(clean_video), "-i", str(logo), "-filter_complex", "[1:v]scale=160:-1[logo];[0:v][logo]overlay=W-w-36:36", "-c:v", "libx264", "-c:a", "copy", str(decorated)])
        else:
            shutil.copy2(clean_video, decorated)
        endcard = assets / "endcard_official.mp4"
    else:
        shutil.copy2(clean_video, decorated)
        endcard = assets / "endcard_creator.mp4"
    if not endcard.exists():
        shutil.copy2(decorated, output)
        return output
    concat = cache_root / f"{output.stem}.txt"
    concat.write_text(f"file '{decorated.as_posix()}'\nfile '{endcard.as_posix()}'\n", encoding="utf-8")
    run_command([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:v", "libx264", "-c:a", "aac", str(output)])
    return output

