from pathlib import Path

from app.models import Drama
from app.services.local_storage import LocalStorageEntry, list_local_storage, remove_storage_entry


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_storage_inventory_lists_only_managed_local_files(tmp_path: Path):
    drama_root = tmp_path / "source-drama"
    _write(drama_root / "Episode1.mp4", 101)
    _write(drama_root / "generated" / "final.mp4", 102)
    _write(drama_root / ".factory" / "job_0001" / "part.mp4", 11)
    _write(drama_root / "analysis_frames" / "frame.jpg", 12)
    legacy_root = tmp_path / "legacy"
    cover_root = tmp_path / "covers"
    whisper_root = tmp_path / "whisper"
    _write(legacy_root / "1" / "Episode1.mp4", 13)
    _write(legacy_root / ".2-job.importing" / "Episode2.mp4.part", 16)
    _write(cover_root / "1" / "vertical.jpg", 14)
    _write(whisper_root / "model.bin", 15)
    drama = Drama(id=1, title="示例短剧", file_dir=str(drama_root), source_note="local")

    result = list_local_storage(
        [drama], app_dir=tmp_path, legacy_root=legacy_root,
        cover_root=cover_root, whisper_cache=whisper_root,
    )

    ids = {item["id"] for item in result["items"]}
    assert ids == {"factory:1", "frames:1", "legacy-staging:.2-job.importing", "legacy:1", "covers:1", "whisper:model"}
    assert result["total_bytes"] == 11 + 12 + 13 + 14 + 15 + 16
    assert all("Episode1.mp4" not in item["path"] for item in result["items"])
    assert (drama_root / "Episode1.mp4").is_file()
    assert (drama_root / "generated" / "final.mp4").is_file()


def test_remove_storage_entry_removes_only_selected_directory(tmp_path: Path):
    cache = tmp_path / "analysis_frames"
    source = tmp_path / "Episode1.mp4"
    _write(cache / "frame.jpg", 27)
    _write(source, 31)
    entry = LocalStorageEntry(
        id="frames:1", category="analysis", name="识别证据帧", description="test",
        path=str(cache), size_bytes=27, file_count=1, drama_id=1,
    )

    assert remove_storage_entry(entry) == 27
    assert not cache.exists()
    assert source.is_file()
