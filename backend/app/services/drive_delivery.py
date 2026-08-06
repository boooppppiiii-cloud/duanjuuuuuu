from __future__ import annotations

import mimetypes
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..config import get_settings

META_SFS_READER = "sfs-viewer-drive-reader@sfs-content-viewer.iam.gserviceaccount.com"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def _drive_service():
    settings = get_settings()
    path = Path(settings.google_drive_service_account_file)
    if not settings.google_drive_service_account_file or not path.is_file():
        raise RuntimeError("尚未配置有效的 GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE")
    credentials = service_account.Credentials.from_service_account_file(str(path), scopes=[DRIVE_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _create_folder(service, name: str, parent_id: str = "") -> str:
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    item = service.files().create(body=metadata, fields="id").execute()
    folder_id = str(item.get("id") or "")
    if not folder_id:
        raise RuntimeError(f"Google Drive 创建文件夹失败：{name}")
    return folder_id


def _upload_tree(service, source: Path, parent_id: str) -> None:
    for item in sorted(source.iterdir(), key=lambda path: (path.is_file(), path.name.casefold())):
        if item.is_dir():
            child_id = _create_folder(service, item.name, parent_id)
            _upload_tree(service, item, child_id)
        elif item.is_file():
            mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
            media = MediaFileUpload(str(item), mimetype=mime, resumable=True, chunksize=10 * 1024 * 1024)
            service.files().create(body={"name": item.name, "parents": [parent_id]}, media_body=media, fields="id").execute()


def upload_meta_package(package_root: Path) -> tuple[str, str]:
    if not package_root.is_dir():
        raise RuntimeError("Meta 投递包目录不存在")
    service = _drive_service()
    root_id = _create_folder(service, package_root.name, get_settings().google_drive_parent_folder_id.strip())
    _upload_tree(service, package_root, root_id)
    service.permissions().create(fileId=root_id, body={"type": "user", "role": "reader", "emailAddress": META_SFS_READER}, sendNotificationEmail=False, fields="id").execute()
    details = service.files().get(fileId=root_id, fields="id,webViewLink").execute()
    url = str(details.get("webViewLink") or f"https://drive.google.com/drive/folders/{root_id}")
    return root_id, url
