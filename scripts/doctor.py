#!/usr/bin/env python3
import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"): sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class Report:
    def __init__(self): self.failed = 0
    def item(self, ok: bool, name: str, detail: str, fix: str = ""):
        print(f"{'✅' if ok else '❌'} {name}：{detail}")
        if not ok:
            self.failed += 1
            if fix: print(f"   怎么修：{fix}")


def find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found: return found
    if os.name == "nt":
        candidates = list((Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages").glob(f"**/{name}.exe"))
        candidates.sort(key=lambda path: ("Shared" not in str(path), len(str(path))))
        if candidates: return str(candidates[0])
    return None


def command_version(path: str | None) -> tuple[bool, str]:
    if not path: return False, "未找到"
    try:
        line = subprocess.run([path, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10).stdout.splitlines()[0]
        return True, f"{line}（{path}）"
    except Exception as exc: return False, str(exc)


def module_check(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def port_state(port: int, health_url: str) -> tuple[bool, str]:
    with socket.socket() as sock:
        occupied = sock.connect_ex(("127.0.0.1", port)) == 0
    if not occupied: return True, f"端口 {port} 空闲"
    try:
        with urllib.request.urlopen(health_url, timeout=3) as response:
            return response.status == 200, f"端口 {port} 已由本项目服务监听"
    except Exception: return False, f"端口 {port} 被其他程序占用"


def frontend_port_state(port: int) -> tuple[bool, str]:
    with socket.socket() as sock:
        occupied = sock.connect_ex(("127.0.0.1", port)) == 0
    if not occupied:
        return True, f"端口 {port} 空闲"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=3) as response:
            body = response.read().decode("utf-8", errors="replace")
        if response.status == 200 and "社媒运营中心" in body:
            return True, f"端口 {port} 已由本项目服务监听"
    except Exception:
        pass
    return False, f"端口 {port} 被其他程序占用"


def main() -> int:
    parser = argparse.ArgumentParser(description="短剧运营工具环境体检")
    parser.add_argument("--skip-api", action="store_true", help="仅排查本地环境，不发送 API 最小请求")
    args = parser.parse_args(); report = Report()
    print("\n=== 短剧运营工具环境体检 ===")
    ffmpeg = find_binary("ffmpeg"); ffprobe = find_binary("ffprobe")
    for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        ok, detail = command_version(path); report.item(ok, name, detail, "Windows: winget install Gyan.FFmpeg；Ubuntu: sudo apt-get install -y ffmpeg")
    demucs_ok, whisper_ok = module_check("demucs"), module_check("faster_whisper")
    report.item(demucs_ok, "Demucs Python 包", "可以导入" if demucs_ok else "无法导入", f'"{sys.executable}" -m pip install demucs==4.0.1')
    report.item(whisper_ok, "faster-whisper Python 包", "可以导入" if whisper_ok else "无法导入", f'"{sys.executable}" -m pip install faster-whisper==1.2.0')
    whisper_cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-small"
    demucs_cache = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
    report.item(whisper_cache.exists(), "Whisper small 模型", str(whisper_cache) if whisper_cache.exists() else "尚未下载", f'"{sys.executable}" scripts/download_models.py --whisper')
    demucs_models = list(demucs_cache.glob("*.th")) if demucs_cache.exists() else []
    report.item(bool(demucs_models), "Demucs 模型", str(demucs_models[0]) if demucs_models else "尚未下载", f'"{sys.executable}" scripts/download_models.py --demucs')
    fonts = list((ROOT / "media" / "assets").glob("*.tt[cf]"))
    report.item(bool(fonts), "中文字体", str(fonts[0]) if fonts else "media/assets 中没有 ttf/ttc", "复制 NotoSansCJK-Regular.ttc 到 media/assets/")
    for relative in ("dramas", "bgm", "assets", "clips", "posts", "packages", "uploads"):
        path = ROOT / "media" / relative
        ok = path.is_dir() and os.access(path, os.W_OK)
        report.item(ok, f"媒体目录 media/{relative}", "存在且可写" if ok else "缺失或不可写", f'python -c "from pathlib import Path; Path(r\'{path}\').mkdir(parents=True, exist_ok=True)"')
    from app.config import get_settings
    settings = get_settings()
    text_key = bool(settings.gemini_api_key or settings.qwen_api_key)
    report.item(text_key, "文本模型密钥", "已配置 Gemini 或千问" if text_key else "GEMINI_API_KEY 与 QWEN_API_KEY 均为空", "编辑 .env；Gemini: https://aistudio.google.com/apikey；千问: https://bailian.console.aliyun.com/")
    report.item(bool(settings.gemini_api_key), "图像模型密钥", "GEMINI_API_KEY 已配置" if settings.gemini_api_key else "缺少 GEMINI_API_KEY", "在 .env 中填写 GEMINI_API_KEY=AIza...（不要提交到 git）")
    try:
        from app.database import create_db_and_tables, engine
        from sqlalchemy import text
        create_db_and_tables()
        with engine.begin() as connection: connection.execute(text("SELECT 1"))
        report.item(True, "数据库读写", settings.database_url)
    except Exception as exc: report.item(False, "数据库读写", str(exc), "检查 DATABASE_URL 和 backend/data 目录写权限")
    ok, detail = port_state(8000, "http://127.0.0.1:8000/api/health")
    report.item(ok, "后端端口", detail, "Windows: Get-NetTCPConnection -LocalPort 8000；Ubuntu: sudo lsof -i :8000")
    frontend_port = int(os.getenv("FRONTEND_PORT", "5174"))
    ok, detail = frontend_port_state(frontend_port)
    report.item(ok, "前端端口", detail, f"Windows: Get-NetTCPConnection -LocalPort {frontend_port}；Ubuntu: sudo lsof -i :{frontend_port}")
    if args.skip_api:
        print("⚠️ API 连通性：本次使用 --skip-api 跳过，不计为全绿验收")
    elif text_key:
        try:
            if settings.gemini_api_key:
                from app.services.llm import _gemini
                answer = _gemini('只输出 {"ok":true}')
            else:
                from app.services.llm import _qwen
                answer = _qwen('只输出 {"ok":true}')
            report.item(bool(answer), "文本模型 API", "最小请求成功")
        except Exception as exc: report.item(False, "文本模型 API", repr(exc), "核对 key、模型名、服务器网络和 API 配额")
        if settings.gemini_api_key:
            try:
                from PIL import Image
                from sqlmodel import Session
                from app.database import engine
                from app.services.imagegen import generate_image
                source, output = ROOT / "media" / "uploads" / "doctor_input.png", ROOT / "media" / "uploads" / "doctor_output.png"
                Image.new("RGB", (64, 64), "blue").save(source)
                with Session(engine) as session: generate_image(session, source, output, kind="basemap")
                report.item(output.exists(), "图像模型 API", "最小请求成功（计入底图配额 1 次）")
            except Exception as exc: report.item(False, "图像模型 API", repr(exc), "核对 GEMINI_API_KEY、GEMINI_IMAGE_MODEL、网络和月配额")
    log_file = ROOT / "logs" / "app.log"
    errors = [line for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if " ERROR " in line][-10:] if log_file.exists() else []
    print("\n=== 最近 10 条 ERROR ===")
    print("\n".join(errors) if errors else "无 ERROR 记录")
    print(f"\n体检结果：{'全部通过' if report.failed == 0 else f'{report.failed} 项需要处理'}")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__": raise SystemExit(main())
