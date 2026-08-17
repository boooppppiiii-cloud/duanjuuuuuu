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
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen
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
os.environ["FACTORY_MODEL_PROXY_ENABLED"] = "1"

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .app.config import get_settings
from .app.database import create_db_and_tables, engine
from .app.models import AppUser, Drama, FactoryJob, MetaDeliveryPackage, UsageEvent
from .app.routers.factory import router as factory_router
from .app.routers.meta_sfs import router as meta_sfs_router
from .app.services.auth import bind_current_user, reset_current_user
from .app.services.drama_library import IMAGE_SUFFIXES, VIDEO_SUFFIXES, episode_files, files_with_suffix
from .app.services.factory_processing import resume_factory_jobs
from .app.services.local_storage import LocalStorageEntry, list_local_storage, remove_storage_entry
from .app.services.meta_package_processing import ACTIVE_STATUSES as META_ACTIVE_STATUSES, resume_meta_packages
from .app.services.script_analysis import factory_analysis_pipeline, source_set_fingerprint, write_analysis
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
LEGACY_IMPORT_ROOT = APP_DIR / "legacy-server-sources"
LEGACY_SOURCE_HOSTS = {
    item.strip().casefold()
    for item in os.getenv("JUSHU_LEGACY_SOURCE_HOSTS", "app.duanju.chat,127.0.0.1,localhost").split(",")
    if item.strip()
}
_legacy_import_jobs: dict[str, dict] = {}
_legacy_import_lock = threading.Lock()
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


class LegacyImportFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    sequence: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=4096)


class LegacyImportRequest(WorkspaceBindRequest):
    factory_job_id: int = Field(gt=0)
    files: list[LegacyImportFile] = Field(min_length=1, max_length=999)


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


def _bind_workspace(payload: WorkspaceBindRequest, folder: Path, source_note: str) -> WorkspaceView:
    videos = [path for path in episode_files(folder) if path.suffix.lower() in VIDEO_SUFFIXES]
    if not videos:
        raise ValueError("该文件夹内没有找到支持的视频文件")
    with Session(engine) as session:
        duplicate = session.exec(select(Drama).where(Drama.file_dir == str(folder), Drama.id != payload.drama_id)).first()
        if duplicate:
            raise ValueError(f"该文件夹已连接到《{duplicate.title}》")
        drama = session.get(Drama, payload.drama_id)
        if drama is None:
            drama = Drama(id=payload.drama_id, title=payload.title.strip(), file_dir=str(folder))
        drama.title = payload.title.strip()
        drama.theater = payload.theater.strip()
        drama.description = payload.description.strip()
        drama.genres = payload.genres
        drama.language = payload.language
        drama.total_episode_count = payload.total_episode_count
        drama.promotion_episode_count = payload.total_episode_count
        drama.file_dir = str(folder)
        drama.source_note = source_note
        drama.episode_count = len(videos)
        _sync_local_covers(drama, folder)
        session.add(drama)
        session.commit()
        session.refresh(drama)
        return _workspace_view(drama)


def _legacy_source_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or (parsed.hostname or "").casefold() not in LEGACY_SOURCE_HOSTS:
        raise ValueError("旧成品下载地址不属于剧枢服务器")
    if not parsed.path.startswith("/api/meta-sfs/legacy-assets/"):
        raise ValueError("旧成品下载路径无效")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("旧成品下载必须使用 HTTPS")
    return value


def _legacy_job_update(job_id: str, **values) -> None:
    with _legacy_import_lock:
        if job_id in _legacy_import_jobs:
            _legacy_import_jobs[job_id].update(values, updated_at=datetime.utcnow().isoformat())


