import threading
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import Clip, Drama
from app.schemas import ClipCreateRequest
from app.services.audio import replace_background_music
from app.services.pipeline import SerialPipeline, create_clip_records


def test_four_highlights_create_four_clips(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'clips.db'}")
    SQLModel.metadata.create_all(engine)
    drama_dir = tmp_path / "drama"
    drama_dir.mkdir()
    (drama_dir / "highlights.json").write_text(
        '{"highlights":['
        '{"episode":"1.mp4","start":1,"end":10,"note":"a"},'
        '{"episode":"1.mp4","start":20,"end":30,"note":"b"},'
        '{"episode":"2.mp4","start":1,"end":10,"note":"c"},'
        '{"episode":"3.mp4","start":2,"end":12,"note":"d"}]}' , encoding="utf-8")
    with Session(engine) as session:
        drama = Drama(title="三集剧", file_dir=str(drama_dir), source_note="测试", episode_count=3)
        session.add(drama); session.commit(); session.refresh(drama)
        clips = create_clip_records(session, drama, "suspense_hook")
        assert len(clips) == 4
        assert all(item.current_step == "queued" for item in clips)


def test_empty_bgm_keeps_original_audio(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"original-media")
    result, vocals, replaced = replace_background_music("ffmpeg", source, ["复仇"], tmp_path / "media", output, tmp_path / "work")
    assert result == output
    assert vocals is None
    assert replaced is False
    assert output.read_bytes() == b"original-media"


def test_template_name_rejects_path_traversal():
    try:
        ClipCreateRequest(drama_id=1, template_name="../../secret")
        assert False, "路径穿越模板名必须被拒绝"
    except ValueError:
        pass


def test_serial_pipeline_lock_allows_only_one_consumer(monkeypatch, tmp_path: Path):
    import app.services.pipeline as module

    test_engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(module, "engine", test_engine)
    with Session(test_engine) as session:
        drama = Drama(title="排队剧", file_dir=str(tmp_path), source_note="测试")
        session.add(drama); session.commit(); session.refresh(drama)
        for _ in range(4):
            session.add(Clip(drama_id=drama.id, template_name="suspense_hook", source_eps=["1.mp4"], source_start=0, source_end=10))
        session.commit()

    queue = SerialPipeline()
    processed: list[int] = []

    def fake_process(clip_id: int):
        processed.append(clip_id)
        with Session(test_engine) as session:
            clip = session.get(Clip, clip_id)
            clip.current_step = "completed"
            clip.progress = 100
            session.add(clip); session.commit()

    monkeypatch.setattr(queue, "process_one", fake_process)
    threads = [threading.Thread(target=queue.process_queued) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(processed) == 4
    assert processed == sorted(processed)
