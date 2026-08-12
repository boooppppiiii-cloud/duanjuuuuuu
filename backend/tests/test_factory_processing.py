import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from app.models import AppUser, Drama, FactoryJob, HookAsset
from app.schemas import FactoryProcessRequest
from app.services.factory_processing import FactoryCancelled, FactoryPipeline, TimelinePart, _encode_piece, balanced_lengths, build_hook_groups, build_meta_episode_plan, hook_clip_range, meta_video_is_compliant, natural_key, read_sensitive_ranges, render_timeline_slice, resume_factory_jobs, safe_ranges, slice_timeline
from app.services.drama_library import deduplicate_episode_copies


def test_natural_order_and_balanced_four_minutes():
    names = ["episode10.mp4", "episode2.mp4", "episode1.mp4"]
    assert sorted(names, key=natural_key) == ["episode1.mp4", "episode2.mp4", "episode10.mp4"]
    lengths = balanced_lengths(240, 180)
    assert len(lengths) == 2
    assert lengths == [120, 120]
    assert max(lengths) <= 180


def test_meta_split_uses_global_episode_numbers_after_a_source_is_split(tmp_path: Path):
    sources = [(tmp_path / f"Episode{index}.mp4", duration) for index, duration in enumerate([120, 150, 240, 90], start=1)]
    plan = build_meta_episode_plan(sources, 180)

    assert len(plan) == 5
    assert [part.sequence for part in plan] == [1, 2, 3, 4, 5]
    assert [part.source_episodes for part in plan] == [(1,), (2,), (3,), (3,), (4,)]
    assert [(part.parts[0].start, part.parts[0].end) for part in plan[2:4]] == [(0, 120), (120, 240)]


@pytest.mark.parametrize(
    ("durations", "expected"),
    [
        ([50, 100, 120], [150, 120]),
        ([50, 160], [60, 150]),
        ([120, 40], [160]),
        ([170, 40], [150, 60]),
        ([20, 20, 50], [90]),
    ],
)
def test_meta_short_episodes_are_merged_or_borrow_from_adjacent_episode(
    tmp_path: Path,
    durations: list[float],
    expected: list[float],
):
    sources = [(tmp_path / f"Episode{index}.mp4", duration) for index, duration in enumerate(durations, start=1)]
    operations: list[str] = []

    plan = build_meta_episode_plan(sources, 180, operations=operations)

    assert [part.duration for part in plan] == pytest.approx(expected)
    assert all(60 <= part.duration <= 180 for part in plan)
    assert operations
    assert any("不足 60 秒" in operation for operation in operations)


def test_meta_plan_rejects_a_whole_drama_shorter_than_one_minute(tmp_path: Path):
    with pytest.raises(ValueError, match="总时长不足 60 秒"):
        build_meta_episode_plan([(tmp_path / "Episode1.mp4", 59)], 180)


def test_identical_reuploads_of_a_numbered_episode_are_ignored(tmp_path: Path):
    original = tmp_path / "Drama-EP.1第1集.mp4"
    copy = tmp_path / "Drama-EP.1第1集 (1).mp4"
    second = tmp_path / "Drama-EP.2第2集.mp4"
    original.write_bytes(b"same-video")
    copy.write_bytes(b"same-video")
    second.write_bytes(b"second")

    result = deduplicate_episode_copies([copy, second, original])

    assert [path.name for path in result] == [original.name, second.name]


def test_hook_clip_range_is_between_fifteen_and_thirty_seconds():
    assert hook_clip_range(30, 45, 120) == (30, 45)
    assert hook_clip_range(30, 60, 120) == (30, 60)
    assert hook_clip_range(116, 119, 120) == (105, 120)
    assert hook_clip_range(5, 8, 12) == (0, 12)
    assert hook_clip_range(30, 70, 120) == (35, 65)


def test_factory_request_accepts_only_fifteen_to_thirty_second_hooks():
    assert FactoryProcessRequest().hook_duration_seconds == 15
    with pytest.raises(ValidationError):
        FactoryProcessRequest(hook_duration_seconds=14)
    with pytest.raises(ValidationError):
        FactoryProcessRequest(hook_duration_seconds=31)


