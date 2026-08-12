"""Local-only video workspace for the hosted Jushu web UI.

Run with ``python -m backend.local_workspace``. Source videos and generated
assets stay on this computer; the hosted API receives only explicit metadata
and analysis synchronization requests made by the browser.
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
import shutil
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
os.environ["JUSHU_LOCAL_WORKSPACE"] = "1"

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .app.config import get_settings
from .app.database import create_db_and_tables, engine
from .app.models import AppUser, Drama, UsageEvent
from .app.routers.factory import router as factory_router
from .app.routers.meta_sfs import router as meta_sfs_router
from .app.services.auth import bind_current_user, reset_current_user
from .app.services.drama_library import IMAGE_SUFFIXES, VIDEO_SUFFIXES, episode_files, files_with_suffix
from .app.services.factory_processing import resume_factory_jobs
from .app.services.meta_package_processing import resume_meta_packages
from .app.services.script_analysis import write_analysis
from .app.services.windows_folder_picker import (
    FolderPickerBusy,
    FolderPickerCancelled,
    FolderPickerError,
    folder_picker_environment,
    pick_windows_folder,
)


LOCAL_USER_EMAIL = "local-workspace@jushu.invalid"
MACHINE_ID_FILE = APP_DIR / "machine-id"
LOCAL_COVER_ROOT = APP_DIR / "covers"
LOCAL_COVER_SPECS = {
    "vertical": ("cover_vertical_path", 3 / 4, 1440, 1920, "竖版封面必须为 3:4，且至少 1440x1920"),
    "square": ("cover_square_path", 1.0, 1200, 1200, "方形封面必须为 1:1，且至少 1200x1200"),
    "horizontal": ("cover_horizontal_path", 16 / 9, 1920, 1080, "横版封面必须为 16:9，且至少 1920x1080"),
}


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
    covers: dict[str, str]
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
    try:
        return pick_windows_folder("选择短剧源文件夹（视频不会上传）")
    except FolderPickerCancelled:
        return None


def _discover_covers(folder: Path) -> dict[str, Path]:
    """Find Meta-ready covers beside the selected videos without copying them."""
    candidates: list[Path] = []
    for candidate_folder in (folder / "covers", folder, folder / "stills"):
        candidates.extend(files_with_suffix(candidate_folder, IMAGE_SUFFIXES))
    specs = {
        "vertical": (3 / 4, 1440, 1920, ("vertical", "portrait", "竖", "3x4", "3-4")),
        "square": (1.0, 1200, 1200, ("square", "方", "1x1", "1-1")),
        "horizontal": (16 / 9, 1920, 1080, ("horizontal", "landscape", "横", "16x9", "16-9", "background")),
    }
    matches: dict[str, list[tuple[int, int, Path]]] = {kind: [] for kind in specs}
    for path in dict.fromkeys(candidates):
        try:
            with Image.open(path) as image:
                if image.format not in {"JPEG", "PNG"}:
                    continue
                width, height = image.size
        except Exception:
            continue
        name = path.stem.casefold()
        for kind, (ratio, min_width, min_height, hints) in specs.items():
            if width >= min_width and height >= min_height and abs(width / height - ratio) <= 0.01:
                matches[kind].append((0 if any(hint in name for hint in hints) else 1, width * height, path.resolve()))
    return {
        kind: min(rows, key=lambda row: (row[0], row[1], row[2].name.casefold()))[2]
        for kind, rows in matches.items()
        if rows
    }


def _sync_local_covers(drama: Drama, folder: Path) -> None:
    covers = _discover_covers(folder)
    for kind, field in (
        ("vertical", "cover_vertical_path"),
        ("square", "cover_square_path"),
        ("horizontal", "cover_horizontal_path"),
    ):
        discovered = covers.get(kind)
        current = Path(str(getattr(drama, field) or ""))
        setattr(drama, field, str(discovered or (current if current.is_file() else "")))


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
        covers={
            "vertical": Path(drama.cover_vertical_path).name if drama.cover_vertical_path else "",
            "square": Path(drama.cover_square_path).name if drama.cover_square_path else "",
            "horizontal": Path(drama.cover_horizontal_path).name if drama.cover_horizontal_path else "",
        },
        ffmpeg_ready=bool(shutil.which(get_settings().ffmpeg_binary) and shutil.which(get_settings().ffprobe_binary)),
        updated_at=datetime.utcnow().isoformat(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    _local_user()
    resume_factory_jobs()
    resume_meta_packages()
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
app.include_router(meta_sfs_router)


@app.get("/api/local/health")
def health():
    picker = folder_picker_environment()
    capabilities = ["meta_direct_local_v2", "meta_progress", "meta_cover_sync", "native_folder_picker_v1", "native_folder_picker_v2"]
    return {
        "status": "ok",
        "ffmpeg_ready": bool(shutil.which(get_settings().ffmpeg_binary)),
        "workspace_root": str(APP_DIR),
        "version": "1.2.1",
        "picker_ready": picker.ready,
        "picker_reason": picker.reason,
        "windows_user": os.getenv("USERNAME", ""),
        "session_id": picker.session_id,
        "session_state": picker.session_state,
        "interactive_user": picker.interactive_user,
        "shell_session_id": picker.shell_session_id,
        "active_console_session_id": picker.active_console_session_id,
        "capabilities": capabilities,
    }


@app.post("/api/local/workspaces/select", response_model=WorkspaceView)
def select_workspace(payload: WorkspaceBindRequest):
    try:
        folder = Path(payload.absolute_path).expanduser().resolve() if payload.absolute_path else _pick_folder()
    except FolderPickerBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except FolderPickerError as exc:
        raise HTTPException(422, str(exc)) from exc
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
        _sync_local_covers(drama, folder)
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
        _sync_local_covers(drama, Path(drama.file_dir).resolve())
        session.add(drama)
        session.commit()
        session.refresh(drama)
        return _workspace_view(drama)


@app.put("/api/local/workspaces/{drama_id}/covers/{kind}", response_model=WorkspaceView)
async def sync_workspace_cover(drama_id: int, kind: str, request: Request):
    spec = LOCAL_COVER_SPECS.get(kind)
    if not spec:
        raise HTTPException(404, "不支持的封面类型")
    data = await request.body()
    if not data:
        raise HTTPException(422, "封面文件为空")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "封面文件不能超过 25MB")
    field, ratio, min_width, min_height, requirement = spec
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("封面仅支持 JPEG 或 PNG")
            width, height = image.size
            if width < min_width or height < min_height or abs(width / height - ratio) > 0.01:
                raise ValueError(f"{requirement}；当前为 {width}x{height}")
            suffix = ".jpg" if image.format == "JPEG" else ".png"
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc

    with Session(engine) as session:
        drama = session.get(Drama, drama_id)
        if not drama:
            raise HTTPException(404, "请先连接该剧目的本地源文件夹")
        target_dir = (LOCAL_COVER_ROOT / str(drama_id)).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{kind}{suffix}"
        temporary = target_dir / f".{kind}-{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, target)
        previous_value = str(getattr(drama, field) or "")
        previous = Path(previous_value).resolve() if previous_value else None
        setattr(drama, field, str(target))
        session.add(drama)
        session.commit()
        session.refresh(drama)
        if previous and previous != target and previous.is_file() and target_dir in previous.parents:
            previous.unlink(missing_ok=True)
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
