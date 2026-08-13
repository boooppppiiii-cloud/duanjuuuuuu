import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import AppUser, Clip, Drama, FactoryJob, GeneratedAsset
from ..schemas import DramaCreateRequest, DramaDetail, DramaUpdate, HighlightsPayload, LocalSourceManifestRequest, ManualRegisterRequest, ScanResult, UploadInitRequest, UploadInitResult
from ..services.drama_library import IMAGE_SUFFIXES, VIDEO_SUFFIXES, episode_files, files_with_suffix, read_highlights, scan_dramas_with_logs, write_highlights
from ..services.script_analysis import factory_analysis_pipeline
from ..services.uploads import UploadStore, validate_title
from ..services.auth import get_current_user

router = APIRouter(prefix="/api/dramas", tags=["剧库"])

COVER_SPECS = {
    "cover_vertical": ("cover_vertical_path", 3 / 4, 1440, 1920, "竖版封面必须为 3:4，且至少 1440x1920"),
    "cover_square": ("cover_square_path", 1.0, 1200, 1200, "方形封面必须为 1:1，且至少 1200x1200"),
    "cover_horizontal": ("cover_horizontal_path", 16 / 9, 1920, 1080, "横版封面必须为 16:9，且至少 1920x1080"),
}


def get_drama_or_404(drama_id: int, session: Session) -> Drama:
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return drama


def source_video_files(folder: Path) -> list[Path]:
    nested = files_with_suffix(folder / "episodes", VIDEO_SUFFIXES)
    return nested or files_with_suffix(folder, VIDEO_SUFFIXES)


def source_storage_info(folder: Path, sources: list[Path]) -> tuple[str, str]:
    settings = get_settings()
    hostname = (urlparse(settings.public_ui_origin).hostname or "").casefold()
    storage = "local" if hostname in {"", "localhost", "127.0.0.1", "::1"} else "server"
    source_folder = sources[0].parent if sources else (folder / "episodes" if (folder / "episodes").is_dir() else folder)
    if storage == "server":
        try:
            relative = source_folder.resolve().relative_to(settings.media_root.resolve())
            return storage, (Path("media") / relative).as_posix()
        except ValueError:
            pass
    return storage, str(source_folder.resolve())


def to_detail(drama: Drama) -> DramaDetail:
    media_root = get_settings().media_root
    folder = Path(drama.file_dir)
    episodes = episode_files(folder)
    source_files = source_video_files(folder)
    source_storage, source_storage_path = source_storage_info(folder, source_files)
    stills = files_with_suffix(folder / "stills", IMAGE_SUFFIXES)
    data = drama.model_dump()
    data["episode_count"] = max(len(episodes), drama.episode_count)
    data["total_episode_count"] = max(drama.total_episode_count, 1)
    return DramaDetail(
        **data,
        episodes=[path.name for path in episodes],
        source_files=[{"name": path.name, "size_bytes": path.stat().st_size} for path in source_files],
        source_size_bytes=sum(path.stat().st_size for path in source_files),
        source_storage=source_storage,
        source_storage_path=source_storage_path,
        stills=[DramaDetail.safe_relative(path, media_root) for path in stills],
        highlights=read_highlights(folder),
        generated_files=[],
    )


def to_list_detail(drama: Drama) -> DramaDetail:
    """Return database-backed card data without walking every media folder.

    The full filesystem inventory belongs to the single-drama detail endpoint.
    Keeping it out of the shared list makes navigation cost independent of the
    number and size of source videos stored on disk.
    """
    folder = Path(drama.file_dir)
    settings = get_settings()
    hostname = (urlparse(settings.public_ui_origin).hostname or "").casefold()
    source_storage = "local" if hostname in {"", "localhost", "127.0.0.1", "::1"} else "server"
    source_storage_path = "本地工作区" if drama.source_note.startswith("本地工作区") else "服务器共享素材"
    data = drama.model_dump()
    data["episode_count"] = max(drama.episode_count, 0)
    data["total_episode_count"] = max(drama.total_episode_count, 1)
    return DramaDetail(
        **data,
        episodes=[],
        source_files=[],
        source_size_bytes=0,
        source_storage=source_storage,
        source_storage_path=source_storage_path,
        stills=[],
        # Highlights are a small JSON sidecar used by the factory to prevent
        # duplicate adoptions. Reading it does not enumerate or stat videos.
        highlights=read_highlights(folder),
        generated_files=[],
    )