def _legacy_import_worker(job_id: str, payload: LegacyImportRequest) -> None:
    staging = LEGACY_IMPORT_ROOT / f".{payload.drama_id}-{job_id}.importing"
    target = LEGACY_IMPORT_ROOT / str(payload.drama_id)
    total_bytes = sum(item.size_bytes for item in payload.files)
    downloaded = 0
    try:
        LEGACY_IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
        reserve = max(1024 * 1024 * 1024, round(total_bytes * 0.1))
        if shutil.disk_usage(LEGACY_IMPORT_ROOT).free < total_bytes + reserve:
            raise ValueError(f"本机磁盘空间不足：迁移需要约 {round(total_bytes / 1024**3, 2)} GB，并需保留至少 1 GB 空闲空间")
        shutil.rmtree(staging, ignore_errors=True)
        episodes = staging / "episodes"
        episodes.mkdir(parents=True, exist_ok=False)
        _legacy_job_update(job_id, status="downloading", current_step="准备迁移服务器旧成品", progress=0)
        for index, item in enumerate(sorted(payload.files, key=lambda row: row.sequence), 1):
            safe_name = Path(item.name).name
            if safe_name != item.name or Path(safe_name).suffix.casefold() not in VIDEO_SUFFIXES:
                raise ValueError(f"旧成品文件名无效：{item.name}")
            destination = episodes / safe_name
            temporary = destination.with_suffix(destination.suffix + ".part")
            request = UrlRequest(_legacy_source_url(item.url), headers={"User-Agent": "Jushu-Local-Assistant/1.4"})
            _legacy_job_update(job_id, current_step=f"正在迁移第 {index}/{len(payload.files)} 集 · {safe_name}")
            with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    _legacy_job_update(job_id, bytes_downloaded=downloaded, progress=min(99, round(downloaded / max(total_bytes, 1) * 100)))
            actual_size = temporary.stat().st_size
            if actual_size != item.size_bytes:
                raise ValueError(f"{safe_name} 迁移不完整：应为 {item.size_bytes} 字节，实际 {actual_size} 字节")
            os.replace(temporary, destination)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        workspace = _bind_workspace(payload, target.resolve(), f"服务器旧成品已迁移到本机（任务 #{payload.factory_job_id}）")
        _legacy_job_update(
            job_id, status="completed", current_step="服务器旧成品已迁移到本机", progress=100,
            bytes_downloaded=downloaded, workspace=workspace.model_dump(),
        )
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _legacy_job_update(job_id, status="failed", current_step="迁移失败", error_message=str(exc)[:2000])


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
    capabilities = ["meta_direct_local_v2", "meta_progress", "meta_cover_sync", "legacy_server_import_v1", "factory_cancel_v1", "factory_sensitive_policy_v3", "factory_analysis_worker_v1", "factory_analysis_worker_v2", "factory_analysis_worker_v3", "factory_task_history_v1", "local_storage_manager_v1", "factory_model_proxy_v1", "meta_duration_guard_v1", "meta_metadata_guard_v1", "native_folder_picker_v1", "native_folder_picker_v2", "native_folder_picker_v3"]
    return {
        "status": "ok",
        "ffmpeg_ready": bool(shutil.which(get_settings().ffmpeg_binary)),
        "workspace_root": str(APP_DIR),
        "version": "1.15.0",
        "picker_backend": "IFileOpenDialog",
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
    try:
        return _bind_workspace(payload, folder, "本地工作区（源视频不上传）")
    except ValueError as exc:
        raise HTTPException(409 if "已连接" in str(exc) else 422, str(exc)) from exc


@app.post("/api/local/workspaces/import-legacy")
def import_legacy_workspace(payload: LegacyImportRequest):
    for item in payload.files:
        _legacy_source_url(item.url)
    with _legacy_import_lock:
        active = next((item for item in _legacy_import_jobs.values() if item.get("drama_id") == payload.drama_id and item.get("status") in {"queued", "downloading"}), None)
        if active:
            return active
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id, "drama_id": payload.drama_id, "status": "queued", "progress": 0,
            "current_step": "等待迁移服务器旧成品", "bytes_downloaded": 0,
            "total_bytes": sum(item.size_bytes for item in payload.files), "error_message": "",
            "workspace": None, "updated_at": datetime.utcnow().isoformat(),
        }
        _legacy_import_jobs[job_id] = job
    threading.Thread(target=_legacy_import_worker, args=(job_id, payload), name=f"jushu-legacy-import-{job_id[:8]}", daemon=True).start()
    return job


@app.get("/api/local/workspaces/import-legacy/{job_id}")
def legacy_workspace_import(job_id: str):
    with _legacy_import_lock:
        job = _legacy_import_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "旧成品迁移任务不存在")
        return dict(job)


