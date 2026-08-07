import zipfile
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import Drama
from app.routers.meta_sfs import _create_package_archive
from app.services.drama_library import scan_dramas_with_logs
from app.services.storage_paths import rebase_media_path


def test_rebase_windows_media_path_to_server_root(tmp_path: Path):
    media_root = tmp_path / "media"
    target = media_root / "dramas" / "迁移剧" / "episodes" / "01.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")

    result = rebase_media_path(r"E:\旧工作台\media\dramas\迁移剧\episodes\01.mp4", media_root)

    assert Path(result) == target.resolve()


def test_rebase_keeps_missing_media_path_unchanged(tmp_path: Path):
    original = r"E:\旧工作台\media\dramas\尚未上传\episodes\01.mp4"
    assert rebase_media_path(original, tmp_path / "media") == original


def test_scan_moves_same_title_record_from_missing_old_host_path(tmp_path: Path):
    media_root = tmp_path / "media"
    current = media_root / "dramas" / "迁移剧"
    (current / "episodes").mkdir(parents=True)
    (current / "episodes" / "01.mp4").write_bytes(b"video")
    engine = create_engine(f"sqlite:///{tmp_path / 'paths.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Drama(title="迁移剧", file_dir=r"E:\旧工作台\media\dramas\迁移剧", source_note="迁移"))
        session.commit()

        dramas, logs = scan_dramas_with_logs(session, media_root)

        assert dramas[0].file_dir == str(current.resolve())
        assert dramas[0].episode_count == 1
        assert any("迁移到当前共享素材目录" in entry["message"] for entry in logs)


def test_package_archive_preserves_root_folder(tmp_path: Path):
    root = tmp_path / "series_package"
    (root / "series").mkdir(parents=True)
    (root / "README.txt").write_text("steps", encoding="utf-8")
    (root / "series" / "episode.mp4").write_bytes(b"video")

    archive = _create_package_archive(root, tmp_path / "downloads", reserve_bytes=0)

    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["series_package/README.txt", "series_package/series/episode.mp4"]
        assert bundle.read("series_package/series/episode.mp4") == b"video"
