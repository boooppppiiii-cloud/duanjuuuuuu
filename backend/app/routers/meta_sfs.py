from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import Drama, MetaDeliveryPackage
from ..schemas import MetaSFSRequest
from ..services.meta_sfs import build_package, preflight
from ..services.drive_delivery import upload_meta_package
from datetime import datetime
from pathlib import Path

router = APIRouter(prefix="/api/meta-sfs", tags=["Meta SFS 官方投递"])


@router.post("/preflight")
def check_package(payload: MetaSFSRequest, session: Session = Depends(get_session)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return preflight(drama, payload)


@router.post("/build")
def create_package(payload: MetaSFSRequest, session: Session = Depends(get_session)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    try:
        output_dir, report = build_package(drama, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Meta 投递包构建失败：{exc}") from exc
    item = MetaDeliveryPackage(drama_id=drama.id, series_slug=report["series_slug"], output_dir=str(output_dir.resolve()), status="ready", validation_json=report)
    session.add(item); session.commit(); session.refresh(item)
    return item


@router.get("/packages", response_model=list[MetaDeliveryPackage])
def list_packages(session: Session = Depends(get_session)):
    return session.exec(select(MetaDeliveryPackage).order_by(MetaDeliveryPackage.created_at.desc())).all()


@router.post("/packages/{package_id}/upload-drive", response_model=MetaDeliveryPackage)
def upload_package(package_id: int, session: Session = Depends(get_session)):
    item = session.get(MetaDeliveryPackage, package_id)
    if not item:
        raise HTTPException(404, "投递包不存在")
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