@app.get("/api/local/workspaces/{drama_id}", response_model=WorkspaceView)
def get_workspace(drama_id: int):
    with Session(engine) as session:
        drama = session.get(Drama, drama_id)
        if not drama or not Path(drama.file_dir).is_dir():
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
        local_videos = episode_files(Path(drama.file_dir))
        local_names = {path.name for path in local_videos}
        analysis_names = {str(item.get("episode", "")) for item in episodes if isinstance(item, dict)}
        shared_fingerprint = str(payload.get("source_fingerprint") or "")
        if shared_fingerprint and source_set_fingerprint(local_videos) != shared_fingerprint:
            raise HTTPException(409, "共享识别结果对应的源视频内容不同，请重新识别")
        imported = dict(payload)
        imported_episodes = [dict(item) for item in episodes if isinstance(item, dict)]
        if local_names != analysis_names:
            if not shared_fingerprint or len(imported_episodes) != len(local_videos):
                raise HTTPException(409, "共享识别结果与当前本地文件不一致，请重新识别")
            for item, video in zip(imported_episodes, local_videos):
                item["episode"] = video.name
            imported["episodes"] = imported_episodes
            imported["source_files"] = [video.name for video in local_videos]
        imported.pop("task_id", None)
        imported.pop("owner_user_id", None)
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


def _storage_snapshot(session: Session) -> dict:
    settings = get_settings()
    whisper_cache = Path(settings.whisper_cache_dir).expanduser()
    if not whisper_cache.is_absolute():
        whisper_cache = (Path.cwd() / whisper_cache).resolve()
    dramas = session.exec(select(Drama).order_by(Drama.id)).all()
    return list_local_storage(
        dramas,
        app_dir=APP_DIR,
        legacy_root=LEGACY_IMPORT_ROOT,
        cover_root=LOCAL_COVER_ROOT,
        whisper_cache=whisper_cache,
    )


@app.get("/api/local/storage")
def local_storage():
    with Session(engine) as session:
        return _storage_snapshot(session)


@app.delete("/api/local/storage/{entry_id}")
def delete_local_storage(entry_id: str):
    with Session(engine) as session:
        snapshot = _storage_snapshot(session)
        raw = next((item for item in snapshot["items"] if item["id"] == entry_id), None)
        if not raw:
            raise HTTPException(404, "文件已不存在或已被清理")
        entry = LocalStorageEntry(**raw)
        if entry.id.startswith("legacy-staging:"):
            with _legacy_import_lock:
                importing = any(item.get("status") in {"queued", "downloading"} for item in _legacy_import_jobs.values())
            if importing:
                raise HTTPException(409, "旧素材正在迁移，请等待任务完成后再删除临时文件")
        if entry.drama_id:
            active_job = session.exec(select(FactoryJob).where(
                FactoryJob.drama_id == entry.drama_id,
                FactoryJob.status.in_(["queued", "processing", "cancel_requested"]),
            )).first()
            active_meta = session.exec(select(MetaDeliveryPackage).where(
                MetaDeliveryPackage.drama_id == entry.drama_id,
                MetaDeliveryPackage.status.in_(list(META_ACTIVE_STATUSES)),
            )).first()
            if active_job or active_meta or factory_analysis_pipeline.is_active(entry.drama_id):
                raise HTTPException(409, "该剧目仍有处理任务运行，请先取消或等待任务完成")
        elif entry.category == "model":
            dramas = session.exec(select(Drama)).all()
            if any(drama.id and factory_analysis_pipeline.is_active(int(drama.id)) for drama in dramas):
                raise HTTPException(409, "内容识别正在使用语音模型，请等待任务完成")
        try:
            freed = remove_storage_entry(entry)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if entry.category == "cache" and entry.drama_id:
            drama = session.get(Drama, entry.drama_id)
            if drama:
                root = Path(entry.path).resolve()
                for field in ("cover_vertical_path", "cover_square_path", "cover_horizontal_path"):
                    value = str(getattr(drama, field) or "")
                    if value:
                        path = Path(value).resolve()
                        if path == root or root in path.parents:
                            setattr(drama, field, "")
                session.add(drama)
                session.commit()
        elif entry.category == "material" and entry.drama_id:
            drama = session.get(Drama, entry.drama_id)
            if drama:
                drama.file_dir = str(APP_DIR / "disconnected" / f"drama-{entry.drama_id}-{uuid.uuid4().hex}")
                drama.episode_count = 0
                drama.source_note = "本机素材副本已删除，请重新选择源文件夹"
                session.add(drama)
                session.commit()
        return {"deleted": True, "freed_bytes": freed, **_storage_snapshot(session)}


def main() -> None:
    import uvicorn

    print("剧枢本地工作区已启动：http://127.0.0.1:17862")
    print("此窗口保持开启时，网页可直接处理本机视频；源视频不会上传到服务器。")
    uvicorn.run(app, host="127.0.0.1", port=17862, log_level="info")


if __name__ == "__main__":
    main()