def test_hook_groups_support_multiple_unique_hooks_per_version():
    hooks = [HookAsset(id=index, drama_id=1, episode=f"{index}.mp4", start=0, end=3) for index in range(1, 5)]
    groups = build_hook_groups(hooks, variant_count=4, hooks_per_variant=2)
    ids = [[hook.id for hook in group] for group in groups]
    assert ids == [[1, 2], [1, 3], [1, 4], [2, 3]]
    assert len({tuple(group) for group in ids}) == 4


def test_sensitive_ranges_are_removed_and_merged():
    assert safe_ranges(30, [(4, 8), (7, 10), (20, 22)]) == [(0, 4), (10, 20), (22, 30)]


def test_timeline_slice_can_cross_episode_boundary(tmp_path: Path):
    first = TimelinePart(tmp_path / "01.mp4", "01.mp4", 0, 100)
    second = TimelinePart(tmp_path / "02.mp4", "02.mp4", 5, 105)
    result = slice_timeline([first, second], 90, 30)
    assert [(row.episode, row.start, row.end) for row in result] == [
        ("01.mp4", 90, 100),
        ("02.mp4", 5, 25),
    ]


def test_render_timeline_reports_progress_across_all_parts(monkeypatch, tmp_path: Path):
    import app.services.factory_processing as module

    parts = [
        TimelinePart(tmp_path / "01.mp4", "01.mp4", 0, 10),
        TimelinePart(tmp_path / "02.mp4", "02.mp4", 0, 30),
    ]
    progress: list[float] = []

    def fake_encode(_ffmpeg, _ffprobe, _part, output, _profile, callback=None, *_):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        if callback:
            callback(.5)
            callback(1)

    monkeypatch.setattr(module, "_encode_piece", fake_encode)
    monkeypatch.setattr(module, "_concat_files", lambda _ffmpeg, _pieces, output, _manifest, *_: output.write_bytes(b"joined"))

    duration = render_timeline_slice(parts, tmp_path / "output.mp4", tmp_path / "work", "balanced", progress.append)

    assert duration == 40
    assert progress == [.125, .25, .625, 1, 1]


def test_meta_encoder_uses_official_full_hd_bitrate_and_audio(monkeypatch, tmp_path: Path):
    import app.services.factory_processing as module

    commands: list[list[str]] = []
    source = tmp_path / "source.mp4"; source.write_bytes(b"video")
    monkeypatch.setattr(module, "probe_media", lambda *_: {"has_audio": True})
    monkeypatch.setattr(module, "run_command", lambda command: commands.append(command))

    _encode_piece("ffmpeg", "ffprobe", TimelinePart(source, source.name, 0, 90), tmp_path / "target.mp4", "meta")

    command = commands[0]
    assert "scale=1080:1920" in command[command.index("-vf") + 1]
    assert command[command.index("-b:v") + 1] == "3M"
    assert command[command.index("-minrate") + 1] == "3M"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "192k"
    assert command[command.index("-ac") + 1] == "2"
    assert "-crf" not in command


def test_meta_direct_copy_requires_all_official_video_specs():
    compliant = {
        "format": "mov,mp4", "video_codec": "h264", "width": 1080, "height": 1920,
        "video_bitrate": 3_000_000, "audio_codec": "aac", "audio_channels": 2,
        "duration": 90, "size": 40_000_000,
    }
    assert meta_video_is_compliant(compliant)
    assert not meta_video_is_compliant({**compliant, "width": 720, "height": 1280})
    assert not meta_video_is_compliant({**compliant, "video_bitrate": 1_800_000})
    assert not meta_video_is_compliant({**compliant, "audio_codec": "mp3"})


