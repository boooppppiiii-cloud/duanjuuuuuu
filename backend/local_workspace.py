"""Local-only video workspace for the hosted Jushu web UI.

Run with ``python -m backend.local_workspace``. Source videos and generated
assets stay on this computer; the hosted API receives only explicit metadata
and analysis synchronization requests made by the browser.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import uuid


APP_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Jushu" / "local-workspace"
APP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = os.getenv("JUSHU_LOCAL_DATABASE_URL", f"sqlite:///{(APP_DIR / 'workspace.db').as_posix()}")
os.environ["MEDIA_ROOT"] = os.getenv("JUSHU_LOCAL_MEDIA_ROOT", str(APP_DIR / "media"))
os.environ["CORS_ORIGINS"] = os.getenv(
    "JUSHU_LOCAL_CORS_ORIGINS",
    "https://app.duanju.chat,http://127.0.0.1:5174,http://localhost:5174",
)
os.environ["PUBLIC_API_ORIGIN"] = "http://127.0.0.1:17862"
os.environ["PUBLIC_UI_ORIGIN"] = "http://127.0.0.1:5174"

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .app.config import get_settings
from .app.database import create_db_and_tables, engine
from .app.models import AppUser, Drama, UsageEvent
from .app.routers.factory import router as factory_router
from .app.services.auth import bind_current_user, reset_current_user
from .app.services.drama_library import VIDEO_SUFFIXES, episode_files
from .app.services.factory_processing import resume_factory_jobs
from .app.services.script_analysis import write_analysis


LOCAL_USER_EMAIL = "local-workspace@jushu.invalid"
MACHINE_ID_FILE = APP_DIR / "machine-id"


def _machine_id() -> str:
    if MACHINE_ID_FILE.is_file():
        value = MACHINE_ID_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = uuid.uuid4().hex
    MACHINE_ID_FILE.write_text(value, encoding="utf-8")
    return value


class WorkspaceBindRequest(BaseModel):
    drama_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    theater: str = ""
    description: str = ""
    genres: list[str] = Field(default_factory=list)
    language: str = "en_US"
    total_episode_count: int = Field(default=1, ge=1)
    absolute_path: str = ""


class WorkspaceFile(BaseModel):
    name: str
    relative_path: str
    size_bytes: int


class WorkspaceView(BaseModel):
    drama_id: int
    title: str
    folder_name: str
    absolute_path: str
    file_count: int
    total_bytes: int
    files: list[WorkspaceFile]
    ffmpeg_ready: bool
    updated_at: str


def _local_user() -> AppUser:
    with Session(engine) as session:
        user = session.exec(select(AppUser).where(AppUser.email == LOCAL_USER_EMAIL)).first()
        if user:
            return user
        user = AppUser(
            email=LOCAL_USER_EMAIL,
            password_hash="local-workspace-no-login",
            is_active=True,
            email_verified=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def _pick_folder() -> Path | None:
    if os.name != "nt":
        return None
    script = """
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择短剧源文件夹（视频不会上传）'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output $dialog.SelectedPath
}
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    value = completed.stdout.strip()
    return Path(value).resolve() if value else None


