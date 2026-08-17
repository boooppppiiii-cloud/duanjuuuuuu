from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import factory


class _Rows:
    def all(self):
        return []


class _Session:
    row = None

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = 91
        self.row = row

    def get(self, _model, row_id):
        return self.row if self.row and self.row.id == row_id else None

    def flush(self):
        return None

    def commit(self):
        return None

    def exec(self, _statement):
        return _Rows()


def test_analysis_uses_process_owned_worker(monkeypatch, tmp_path):
    started: dict[str, object] = {}
    executed: dict[str, object] = {}

    class ThreadProbe:
        def __init__(self, *, target, args, kwargs, name, daemon):
            started.update(target=target, args=args, kwargs=kwargs, name=name, daemon=daemon)

        def start(self):
            started["started"] = True

    drama = SimpleNamespace(id=7, title="Worker Drama", episode_count=12, file_dir=str(tmp_path))
    def run_with_analyzer(*args, **kwargs):
        executed.update(args=args, kwargs=kwargs)

    pipeline = SimpleNamespace(
        is_active=lambda _drama_id: False,
        run_with_analyzer=run_with_analyzer,
    )
    monkeypatch.setattr(factory, "get_drama", lambda _drama_id, _session: drama)
    monkeypatch.setattr(factory, "episode_files", lambda _folder: [tmp_path / "Episode1.mp4"])
    monkeypatch.setattr(factory, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(factory, "provider_name", lambda _settings: "gemini")
    monkeypatch.setattr(factory, "factory_analysis_pipeline", pipeline)
    monkeypatch.setattr(factory, "read_analysis", lambda _path: {})
    monkeypatch.setattr(factory, "queued_analysis", lambda *_args: {"status": "queued", "progress": 0})
    monkeypatch.setattr(factory, "record_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(factory.threading, "Thread", ThreadProbe)

    result = factory.run_script_analysis(
        7,
        payload=None,
        session=_Session(),
        user=SimpleNamespace(id=23),
    )

    assert result == {
        "status": "queued", "progress": 0, "task_id": 91,
        "completed_episode_count": 0, "episodes": [], "is_active": True,
    }
    assert started["started"] is True
    assert started["target"] is factory._run_analysis_as_user
    assert started["name"] == "factory-analysis-7"
    assert started["daemon"] is True
    assert started["args"][0] == 23
    assert len(started["args"]) == 6
    assert started["kwargs"] == {"resume": False, "ai_analyzer": None}

    # Execute the exact target/arguments captured by the thread probe. This
    # catches keyword-only argument regressions that otherwise leave a queued
    # analysis record behind while the worker exits immediately.
    started["target"](*started["args"], **started["kwargs"])
    assert executed["args"] == (tmp_path, 7, "Worker Drama", factory.get_settings(), [])
    assert executed["kwargs"] == {"resume": False, "ai_analyzer": None}


def test_analysis_rejects_missing_video_before_creating_task(monkeypatch, tmp_path):
    drama = SimpleNamespace(id=7, title="Missing Video", episode_count=8, file_dir=str(tmp_path))
    monkeypatch.setattr(factory, "get_drama", lambda _drama_id, _session: drama)
    monkeypatch.setattr(factory, "episode_files", lambda _folder: [])

    with pytest.raises(HTTPException) as caught:
        factory.run_script_analysis(
            7,
            payload=None,
            session=_Session(),
            user=SimpleNamespace(id=23),
        )

    assert caught.value.status_code == 422
    assert "选择本地文件夹" in str(caught.value.detail)


def test_processing_analysis_payload_is_compact_but_preserves_completed_count():
    payload = {
        "status": "processing",
        "progress": 48,
        "episodes": [{"episode": "Episode1.mp4", "segments": [{"text": "long transcript"}]}],
        "window_checkpoints": {"Episode2.mp4": {"windows": {"0-60": {"data": {"summary": "private"}}}}},
    }

    result = factory._public_analysis_payload(payload)

    assert result["completed_episode_count"] == 1
    assert result["episodes"] == []
    assert "window_checkpoints" not in result
    assert payload["episodes"]
    assert "window_checkpoints" in payload


def test_completed_analysis_payload_keeps_review_data_without_private_cache():
    episode = {"episode": "Episode1.mp4", "segments": [], "high_energy": [], "sensitive": []}
    result = factory._public_analysis_payload({
        "status": "completed", "episodes": [episode], "window_checkpoints": {"unused": {}},
    })

    assert result["completed_episode_count"] == 1
    assert result["episodes"] == [episode]
    assert "window_checkpoints" not in result
