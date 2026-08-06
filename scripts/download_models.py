#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--whisper", action="store_true"); parser.add_argument("--demucs", action="store_true"); args = parser.parse_args()
    both = not args.whisper and not args.demucs
    if args.whisper or both:
        print("[1/2] 下载 faster-whisper small，进度由 Hugging Face 显示…", flush=True)
        from faster_whisper import WhisperModel
        WhisperModel("small", device="cpu", compute_type="int8")
        print("✅ Whisper small 下载完成", flush=True)
    if args.demucs or both:
        print("[2/2] 下载 Demucs htdemucs 模型，进度由下载器显示…", flush=True)
        temp = Path(__file__).resolve().parents[1] / "media" / "uploads" / "model_probe.wav"; temp.parent.mkdir(parents=True, exist_ok=True)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from doctor import find_binary
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg: raise RuntimeError("找不到 ffmpeg，请先运行 doctor.py")
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(temp)], check=True)
        env = dict(__import__('os').environ); env["PATH"] = str(Path(ffmpeg).parent) + __import__('os').pathsep + env.get("PATH", "")
        subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals", str(temp)], check=True, env=env)
        print("✅ Demucs 模型下载完成", flush=True)


if __name__ == "__main__": main()
