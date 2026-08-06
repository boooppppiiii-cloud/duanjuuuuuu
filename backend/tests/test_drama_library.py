import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_scan_update_highlights_and_stills(tmp_path: Path):
    media = tmp_path / "media"
    drama_dir = media / "dramas" / "测试短剧"
    (drama_dir / "episodes").mkdir(parents=True)
    (drama_dir / "stills").mkdir()
    (drama_dir / "episodes" / "EP01.mp4").write_bytes(b"fake")
    (drama_dir / "stills" / "one.jpg").write_bytes(b"image1")
    (drama_dir / "stills" / "two.png").write_bytes(b"image2")
    os.environ["MEDIA_ROOT"] = str(media)
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"

    import app.config
    app.config.get_settings.cache_clear()
    import app.database
    import app.routers.dramas
    import app.main
    importlib.reload(app.database)
    importlib.reload(app.routers.dramas)
    importlib.reload(app.main)

    with TestClient(app.main.app) as client:
        scanned = client.post("/api/dramas/scan")
        assert scanned.status_code == 200
        result = scanned.json()
        assert any(item["status"] == "imported" for item in result["logs"])
        drama = result["dramas"][0]
        assert drama["episode_count"] == 1
        assert len(drama["stills"]) == 2
        drama_id = drama["id"]

        updated = client.put(f"/api/dramas/{drama_id}", json={
            "genres": ["复仇"], "actor_names": ["演员甲"],
            "source_note": "已获授权素材", "is_ai_generated": False,
        })
        assert updated.status_code == 200

        marked = client.put(f"/api/dramas/{drama_id}/highlights", json={"highlights": [
            {"episode": "EP01.mp4", "start": 10, "end": 20, "note": "冲突"},
            {"episode": "EP01.mp4", "start": 30, "end": 40, "note": "反转"},
        ]})
        assert marked.status_code == 200
        assert len(marked.json()["highlights"]) == 2
        assert (drama_dir / "highlights.json").exists()

        still = client.get(f"/api/dramas/{drama_id}/stills/one.jpg")
        assert still.status_code == 200


def test_direct_video_upload_and_manual_register(tmp_path: Path):
    media = tmp_path / "media"; os.environ["MEDIA_ROOT"] = str(media); os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'imports.db'}"
    import app.config; app.config.get_settings.cache_clear()
    import app.database; import app.routers.dramas; import app.main
    importlib.reload(app.database); importlib.reload(app.routers.dramas); importlib.reload(app.main)
    direct = media / "dramas" / "直接放视频"; direct.mkdir(parents=True); (direct / "01.mp4").write_bytes(b"video")
    external = tmp_path / "external"; external.mkdir(); (external / "outside.mp4").write_bytes(b"external")
    with TestClient(app.main.app) as client:
        result = client.post("/api/dramas/scan").json()
        assert any(item["title"] == "直接放视频" for item in result["dramas"])
        registered = client.post("/api/dramas/register", json={"title": "绝对路径剧", "absolute_path": str(external), "source_note": "授权测试"})
        assert registered.status_code == 200
        data = b"chunk-upload-video"
        initialized = client.post("/api/dramas/uploads/init", json={"drama_title": "上传剧", "filename": "upload.mp4", "total_size": len(data), "total_chunks": 2, "source_note": "网页上传测试"}).json()
        upload_id = initialized["upload_id"]
        assert client.put(f"/api/dramas/uploads/{upload_id}/chunks/0", content=data[:8], headers={"Content-Type": "application/octet-stream"}).status_code == 200
        assert client.put(f"/api/dramas/uploads/{upload_id}/chunks/1", content=data[8:], headers={"Content-Type": "application/octet-stream"}).status_code == 200
        completed = client.post(f"/api/dramas/uploads/{upload_id}/complete")
        assert completed.status_code == 200
        assert completed.json()["episode_count"] == 1


def test_task_metadata_cover_upload_and_approved_asset_library(tmp_path: Path):
    media = tmp_path / "media"; os.environ["MEDIA_ROOT"] = str(media); os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'tasks.db'}"
    import app.config; app.config.get_settings.cache_clear()
    import app.database; import app.routers.dramas; import app.routers.moderation; import app.main
    importlib.reload(app.database); importlib.reload(app.routers.dramas); importlib.reload(app.routers.moderation); importlib.reload(app.main)
    with TestClient(app.main.app) as client:
        invalid = client.post("/api/dramas", json={"title": "错误任务", "description": "", "total_episode_count": 3, "genres": []})
        assert invalid.status_code == 422
        created = client.post("/api/dramas", json={"title": "海外测试剧", "description": "A mistaken marriage becomes a second chance at love.", "total_episode_count": 12, "genres": ["Drama", "Romance"], "is_ai_generated": True, "is_dubbed_content": True})
        assert created.status_code == 200
        drama = created.json(); assert drama["episode_count"] == 0; assert drama["description"].startswith("A mistaken marriage"); assert drama["genres"] == ["Drama", "Romance"]; assert drama["is_ai_generated"] is True; assert drama["is_dubbed_content"] is True; assert drama["total_episode_count"] == 12
        folder = Path(drama["file_dir"]); assert (folder / "episodes").is_dir(); assert (folder / "stills").is_dir(); assert (folder / "generated").is_dir()

        cover = b"fake-cover"
        initialized = client.post("/api/dramas/uploads/init", json={"drama_title": drama["title"], "filename": "cover.jpg", "total_size": len(cover), "total_chunks": 1, "source_note": "Meta folder", "destination": "stills"}).json()
        assert client.put(f"/api/dramas/uploads/{initialized['upload_id']}/chunks/0", content=cover, headers={"Content-Type": "application/octet-stream"}).status_code == 200
        completed = client.post(f"/api/dramas/uploads/{initialized['upload_id']}/complete")
        assert completed.status_code == 200
        assert (folder / "stills" / "cover.jpg").read_bytes() == cover

        video = b"fake-video"
        initialized = client.post("/api/dramas/uploads/init", json={"drama_title": drama["title"], "filename": "episode-1.mp4", "total_size": len(video), "total_chunks": 1, "source_note": "Content factory", "destination": "episodes"}).json()
        assert client.put(f"/api/dramas/uploads/{initialized['upload_id']}/chunks/0", content=video, headers={"Content-Type": "application/octet-stream"}).status_code == 200
        uploaded = client.post(f"/api/dramas/uploads/{initialized['upload_id']}/complete").json()
        assert uploaded["episode_count"] == 1
        assert uploaded["total_episode_count"] == 12

        from sqlmodel import Session
        from app.models import Clip
        final = media / "clips" / "final.mp4"; final.parent.mkdir(parents=True); final.write_bytes(b"real-final-video")
        with Session(app.database.engine) as session:
            clip = Clip(drama_id=drama["id"], template_name="suspense_hook", current_step="completed", status="pending", file_path=str(final))
            session.add(clip); session.commit(); session.refresh(clip); clip_id = clip.id
        reviewed = client.put(f"/api/moderation/clips/{clip_id}/review", json={"status": "approved", "note": ""})
        assert reviewed.status_code == 200
        refreshed = client.get(f"/api/dramas/{drama['id']}").json()
        assert refreshed["generated_files"][0]["name"] == f"成品_{clip_id:04d}.mp4"