@router.post("", response_model=DramaDetail)
def create_drama_task(payload: DramaCreateRequest, session: Session = Depends(get_session)):
    try:
        title = validate_title(payload.title)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if session.exec(select(Drama).where(Drama.title == title)).first():
        raise HTTPException(409, "已存在同名剧目任务")
    folder = (get_settings().media_root / "dramas" / title).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise HTTPException(409, "本地已有同名素材文件夹，请使用“登记现有文件夹”")
    for name in ("episodes", "stills", "generated", "covers"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    drama = Drama(
        title=title,
        theater=payload.theater,
        description=payload.description.strip(),
        genres=payload.genres,
        is_ai_generated=payload.is_ai_generated,
        is_dubbed_content=payload.is_dubbed_content,
        file_dir=str(folder),
        source_note="剧目任务",
        language=payload.language,
        promotion_episode_count=payload.total_episode_count,
        total_episode_count=payload.total_episode_count,
    )
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.post("/scan", response_model=ScanResult)
def scan(session: Session = Depends(get_session)):
    items, logs = scan_dramas_with_logs(session, get_settings().media_root)
    return ScanResult(scan_root=str((get_settings().media_root / "dramas").resolve()), logs=logs, dramas=[to_detail(item) for item in items])


@router.post("/register", response_model=DramaDetail)
def manual_register(payload: ManualRegisterRequest, session: Session = Depends(get_session)):
    try: title = validate_title(payload.title)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    source = Path(payload.absolute_path).expanduser().resolve()
    folder = source.parent if source.is_file() else source
    if not source.exists(): raise HTTPException(422, f"路径不存在：{source}")
    videos = [source] if source.is_file() and source.suffix.lower() in VIDEO_SUFFIXES else episode_files(folder)
    if not videos: raise HTTPException(422, "路径存在，但没有找到支持的视频文件")
    existing = session.exec(select(Drama).where(Drama.title == title)).first()
    if existing and Path(existing.file_dir).resolve() != folder: raise HTTPException(409, f"已存在同名剧：{existing.file_dir}")
    drama = existing or Drama(title=title, file_dir=str(folder), source_note=payload.source_note)
    drama.file_dir, drama.source_note, drama.episode_count = str(folder), payload.source_note.strip(), len(videos)
    drama.theater = payload.theater
    if not drama.description.strip():
        drama.total_episode_count = max(drama.total_episode_count, len(videos))
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.post("/uploads/init", response_model=UploadInitResult)
def upload_init(payload: UploadInitRequest, user: AppUser = Depends(get_current_user)):
    try:
        settings = get_settings()
        upload_id, received = UploadStore(
            settings.media_root,
            max_file_size=settings.max_upload_file_bytes,
            free_space_reserve=settings.upload_free_space_reserve_bytes,
        ).init(payload, user.id)
        return UploadInitResult(upload_id=upload_id, received_chunks=received)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.put("/uploads/{upload_id}/chunks/{index}")
def upload_chunk(upload_id: str, index: int, data: bytes = Body(..., media_type="application/octet-stream"), user: AppUser = Depends(get_current_user)):
    try: return {"received_chunk": UploadStore(get_settings().media_root).write_chunk(upload_id, index, data, user.id)}
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/uploads/{upload_id}/complete", response_model=DramaDetail)
def upload_complete(upload_id: str, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    try: target, manifest = UploadStore(get_settings().media_root).complete(upload_id, user.id)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    destination = manifest.get("destination", "episodes")
    if destination in {"episodes", "stills"}:
        scan_dramas_with_logs(session, get_settings().media_root)
    drama = session.exec(select(Drama).where(Drama.title == manifest["drama_title"])).first()
    if not drama: raise HTTPException(500, "文件已落盘，但剧目入库失败，请点击目录扫描查看原因")
    if destination in COVER_SPECS:
        field, ratio, min_width, min_height, requirement = COVER_SPECS[destination]
        try:
            with Image.open(target) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("封面仅支持 JPEG 或 PNG")
                width, height = image.size
                if width < min_width or height < min_height or abs(width / height - ratio) > 0.01:
                    raise ValueError(f"{requirement}；当前为 {width}x{height}")
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        previous = Path(getattr(drama, field)) if getattr(drama, field) else None
        setattr(drama, field, str(target.resolve()))
        if previous and previous != target and previous.is_file():
            previous.unlink(missing_ok=True)
    elif destination == "publish":
        if target.suffix.lower() not in VIDEO_SUFFIXES:
            target.unlink(missing_ok=True)
            raise HTTPException(422, "本地发布文件仅支持视频格式")
        resolved = str(target.resolve())
        if not session.exec(select(Clip).where(Clip.file_path == resolved)).first():
            session.add(Clip(
                drama_id=drama.id,
                template_name="local_upload",
                source_eps=[target.name],
                source_start=0,
                source_end=0,
                duration=0,
                file_path=resolved,
                status="approved",
                progress=100,
                current_step="completed",
                asset_kind="publish",
                owner_user_id=user.id,
            ))
    drama.source_note = manifest["source_note"]
    drama.episode_count = len(episode_files(Path(drama.file_dir)))
    if not drama.description.strip():
        drama.total_episode_count = max(drama.total_episode_count, drama.episode_count, 1)
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.put("/{drama_id}/local-source-manifest", response_model=DramaDetail)
def register_local_source_manifest(
    drama_id: int,
    payload: LocalSourceManifestRequest,
    session: Session = Depends(get_session),
    _: AppUser = Depends(get_current_user),
):
    """Store metadata only; local video bytes and absolute paths never reach the server."""
    drama = get_drama_or_404(drama_id, session)
    drama.episode_count = payload.file_count
    drama.source_note = f"本地工作区 · {payload.folder_name}"
    if drama.total_episode_count <= 1:
        drama.total_episode_count = max(1, payload.file_count)
    session.add(drama)
    session.commit()
    session.refresh(drama)
    return to_detail(drama)


@router.get("", response_model=list[DramaDetail])
def list_dramas(session: Session = Depends(get_session)):
    return [to_list_detail(item) for item in session.exec(select(Drama).order_by(Drama.id.desc())).all()]


@router.get("/{drama_id}", response_model=DramaDetail)
def get_drama(drama_id: int, session: Session = Depends(get_session)):
    return to_detail(get_drama_or_404(drama_id, session))


@router.delete("/{drama_id}/source-files", response_model=DramaDetail)
def delete_source_files(
    drama_id: int,
    filename: str | None = None,
    session: Session = Depends(get_session),
    _: AppUser = Depends(get_current_user),
):
    drama = get_drama_or_404(drama_id, session)
    active_job = session.exec(
        select(FactoryJob).where(
            FactoryJob.drama_id == drama_id,
            FactoryJob.status.in_(["queued", "processing"]),
        )
    ).first()
    if active_job:
        raise HTTPException(409, f"加工任务 #{active_job.id} 正在运行，请完成后再删除源文件")

    folder = Path(drama.file_dir).resolve()
    analysis_path = folder / "factory_analysis.json"
    if factory_analysis_pipeline.is_active(drama_id):
        raise HTTPException(409, "内容识别正在运行，请完成后再删除源文件")

    sources = source_video_files(folder)
    if filename is not None:
        if not filename or Path(filename).name != filename:
            raise HTTPException(422, "源文件名不合法")
        sources = [path for path in sources if path.name == filename]
        if not sources:
            raise HTTPException(404, "源文件不存在")
    if not sources:
        raise HTTPException(404, "当前剧目没有可删除的源文件")

    allowed_parents = {folder, (folder / "episodes").resolve()}
    for source in sources:
        target = source.resolve()
        if target.parent not in allowed_parents or target.suffix.lower() not in VIDEO_SUFFIXES:
            raise HTTPException(422, "源文件路径超出剧目目录，已停止删除")
    for source in sources:
        source.unlink()

    drama.episode_count = len(episode_files(folder))
    session.add(drama)
    session.commit()
    session.refresh(drama)

    if analysis_path.is_file():
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            analysis["analysis_version"] = -1
            analysis["current_step"] = "源文件已变更，原识别记录已保留；重新识别后更新"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
            pass
    return to_detail(drama)


@router.get("/{drama_id}/generated/{filename:path}")
def get_generated_video(drama_id: int, filename: str, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = get_drama_or_404(drama_id, session)
    generated_dir = (Path(drama.file_dir) / "generated").resolve()
    target = (generated_dir / filename).resolve()
    asset = session.exec(select(GeneratedAsset).where(GeneratedAsset.drama_id == drama_id, GeneratedAsset.owner_user_id == user.id, GeneratedAsset.file_path == str(target))).first()
    if generated_dir not in target.parents or not target.is_file() or target.suffix.lower() not in VIDEO_SUFFIXES or not asset:
        raise HTTPException(404, "成品不存在")
    return FileResponse(target, filename=target.name)


@router.put("/{drama_id}", response_model=DramaDetail)
def update_drama(drama_id: int, payload: DramaUpdate, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        try:
            new_title = validate_title(changes.pop("title"))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        duplicate = session.exec(select(Drama).where(Drama.title == new_title, Drama.id != drama_id)).first()
        if duplicate:
            raise HTTPException(409, "已存在同名剧目任务")
        if new_title != drama.title:
            old_folder = Path(drama.file_dir).resolve()
            managed_root = (get_settings().media_root / "dramas").resolve()
            try:
                old_folder.relative_to(managed_root)
                new_folder = (managed_root / new_title).resolve()
                if new_folder.exists():
                    raise HTTPException(409, "新名称对应的本地文件夹已存在")
                old_folder.rename(new_folder)
                drama.file_dir = str(new_folder)
                for field in ("cover_vertical_path", "cover_square_path", "cover_horizontal_path"):
                    value = getattr(drama, field)
                    if value:
                        try:
                            setattr(drama, field, str(new_folder / Path(value).resolve().relative_to(old_folder)))
                        except ValueError:
                            pass
            except ValueError:
                pass
            except OSError as exc:
                raise HTTPException(422, f"本地剧目文件夹重命名失败：{exc}") from exc
            drama.title = new_title
    for key, value in changes.items():
        setattr(drama, key, value)
    session.add(drama)
    session.commit()
    session.refresh(drama)
    return to_detail(drama)


@router.get("/{drama_id}/covers/{kind}")
def get_cover(drama_id: int, kind: str, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    fields = {"vertical": "cover_vertical_path", "square": "cover_square_path", "horizontal": "cover_horizontal_path"}
    field = fields.get(kind)
    target = Path(getattr(drama, field, "")) if field else Path()
    if not field or not target.is_file():
        raise HTTPException(404, "封面不存在")
    return FileResponse(target)


@router.put("/{drama_id}/highlights", response_model=DramaDetail)
def update_highlights(drama_id: int, payload: HighlightsPayload, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    folder = Path(drama.file_dir)
    episodes = {path.name for path in episode_files(folder)}
    try:
        write_highlights(folder, payload.highlights, episodes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return to_detail(drama)


@router.get("/{drama_id}/stills/{filename}")
def get_still(drama_id: int, filename: str, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    stills_dir = (Path(drama.file_dir) / "stills").resolve()
    target = (stills_dir / Path(filename).name).resolve()
    if target.parent != stills_dir or not target.is_file() or target.suffix.lower() not in IMAGE_SUFFIXES:
        raise HTTPException(404, "剧照不存在")
    return FileResponse(target)
