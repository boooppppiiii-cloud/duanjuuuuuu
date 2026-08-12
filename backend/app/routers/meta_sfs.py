import hashlib
import hmac
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..database import get_session
from ..config import get_settings
from ..models import AppUser, Drama, FactoryJob, GeneratedAsset, MetaDeliveryPackage
from ..schemas import MetaSFSRequest
from ..services.meta_sfs import delivery_sources, preflight
from ..services.meta_package_processing import ACTIVE_STATUSES, meta_package_pipeline
from ..services.drive_delivery import upload_meta_package
from ..services.auth import get_current_user
from ..services.windows_folder_picker import FolderPickerBusy, FolderPickerCancelled, FolderPickerError, pick_windows_folder

router = APIRouter(prefix="/api/meta-sfs", tags=["Meta SFS 官方投递"])
_local_destinations: dict[str, tuple[Path, float]] = {}
LEGACY_ASSET_TICKET_TTL_SECONDS = 6 * 60 * 60


def _legacy_factory_assets(session: Session, drama: Drama, user: AppUser) -> tuple[FactoryJob | None, list[GeneratedAsset]]:
    latest = session.exec(select(FactoryJob).where(
        FactoryJob.drama_id == drama.id, FactoryJob.owner_user_id == user.id,
        FactoryJob.status == "completed", FactoryJob.meta_count > 0,
    ).order_by(FactoryJob.id.desc())).first()
    if not latest:
        return None, []
    assets = session.exec(select(GeneratedAsset).where(
        GeneratedAsset.factory_job_id == latest.id, GeneratedAsset.owner_user_id == user.id,
        GeneratedAsset.kind == "meta_episode",
    ).order_by(GeneratedAsset.sequence)).all()
    available = [item for item in assets if Path(item.file_path).resolve().is_file()]
    return latest, available if len(available) == len(assets) else []


def _legacy_ticket(asset: GeneratedAsset, user: AppUser, expires_at: int) -> str:
    secret = get_settings().credential_secret
    if not secret:
        raise HTTPException(503, "服务器尚未配置旧成品迁移签名密钥")
    message = f"{asset.id}:{user.id}:{expires_at}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{user.id}.{expires_at}.{signature}"


def _validate_legacy_ticket(asset: GeneratedAsset, ticket: str) -> None:
    try:
        raw_user_id, raw_expires_at, supplied = ticket.split(".", 2)
        user_id = int(raw_user_id)
        expires_at = int(raw_expires_at)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(403, "旧成品迁移链接无效") from exc
    if expires_at < int(time.time()) or asset.owner_user_id != user_id:
        raise HTTPException(403, "旧成品迁移链接已过期")
    secret = get_settings().credential_secret
    message = f"{asset.id}:{user_id}:{expires_at}"
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, "旧成品迁移链接无效")


def _package_root(item: MetaDeliveryPackage) -> Path:
    if item.status in ACTIVE_STATUSES:
        raise HTTPException(409, "投递文件夹仍在生成中")
    if item.status == "failed":
        raise HTTPException(422, item.last_error or "投递文件夹生成失败")
    root = Path(item.output_dir).resolve()
    if not root.is_dir():
        raise HTTPException(404, "投递文件夹不存在或尚未生成完成")
    return root


def _owned_package(package_id: int, session: Session, user: AppUser) -> MetaDeliveryPackage:
    item = session.get(MetaDeliveryPackage, package_id)
    if not item or item.owner_user_id != user.id:
        raise HTTPException(404, "投递文件夹不存在")
    return item


def _delivery_for_user(session: Session, drama: Drama, user: AppUser) -> tuple[list[Path], str]:
    _, assets = _legacy_factory_assets(session, drama, user)
    if assets:
        paths = [Path(item.file_path).resolve() for item in assets]
        return paths, "factory_meta_split"
    if os.getenv("JUSHU_LOCAL_WORKSPACE") == "1":
        return delivery_sources(Path(drama.file_dir).resolve())
    return [], "factory_meta_split"