def test_analysis_sensitive_segments_get_safety_buffer(tmp_path: Path):
    (tmp_path / "factory_analysis.json").write_text(json.dumps({"episodes": [{"episode": "01.mp4", "sensitive": [{"start": 10, "end": 12}]}]}), encoding="utf-8")
    assert read_sensitive_ranges(tmp_path) == {"01.mp4": [(9.75, 12.25)]}


def test_interrupted_job_is_requeued_on_server_start(monkeypatch, tmp_path: Path):
    import app.services.factory_processing as module

    test_engine = create_engine(f"sqlite:///{tmp_path / 'resume.db'}")
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(module.database, "engine", test_engine)
    with Session(test_engine) as session:
        drama = Drama(title="恢复测试", file_dir=str(tmp_path / "drama"), source_note="test")
        session.add(drama); session.commit(); session.refresh(drama)
        job = FactoryJob(drama_id=drama.id, status="processing", current_step="生成原剧分段")
        session.add(job); session.commit(); session.refresh(job); job_id = job.id
    called: list[bool] = []
    monkeypatch.setattr(module.factory_pipeline, "process_queued", lambda: called.append(True))

    class ImmediateThread:
        def __init__(self, target, **_): self.target = target
        def start(self): self.target()

    monkeypatch.setattr(module.threading, "Thread", ImmediateThread)
    resume_factory_jobs()
    with Session(test_engine) as session:
        recovered = session.get(FactoryJob, job_id)
        assert recovered.status == "queued"
        assert "等待恢复" in recovered.current_step
    assert called == [True]


def test_cancel_request_terminates_active_media_process():
    pipeline = FactoryPipeline()

    class ActiveProcess:
        terminated = False
        def poll(self): return None
        def terminate(self): self.terminated = True

    process = ActiveProcess()
    pipeline._begin_job(17)
    pipeline._set_process(17, process)  # type: ignore[arg-type]
    pipeline.request_cancel(17)

    assert process.terminated is True
    with pytest.raises(FactoryCancelled, match="已取消"):
        pipeline._check_cancelled(17)
    pipeline._finish_job(17)


def test_cancel_requested_job_is_not_requeued_on_restart(monkeypatch, tmp_path: Path):
    import app.services.factory_processing as module

    test_engine = create_engine(f"sqlite:///{tmp_path / 'cancel-resume.db'}")
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(module.database, "engine", test_engine)
    with Session(test_engine) as session:
        drama = Drama(title="取消恢复测试", file_dir=str(tmp_path / "drama"), source_note="test")
        session.add(drama); session.commit(); session.refresh(drama)
        job = FactoryJob(drama_id=drama.id, status="cancel_requested", current_step="正在取消")
        session.add(job); session.commit(); session.refresh(job); job_id = job.id
    called: list[bool] = []
    monkeypatch.setattr(module.factory_pipeline, "process_queued", lambda: called.append(True))

    resume_factory_jobs()

    with Session(test_engine) as session:
        recovered = session.get(FactoryJob, job_id)
        assert recovered.status == "cancelled"
        assert recovered.current_step == "已取消"
    assert called == []


def test_cancel_route_marks_processing_job_and_signals_pipeline(monkeypatch, tmp_path: Path):
    import app.routers.factory as factory_router

    test_engine = create_engine(f"sqlite:///{tmp_path / 'cancel-route.db'}")
    SQLModel.metadata.create_all(test_engine)
    called: list[int] = []
    monkeypatch.setattr(factory_router.factory_pipeline, "request_cancel", called.append)
    with Session(test_engine) as session:
        drama = Drama(title="取消接口测试", file_dir=str(tmp_path / "drama"), source_note="test")
        session.add(drama); session.commit(); session.refresh(drama)
        job = FactoryJob(drama_id=drama.id, owner_user_id=7, status="processing", current_step="转码中")
        session.add(job); session.commit(); session.refresh(job)

        updated = factory_router.cancel_job(
            int(job.id), session=session,
            user=AppUser(id=7, email="owner@example.com", password_hash="test"),
        )

        assert updated.status == "cancel_requested"
        assert updated.current_step == "正在取消并清理中间文件"
        assert called == [job.id]
