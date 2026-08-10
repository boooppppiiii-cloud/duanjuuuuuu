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
from ..services.meta_sfs import build_package, preflight
from ..services.drive_delivery import upload_meta_package
from ..services.auth import get_current_user
from ..services.drama_library import episode_files

router = APIRouter(prefix="/api/meta-sfs", tags=["Meta SFS 官方投递"])
_local_destinations: dict[str, tuple[Path, float]] = {}


def _package_root(item: MetaDeliveryPackage) -> Path:
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
    latest = session.exec(select(FactoryJob).where(
        FactoryJob.drama_id == drama.id, FactoryJob.owner_user_id == user.id,
        FactoryJob.status == "completed", FactoryJob.meta_count > 0,
    ).order_by(FactoryJob.id.desc())).first()
    if latest:
        assets = session.exec(select(GeneratedAsset).where(
            GeneratedAsset.factory_job_id == latest.id, GeneratedAsset.owner_user_id == user.id,
            GeneratedAsset.kind == "meta_episode",
        ).order_by(GeneratedAsset.sequence)).all()
        paths = [Path(item.file_path).resolve() for item in assets]
        if paths and all(path.is_file() for path in paths):
            return paths, "factory_meta_split"
    return episode_files(Path(drama.file_dir)), "source_episodes"


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
    if sys.platform != "win32":
        raise HTTPException(422, "当前环境不支持系统文件夹选择器，请使用 Chrome 或 Edge")
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(parent=root, title="选择 Meta 合规文件夹保存位置", mustexist=True)
        root.destroy()
    except Exception as exc:
        raise HTTPException(422, f"无法打开文件夹选择器：{exc}") from exc
    if not selected:
        raise HTTPException(409, "已取消选择保存位置")
    path = Path(selected).resolve()
    token = secrets.token_urlsafe(24)
    _local_destinations[token] = (path, time.monotonic() + 15 * 60)
    return {"token": token, "name": path.name or str(path)}


@router.post("/preflight")
def check_package(payload: MetaSFSRequest, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return preflight(drama, payload, _delivery_for_user(session, drama, user))


@router.post("/build")
def create_package(payload: MetaSFSRequest, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    try:
        output_dir, report = build_package(drama, payload, output_parent=_take_local_destination(payload.local_destination_token), delivery=_delivery_for_user(session, drama, user))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Meta 投递包构建失败：{exc}") from exc
    item = MetaDeliveryPackage(drama_id=drama.id, series_slug=report["series_slug"], output_dir=str(output_dir.resolve()), status="ready", validation_json=report, owner_user_id=user.id)
    session.add(item); session.commit(); session.refresh(item)
    return item


@router.get("/packages", response_model=list[MetaDeliveryPackage])
def list_packages(session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    items = session.exec(select(MetaDeliveryPackage).where(MetaDeliveryPackage.owner_user_id == user.id).order_by(MetaDeliveryPackage.created_at.desc())).all()
    changed = False
    for item in items:
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