@router.get("/legacy-source/{drama_id}")
def legacy_server_source(drama_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    """Issue short-lived download links for Meta episodes created by the legacy server pipeline."""
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    job, assets = _legacy_factory_assets(session, drama, user)
    expires_at = int(time.time()) + LEGACY_ASSET_TICKET_TTL_SECONDS
    files = [
        {
            "name": item.filename,
            "size_bytes": item.size_bytes or Path(item.file_path).stat().st_size,
            "sequence": item.sequence,
            "url": f"/api/meta-sfs/legacy-assets/{item.id}?ticket={_legacy_ticket(item, user, expires_at)}",
        }
        for item in assets
    ]
    return {
        "ready": bool(files),
        "factory_job_id": int(job.id) if job and job.id else 0,
        "episode_count": len(files),
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
        "expires_at": expires_at,
        "files": files,
    }


@router.get("/legacy-assets/{asset_id}")
def download_legacy_asset(asset_id: int, ticket: str, session: Session = Depends(get_session)):
    asset = session.get(GeneratedAsset, asset_id)
    if not asset or asset.kind != "meta_episode":
        raise HTTPException(404, "旧成品不存在")
    _validate_legacy_ticket(asset, ticket)
    drama = session.get(Drama, asset.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    path = Path(asset.file_path).resolve()
    root = (Path(drama.file_dir) / "generated").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "旧成品文件不存在")
    return FileResponse(path, filename=asset.filename, media_type="video/mp4")


@router.get("/source/{drama_id}")
def factory_delivery_source(drama_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    paths, source_mode = _delivery_for_user(session, drama, user)
    return {
        "ready": bool(paths),
        "episode_count": len(paths),
        "source_episode_count": drama.episode_count,
        "source_mode": source_mode,
        "files": [path.name for path in paths],
    }


def _package_file(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "文件路径无效") from exc
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return target


def _create_package_archive(root: Path, export_root: Path, reserve_bytes: int) -> Path:
    total_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    export_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(export_root).free < total_bytes + reserve_bytes:
        raise HTTPException(507, "服务器空间不足，无法创建本机下载包；请先清理旧投递包")
    descriptor, archive_name = tempfile.mkstemp(prefix=f"{root.name}_", suffix=".zip", dir=export_root)
    os.close(descriptor)
    archive = Path(archive_name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as output:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    output.write(path, arcname=(Path(root.name) / path.relative_to(root)).as_posix())
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return archive


def _take_local_destination(token: str) -> Path | None:
    if not token:
        return None
    selected = _local_destinations.pop(token, None)
    if not selected or selected[1] < time.monotonic():
        raise HTTPException(422, "保存位置授权已过期，请重新选择")
    path = selected[0]
    if not path.is_dir():
        raise HTTPException(422, "选择的保存位置已不存在")
    return path


@router.post("/select-local-directory")
def select_local_directory(request: Request):
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "只有本地运行时可以调用系统文件夹选择器")
    try:
        path = pick_windows_folder("选择 Meta 合规文件夹保存位置")
    except FolderPickerCancelled as exc:
        raise HTTPException(409, "已取消选择保存位置") from exc
    except FolderPickerBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except FolderPickerError as exc:
        raise HTTPException(422, str(exc)) from exc
    token = secrets.token_urlsafe(24)
    _local_destinations[token] = (path, time.monotonic() + 15 * 60)
    return {"token": token, "name": path.name or str(path)}


@router.post("/preflight")
def check_package(payload: MetaSFSRequest, quick: bool = False, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return preflight(drama, payload, _delivery_for_user(session, drama, user), not quick)


@router.post("/build", response_model=MetaDeliveryPackage, status_code=202)
def create_package(payload: MetaSFSRequest, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    if os.getenv("JUSHU_LOCAL_WORKSPACE") != "1":
        raise HTTPException(422, "Meta 官方投递只允许由用户电脑上的剧枢本地助手生成，服务器不会保存投递成品")
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    active = session.exec(select(MetaDeliveryPackage).where(
        MetaDeliveryPackage.drama_id == drama.id,
        MetaDeliveryPackage.owner_user_id == user.id,
        MetaDeliveryPackage.status.in_(ACTIVE_STATUSES),
    ).order_by(MetaDeliveryPackage.id.desc())).first()
    if active:
        raise HTTPException(409, f"该剧已有投递文件夹任务 #{active.id} 正在生成")
    delivery = _delivery_for_user(session, drama, user)
    # Keep the request short. Full ffprobe validation and conversion happen in
    # the persisted job so the browser always gets a visible task immediately.
    report = preflight(drama, payload, delivery, False)
    if report["blockers"]:
        raise HTTPException(422, "；".join(report["blockers"]))
    output_parent = _take_local_destination(payload.local_destination_token)
    if output_parent is None:
        raise HTTPException(422, "请先选择本机保存位置；Meta 投递成品不会保存到服务器或本地助手缓存目录")
    request_data = payload.model_dump()
    request_data["series_slug"] = report["series_slug"]
    request_data["local_destination_token"] = ""
    item = MetaDeliveryPackage(
        drama_id=drama.id,
        series_slug=report["series_slug"],
        output_dir="",
        status="queued",
        validation_json={
            "request": request_data,
            "source_paths": [str(path) for path in delivery[0]],
            "output_parent": str(output_parent) if output_parent else "",
            "progress": 0,
            "current_step": "等待本机生成",
        },
        owner_user_id=user.id,
    )
    session.add(item); session.commit(); session.refresh(item)
    meta_package_pipeline.start()
    return item


@router.get("/packages", response_model=list[MetaDeliveryPackage])
def list_packages(session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    items = session.exec(select(MetaDeliveryPackage).where(MetaDeliveryPackage.owner_user_id == user.id).order_by(MetaDeliveryPackage.created_at.desc())).all()
    changed = False
    for item in items:
        if item.status in (*ACTIVE_STATUSES, "failed") or not item.output_dir:
            continue
        available = Path(item.output_dir).is_dir()
        if not available and item.status != "missing":
            item.status = "missing"
            session.add(item)
            changed = True
        elif available and item.status == "missing":
            item.status = "ready"
            session.add(item)
            changed = True
    if changed:
        session.commit()
        for item in items:
            session.refresh(item)
    return items


@router.get("/packages/{package_id}", response_model=MetaDeliveryPackage)
def get_package(package_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    return _owned_package(package_id, session, user)


@router.get("/packages/{package_id}/files")
def list_package_files(package_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    root = _package_root(item)
    files = [
        {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return {"folder_name": root.name, "total_bytes": sum(file["size"] for file in files), "files": files}


@router.get("/packages/{package_id}/files/{relative_path:path}")
def download_package_file(package_id: int, relative_path: str, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    target = _package_file(_package_root(item), relative_path)
    return FileResponse(target, filename=target.name)


@router.get("/packages/{package_id}/archive")
def download_package_archive(package_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    root = _package_root(item)
    settings = get_settings()
    archive = _create_package_archive(root, settings.media_root / "downloads", settings.upload_free_space_reserve_bytes)
    background_tasks.add_task(archive.unlink, missing_ok=True)
    return FileResponse(archive, media_type="application/zip", filename=f"{root.name}.zip", background=background_tasks)


@router.post("/packages/{package_id}/open-folder")
def open_package_folder(package_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    root = _package_root(item)
    try:
        if sys.platform == "win32":
            os.startfile(str(root))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except Exception as exc:
        raise HTTPException(422, f"无法打开本地文件夹：{exc}") from exc
    return {"opened": True, "path": str(root)}


@router.post("/packages/{package_id}/copy-local")
def copy_package_local(package_id: int, token: str, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    source = _package_root(item)
    destination_parent = _take_local_destination(token)
    if destination_parent is None:
        raise HTTPException(422, "请重新选择保存位置")
    destination = destination_parent / source.name
    if destination.resolve() == source:
        return {"path": str(source), "folder_name": source.name}
    if destination.exists():
        destination = destination_parent / f"{source.name}_copy_{datetime.now():%Y%m%d_%H%M%S}"
    try:
        shutil.copytree(source, destination)
    except Exception as exc:
        raise HTTPException(500, f"复制合规文件夹失败：{exc}") from exc
    return {"path": str(destination.resolve()), "folder_name": destination.name}


@router.post("/packages/{package_id}/upload-drive", response_model=MetaDeliveryPackage)
def upload_package(package_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    item = _owned_package(package_id, session, user)
    item.status = "uploading"; item.last_error = ""
    session.add(item); session.commit()
    try:
        folder_id, url = upload_meta_package(Path(item.output_dir))
        item.drive_folder_id = folder_id; item.drive_folder_url = url
        item.status = "drive_ready"; item.uploaded_at = datetime.now()
    except Exception as exc:
        item.status = "upload_failed"; item.last_error = str(exc)[:2000]
        session.add(item); session.commit(); session.refresh(item)
        raise HTTPException(422, item.last_error) from exc
    session.add(item); session.commit(); session.refresh(item)
    return item
