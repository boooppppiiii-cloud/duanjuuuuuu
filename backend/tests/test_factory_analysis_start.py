from types import SimpleNamespace

from app.routers import factory


class _Rows:
    def all(self):
        return []


class _Session:
    def exec(self, _statement):
        return _Rows()


def test_analysis_uses_process_owned_worker(monkeypatch, tmp_path):
    started: dict[str, object] = {}

    class ThreadProbe:
        def __init__(self, *, target, args, kwargs, name, daemon):
            started.update(target=target, args=args, kwargs=kwargs, name=name, daemon=daemon)

        def start(self):
            started["started"] = True

    drama = SimpleNamespace(id=7, title="Worker Drama", episode_count=12, file_dir=str(tmp_path))
    pipeline = SimpleNamespace(is_active=lambda _drama_id: False)
    monkeypatch.setattr(factory, "get_drama", lambda _drama_id, _session: drama)
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

    assert result == {"status": "queued", "progress": 0, "is_active": True}
    assert started["started"] is True
    assert started["target"] is factory._run_analysis_as_user
    assert started["name"] == "factory-analysis-7"
    assert started["daemon"] is True
    assert started["args"][0] == 23
