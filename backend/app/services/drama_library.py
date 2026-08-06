import json
from pathlib import Path

from sqlmodel import Session, select

from ..models import Drama
from ..schemas import Highlight

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def ensure_drama_folders(media_root: Path) -> Path:
    dramas_root = media_root / "dramas"
    dramas_root.mkdir(parents=True, exist_ok=True)
    return dramas_root


def files_with_suffix(folder: Path, suffixes: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in suffixes)


def episode_files(folder: Path) -> list[Path]:
    """优先规范 episodes/，同时兼容视频直接放在剧名目录。"""
    nested = files_with_suffix(folder / "episodes", VIDEO_SUFFIXES)
    return nested or files_with_suffix(folder, VIDEO_SUFFIXES)


def scan_dramas_with_logs(session: Session, media_root: Path) -> tuple[list[Drama], list[dict]]:
    """扫描一级剧目目录，并为每个目录返回用户可见的明确结果。"""
    dramas_root = ensure_drama_folders(media_root)
    scanned: list[Drama] = []
    logs: list[dict] = [{"path": str(dramas_root.resolve()), "status": "info", "message": "开始扫描剧目根目录"}]
    folders = sorted(path for path in dramas_root.iterdir() if path.is_dir())
    if not folders:
        logs.append({"path": str(dramas_root.resolve()), "status": "skipped", "message": "没有发现任何剧目子目录"})
    for folder in folders:
        episodes = episode_files(folder)
        if not episodes:
            logs.append({"path": str(folder.resolve()), "status": "skipped", "message": "跳过：未找到 mp4/mov/mkv/webm 视频；支持 episodes/ 子目录或直接放在剧名目录"})
            continue
        existing = session.exec(select(Drama).where(Drama.file_dir == str(folder.resolve()))).first()
        same_title = session.exec(select(Drama).where(Drama.title == folder.name)).first()
        if same_title and not existing:
            logs.append({"path": str(folder.resolve()), "status": "skipped", "message": f"跳过：已存在同名剧，原路径为 {same_title.file_dir}"})
            continue
        drama = existing or Drama(title=folder.name, file_dir=str(folder.resolve()))
        drama.episode_count = len(episodes)
        session.add(drama)
        scanned.append(drama)
        logs.append({"path": str(folder.resolve()), "status": "updated" if existing else "imported", "message": f"{'更新' if existing else '入库'}成功：发现 {len(episodes)} 个视频"})
    session.commit()
    for drama in scanned:
        session.refresh(drama)
    return scanned, logs


def scan_dramas(session: Session, media_root: Path) -> list[Drama]:
    return scan_dramas_with_logs(session, media_root)[0]


def read_highlights(drama_dir: Path) -> list[Highlight]:
    path = drama_dir / "highlights.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Highlight.model_validate(item) for item in data.get("highlights", [])]


def write_highlights(drama_dir: Path, highlights: list[Highlight], episode_names: set[str]) -> None:
    for item in highlights:
        if item.episode not in episode_names:
            raise ValueError(f"剧集文件不存在：{item.episode}")
        if item.end <= item.start:
            raise ValueError("高能点结束时间必须晚于开始时间")
    path = drama_dir / "highlights.json"
    payload = {"highlights": [item.model_dump() for item in highlights]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