def _workspace_view(drama: Drama) -> WorkspaceView:
    folder = Path(drama.file_dir).resolve()
    if not folder.is_dir():
        raise HTTPException(404, "本机文件夹已移动或当前无法访问，请重新选择")
    videos = episode_files(folder)
    files = [
        WorkspaceFile(
            name=path.name,
            relative_path=path.resolve().relative_to(folder).as_posix(),
            size_bytes=path.stat().st_size,
        )
        for path in videos
    ]
    return WorkspaceView(
        drama_id=int(drama.id),
        title=drama.title,
        folder_name=folder.name,
        absolute_path=str(folder),
        file_count=len(files),
        total_bytes=sum(item.size_bytes for item in files),
        files=files,
        ffmpeg_ready=bool(shutil.which(get_settings().ffmpeg_binary) and shutil.which(get_settings().ffprobe_binary)),
        updated_at=datetime.utcnow().isoformat(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    _local_user()
    resume_factory_jobs()
    yield


app = FastAPI(title="剧枢本地工作区", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_identity_and_private_network(request: Request, call_next):
    user = _local_user()
    request.state.user = user
    token = bind_current_user(int(user.id))
    try:
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        reset_current_user(token)


app.include_router(factory_router)


@app.get("/api/local/health")
def health():
    return {
        "status": "ok",
        "ffmpeg_ready": bool(shutil.which(get_settings().ffmpeg_binary)),
        "workspace_root": str(APP_DIR),
    }


@app.post("/api/local/workspaces/select", response_model=WorkspaceView)
def select_workspace(payload: WorkspaceBindRequest):
    folder = Path(payload.absolute_path).expanduser().resolve() if payload.absolute_path else _pick_folder()
    if folder is None:
        raise HTTPException(409, "已取消选择文件夹")
    if not folder.is_dir():
        raise HTTPException(422, "选择的本地文件夹不存在")
    videos = [path for path in episode_files(folder) if path.suffix.lower() in VIDEO_SUFFIXES]
    if not videos:
        raise HTTPException(422, "该文件夹内没有找到支持的视频文件")
    with Session(engine) as session:
        duplicate = session.exec(select(Drama).where(Drama.file_dir == str(folder), Drama.id != payload.drama_id)).first()
        if duplicate:
            raise HTTPException(409, f"该文件夹已连接到《{duplicate.title}》")
        drama = session.get(Drama, payload.drama_id)
        if drama is None:
            drama = Drama(
                id=payload.drama_id,
                title=payload.title.strip(),
                file_dir=str(folder),
            )
        drama.title = payload.title.strip()
        drama.theater = payload.theater.strip()
        drama.description = payload.description.strip()
        drama.genres = payload.genres
        drama.language = payload.language
        drama.total_episode_count = payload.total_episode_count
        drama.promotion_episode_count = payload.total_episode_count
        drama.file_dir = str(folder)
        drama.source_note = "本地工作区（源视频不上传）"
        drama.episode_count = len(videos)
        session.add(drama)
        session.commit()
        session.refresh(drama)
        return _workspace_view(drama)


@app.get("/api/local/workspaces/{drama_id}", response_model=WorkspaceView)
def get_workspace(drama_id: int):
    with Session(engine) as session:
        drama = session.get(Drama, drama_id)
        if not drama:
            raise HTTPException(404, "本机尚未连接该剧目的源文件夹")
        return _workspace_view(drama)


@app.put("/api/local/workspaces/{drama_id}/analysis")
def import_shared_analysis(drama_id: int, payload: dict):
    with Session(engine) as session:
        drama = session.get(Drama, drama_id)
        if not drama:
            raise HTTPException(404, "请先连接该剧目的本地源文件夹")
        episodes = payload.get("episodes")
        if payload.get("status") != "completed" or not isinstance(episodes, list):
            raise HTTPException(422, "只能复用已完成的共享识别结果")
        local_names = {path.name for path in episode_files(Path(drama.file_dir))}
        analysis_names = {str(item.get("episode", "")) for item in episodes if isinstance(item, dict)}
        if local_names != analysis_names:
            raise HTTPException(409, "共享识别结果与当前本地文件名不一致，请重新识别")
        imported = dict(payload)
        imported["drama_id"] = drama_id
        imported["title"] = drama.title
        imported["reused_from_cloud"] = True
        return write_analysis(Path(drama.file_dir), imported)


@app.get("/api/local/usage/model-events")
def local_model_usage():
    user = _local_user()
    with Session(engine) as session:
        rows = session.exec(
            select(UsageEvent).where(
                UsageEvent.user_id == user.id,
                UsageEvent.event_kind == "model_call",
            ).order_by(UsageEvent.id.desc()).limit(500)
        ).all()
    machine_id = _machine_id()
    return [{
        "client_event_id": f"local-model:{machine_id}:{row.id}",
        "feature": row.feature,
        "success": row.success,
        "duration_ms": row.duration_ms,
        "event_kind": "model_call",
        "provider": row.provider,
        "model": row.model,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "api_calls": row.api_calls,
        "details": {**row.details_json, "local_created_at": row.created_at.isoformat()},
    } for row in reversed(rows)]


def main() -> None:
    import uvicorn

    print("剧枢本地工作区已启动：http://127.0.0.1:17862")
    print("此窗口保持开启时，网页可直接处理本机视频；源视频不会上传到服务器。")
    uvicorn.run(app, host="127.0.0.1", port=17862, log_level="info")


if __name__ == "__main__":
    main()
