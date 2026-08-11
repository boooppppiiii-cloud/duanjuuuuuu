from __future__ import annotations

import os
import threading
from pathlib import Path

from sqlmodel import Session, select

from .. import database
from ..models import Drama, MetaDeliveryPackage
from ..schemas import MetaSFSRequest
from .meta_sfs import build_package


ACTIVE_STATUSES = ("queued", "building")


class MetaPackagePipeline:
    """Build Meta packages outside the request lifecycle.

    The database row is created before work starts, so a browser refresh or a
    disconnected proxy cannot cancel the build or hide its outcome.
    """

    def __init__(self) -> None:
        self._start_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self.process_queued, name="meta-package-builder", daemon=True)
            self._thread.start()

    def process_queued(self) -> None:
        while True:
            with Session(database.engine) as session:
                item = session.exec(
                    select(MetaDeliveryPackage)
                    .where(MetaDeliveryPackage.status == "queued")
                    .order_by(MetaDeliveryPackage.id)
                ).first()
                if not item:
                    return
                package_id = int(item.id)
                item.status = "building"
                item.last_error = ""
                item.validation_json = {
                    **dict(item.validation_json or {}),
                    "progress": 1,
                    "current_step": "本机任务已启动",
                }
                session.add(item)
                session.commit()
                session.refresh(item)
                build_state = dict(item.validation_json or {})
                drama = session.get(Drama, item.drama_id)

            try:
                if not drama:
                    raise RuntimeError("剧目不存在")
                payload_data = dict(build_state.get("request") or {})
                payload_data["local_destination_token"] = ""
                payload = MetaSFSRequest(**payload_data)
                source_paths = [Path(value).resolve() for value in build_state.get("source_paths") or []]
                output_parent_value = str(build_state.get("output_parent") or "").strip()
                output_parent = Path(output_parent_value).resolve() if output_parent_value else None

                def update_progress(progress: int, current_step: str) -> None:
                    with Session(database.engine) as progress_session:
                        current = progress_session.get(MetaDeliveryPackage, package_id)
                        if not current:
                            return
                        current.validation_json = {
                            **dict(current.validation_json or {}),
                            "progress": progress,
                            "current_step": current_step,
                        }
                        progress_session.add(current)
                        progress_session.commit()

                output_dir, report = build_package(
                    drama,
                    payload,
                    output_parent=output_parent,
                    delivery=(source_paths, "factory_meta_split"),
                    progress_callback=update_progress,
                )
            except Exception as exc:
                with Session(database.engine) as session:
                    failed = session.get(MetaDeliveryPackage, package_id)
                    if failed:
                        failed.status = "failed"
                        failed.last_error = str(exc)[-2000:]
                        failed.validation_json = {
                            **dict(failed.validation_json or {}),
                            "current_step": "生成失败",
                        }
                        session.add(failed)
                        session.commit()
                continue

            with Session(database.engine) as session:
                completed = session.get(MetaDeliveryPackage, package_id)
                if completed:
                    completed.output_dir = str(output_dir.resolve())
                    completed.validation_json = {
                        **report,
                        "progress": 100,
                        "current_step": "已完成并通过 Meta 规范终检",
                    }
                    completed.status = "ready"
                    completed.last_error = ""
                    session.add(completed)
                    session.commit()


meta_package_pipeline = MetaPackagePipeline()


def resume_meta_packages() -> None:
    if os.getenv("JUSHU_LOCAL_WORKSPACE") != "1":
        return
    with Session(database.engine) as session:
        interrupted = session.exec(
            select(MetaDeliveryPackage).where(MetaDeliveryPackage.status == "building")
        ).all()
        for item in interrupted:
            item.status = "queued"
            item.last_error = "服务器重启，已自动恢复生成"
            session.add(item)
        queued = bool(
            interrupted
            or session.exec(select(MetaDeliveryPackage).where(MetaDeliveryPackage.status == "queued")).first()
        )
        session.commit()
    if queued:
        meta_package_pipeline.start()
