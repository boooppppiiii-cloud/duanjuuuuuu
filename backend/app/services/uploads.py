import hashlib
import json
import re
import shutil
from pathlib import Path

from ..schemas import UploadInitRequest

CHUNK_SIZE = 8 * 1024 * 1024
SAFE_TITLE = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")


def validate_title(title: str) -> str:
    value = title.strip()
    if not value or not SAFE_TITLE.match(value) or value in {".", ".."}:
        raise ValueError("剧名包含非法字符，请勿使用 <>:\"/\\|?*")
    return value


class UploadStore:
    def __init__(self, media_root: Path):
        self.media_root = media_root
        self.root = media_root / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def init(self, payload: UploadInitRequest) -> tuple[str, list[int]]:
        title = validate_title(payload.drama_title)
        filename = Path(payload.filename).name
        upload_id = hashlib.sha256(f"{title}|{payload.destination}|{filename}|{payload.total_size}".encode()).hexdigest()[:24]
        folder = self.root / upload_id; folder.mkdir(parents=True, exist_ok=True)
        manifest = folder / "manifest.json"
        expected = {**payload.model_dump(), "drama_title": title, "filename": filename}
        if manifest.exists():
            current = json.loads(manifest.read_text(encoding="utf-8"))
            if current != expected: raise ValueError("同一上传标识的文件参数不一致")
        else: manifest.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
        return upload_id, self.received(upload_id)

    def received(self, upload_id: str) -> list[int]:
        folder = self.safe_folder(upload_id)
        return sorted(int(path.stem) for path in folder.glob("*.chunk") if path.stem.isdigit())

    def safe_folder(self, upload_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{24}", upload_id): raise ValueError("上传 ID 不合法")
        folder = self.root / upload_id
        if not folder.is_dir(): raise FileNotFoundError("上传任务不存在")
        return folder

    def write_chunk(self, upload_id: str, index: int, data: bytes) -> list[int]:
        folder = self.safe_folder(upload_id); manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if index < 0 or index >= manifest["total_chunks"]: raise ValueError("分片序号越界")
        if len(data) > CHUNK_SIZE: raise ValueError("单分片不得超过 8MB")
        temp = folder / f"{index}.tmp"; final = folder / f"{index}.chunk"
        temp.write_bytes(data); temp.replace(final)
        return self.received(upload_id)

    def complete(self, upload_id: str) -> tuple[Path, dict]:
        folder = self.safe_folder(upload_id); manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        received = self.received(upload_id)
        expected = list(range(manifest["total_chunks"]))
        if received != expected: raise ValueError(f"分片不完整，缺少：{sorted(set(expected) - set(received))}")
        destination = manifest.get("destination", "episodes")
        if destination not in {"episodes", "stills"}:
            raise ValueError("上传目标目录不合法")
        target_dir = self.media_root / "dramas" / manifest["drama_title"] / destination; target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(manifest["filename"]).name; temp = target.with_suffix(target.suffix + ".uploading")
        with temp.open("wb") as output:
            for index in expected:
                with (folder / f"{index}.chunk").open("rb") as source: shutil.copyfileobj(source, output, length=1024 * 1024)
        if temp.stat().st_size != manifest["total_size"]: raise ValueError(f"文件大小校验失败：期望 {manifest['total_size']}，实际 {temp.stat().st_size}")
        temp.replace(target); shutil.rmtree(folder)
        return target, manifest
