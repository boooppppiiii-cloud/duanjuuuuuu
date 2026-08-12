from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..models import Drama


@dataclass(frozen=True)
class LocalStorageEntry:
    id: str
    category: str
    name: str
    description: str
    path: str
    size_bytes: int
    file_count: int
    drama_id: int | None = None
    drama_title: str = ""
    warning: str = ""

    def model_dump(self) -> dict:
        return asdict(self)


def directory_usage(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    total = 0
    files = 0
    for root, directories, names in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in names:
            candidate = Path(root) / name
            try:
                if candidate.is_symlink():
                    continue
                total += candidate.stat().st_size
                files += 1
            except OSError:
                continue
    return total, files


def _entry(
    entry_id: str,
    category: str,
    name: str,
    description: str,
    path: Path,
    drama: Drama | None = None,
    warning: str = "",
) -> LocalStorageEntry | None:
    size_bytes, file_count = directory_usage(path)
    if not path.exists() or (size_bytes <= 0 and file_count <= 0):
        return None
    return LocalStorageEntry(
        id=entry_id,
        category=category,
        name=name,
        description=description,
        path=str(path.resolve()),
        size_bytes=size_bytes,
        file_count=file_count,
        drama_id=int(drama.id) if drama and drama.id else None,
        drama_title=drama.title if drama else "",
        warning=warning,
    )


def list_local_storage(
    dramas: Iterable[Drama],
    *,
    app_dir: Path,
    legacy_root: Path,
    cover_root: Path,
    whisper_cache: Path,
) -> dict:
    drama_rows = list(dramas)
    entries: list[LocalStorageEntry] = []
    by_id = {int(drama.id): drama for drama in drama_rows if drama.id}
    for drama in drama_rows:
        if not drama.id or not drama.file_dir:
            continue
        root = Path(drama.file_dir).expanduser()
        if root.is_dir():
            work = _entry(
                f"factory:{drama.id}", "processing", "加工中间文件",
                "视频合并、转码和拼接时产生，正常完成后会自动删除。",
                root / ".factory", drama,
            )
            frames = _entry(
                f"frames:{drama.id}", "analysis", "AI 识别证据帧",
                "用于高能点和敏感内容的画面依据预览。",
                root / "analysis_frames", drama,
                "删除后已有识别结果仍保留，但证据图将无法显示；重新识别可重建。",
            )
            for item in (work, frames):
                if item:
                    entries.append(item)
    for target in sorted(legacy_root.glob(".*.importing")) if legacy_root.is_dir() else []:
        item = _entry(
            f"legacy-staging:{target.name}", "processing", "未完成的旧素材迁移",
            "旧版服务器素材迁移中断后留下的临时文件。", target,
            warning="确认当前没有正在进行的迁移任务后可安全删除。",
        )
        if item:
            entries.append(item)
    for target in sorted(legacy_root.glob("*")) if legacy_root.is_dir() else []:
        if not target.is_dir() or not target.name.isdigit():
            continue
        drama = by_id.get(int(target.name))
        item = _entry(
            f"legacy:{target.name}", "material", "服务器旧成品本机副本",
            "从服务器迁移后保存在这台电脑的视频素材。",
            target, drama,
            "删除后该剧目会失去这份本机素材及其内部成品，如仍需要必须重新迁移或选择其他文件夹。",
        )
        if item:
            entries.append(item)
    for target in sorted(cover_root.glob("*")) if cover_root.is_dir() else []:
        if not target.is_dir() or not target.name.isdigit():
            continue
        drama = by_id.get(int(target.name))
        item = _entry(
            f"covers:{target.name}", "cache", "剧目封面本机副本",
            "Meta 投递和本机处理使用的封面副本。",
            target, drama,
            "删除后下次使用 Meta 投递前需重新同步封面。",
        )
        if item:
            entries.append(item)
    model = _entry(
        "whisper:model", "model", "语音识别模型",
        "用于本机语音转写，只会下载一次。",
        whisper_cache,
        warning="删除后下次内容识别会重新下载模型，首次识别会变慢。",
    )
    if model:
        entries.append(model)
    entries.sort(key=lambda item: item.size_bytes, reverse=True)
    total = sum(item.size_bytes for item in entries)
    return {
        "workspace_root": str(app_dir.resolve()),
        "total_bytes": total,
        "item_count": len(entries),
        "items": [item.model_dump() for item in entries],
    }


def remove_storage_entry(entry: LocalStorageEntry) -> int:
    target = Path(entry.path).resolve()
    if not target.exists():
        return 0
    filesystem_root = Path(target.anchor).resolve() if target.anchor else None
    if target == filesystem_root or target == Path.home().resolve() or len(target.parts) < 3:
        raise ValueError("拒绝删除范围过大的目录")
    size_bytes, _ = directory_usage(target)
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return size_bytes
