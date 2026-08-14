from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AppUser, Drama, FactoryAnalysisTask, FactoryJob, HookAsset
from app.routers import factory
from app.services.script_analysis import write_analysis


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_history_backfills_analysis_and_combines_processing_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("JUSHU_LOCAL_WORKSPACE", "1")
    folder = tmp_path / "drama"
    folder.mkdir()
    with _session(tmp_path) as session:
        user = AppUser(email="operator@example.com", password_hash="x")
        drama = Drama(title="History Drama", file_dir=str(folder), episode_count=2)
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        write_analysis(folder, {
            "status": "failed", "progress": 36, "current_step": "第 1 集识别中断",
            "error_message": "model error", "drama_id": drama.id, "title": drama.title,
            "episodes": [{"episode": "Episode1.mp4"}], "episode_count": 2,
            "source_files": ["Episode1.mp4", "Episode2.mp4"],
        })
        session.add(FactoryJob(
            drama_id=drama.id, owner_user_id=user.id, status="completed", progress=100,
            current_step="已完成", source_files=["Episode1.mp4", "Episode2.mp4"], clean_count=1,
        ))
        session.commit()

        rows = factory.task_history(session=session, user=user)

        assert {row.task_type for row in rows} == {"analysis", "processing"}
        analysis = next(row for row in rows if row.task_type == "analysis")
        assert analysis.drama_title == "History Drama"
        assert analysis.status == "failed"
        assert analysis.source_count == 2
        assert analysis.output_count == 1
        saved = factory.read_analysis(folder)
        assert saved and saved["task_id"] == analysis.task_id


def test_delete_current_analysis_removes_results_but_keeps_source_video(monkeypatch, tmp_path):
    monkeypatch.setenv("JUSHU_LOCAL_WORKSPACE", "1")
    folder = tmp_path / "drama"
    frames = folder / "analysis_frames"
    frames.mkdir(parents=True)
    source = folder / "Episode1.mp4"
    source.write_bytes(b"video")
    (frames / "frame.jpg").write_bytes(b"frame")
    (folder / "manual_sensitive.json").write_text("[]", encoding="utf-8")
    with _session(tmp_path) as session:
        user = AppUser(email="owner@example.com", password_hash="x")
        drama = Drama(title="Delete Drama", file_dir=str(folder), episode_count=1)
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        task = FactoryAnalysisTask(
            drama_id=drama.id, owner_user_id=user.id, status="failed", progress=40,
            current_step="识别失败", storage_mode="local_workspace", updated_at=datetime.utcnow(),
        )
        session.add(task); session.commit(); session.refresh(task)
        write_analysis(folder, {
            "task_id": task.id, "status": "failed", "progress": 40,
            "current_step": "识别失败", "error_message": "boom", "drama_id": drama.id,
            "title": drama.title, "episodes": [], "episode_count": 1,
        })
        stale = HookAsset(drama_id=drama.id, episode="Episode1.mp4", start=1, end=2, source="analysis", use_count=0)
        used = HookAsset(drama_id=drama.id, episode="Episode1.mp4", start=3, end=4, source="analysis", use_count=1)
        session.add(stale); session.add(used); session.commit(); session.refresh(used)

        result = factory.delete_current_analysis(drama.id, session=session, user=user)

        assert result["deleted"] is True
        assert result["removed_hooks"] == 1
        assert source.is_file()
        assert not (folder / "factory_analysis.json").exists()
        assert not (folder / "manual_sensitive.json").exists()
        assert not frames.exists()
        assert session.get(FactoryAnalysisTask, task.id) is None
        remaining = session.exec(select(HookAsset).where(HookAsset.drama_id == drama.id)).all()
        assert [row.id for row in remaining] == [used.id]
