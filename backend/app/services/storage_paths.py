from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from sqlmodel import Session, select

from ..models import (
    Basemap,
    Clip,
    Drama,
    FactoryJob,
    GeneratedAsset,
    HookAsset,
    MetaDeliveryPackage,
    Post,
    PublishJob,
    VisualReview,
)


def _media_relative_parts(value: str) -> tuple[str, ...] | None:
    """Extract the portion below a previous media root on any operating system."""
    if not value:
        return None
    candidates: Iterable[tuple[str, ...]] = (
        PureWindowsPath(value).parts,
        PurePosixPath(value).parts,
    )
    for parts in candidates:
        for index, part in enumerate(parts):
            if part.lower() == "media" and index + 1 < len(parts):
                return tuple(parts[index + 1 :])
    return None


def rebase_media_path(value: str, media_root: Path) -> str:
    """Resolve a stored path after the database and media directory move hosts."""
    if not value:
        return value
    current = Path(value)
    if current.exists():
        return str(current.resolve())
    relative = _media_relative_parts(value)
    if not relative:
        return value
    candidate = media_root.joinpath(*relative)
    return str(candidate.resolve()) if candidate.exists() else value


def reconcile_database_media_paths(session: Session, media_root: Path) -> int:
    """Repair portable media paths without changing records whose files are absent."""
    changed = 0
    path_fields = {
        Drama: ("file_dir", "cover_vertical_path", "cover_square_path", "cover_horizontal_path"),
        Basemap: ("file_path",),
        Clip: ("file_path", "preview_image"),
        FactoryJob: ("output_dir",),
        GeneratedAsset: ("file_path",),
        HookAsset: ("file_path",),
        Post: ("cover_path_169", "cover_path_916"),
        PublishJob: ("final_video_path",),
        VisualReview: ("image_path",),
        MetaDeliveryPackage: ("output_dir",),
    }
    for model, fields in path_fields.items():
        for row in session.exec(select(model)).all():
            row_changed = False
            for field in fields:
                value = getattr(row, field, "")
                rebased = rebase_media_path(value, media_root)
                if rebased != value:
                    setattr(row, field, rebased)
                    row_changed = True
                    changed += 1
            if isinstance(row, FactoryJob):
                rebased_sources = [rebase_media_path(value, media_root) for value in row.source_files]
                if rebased_sources != row.source_files:
                    row.source_files = rebased_sources
                    row_changed = True
                    changed += 1
            if row_changed:
                session.add(row)
    if changed:
        session.commit()
    return changed
