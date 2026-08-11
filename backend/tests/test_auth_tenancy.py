from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import database
from app.models import AppUser, Clip, Drama


def test_login_shared_drama_and_private_clips(monkeypatch, tmp_path: Path):
    import app.main as main
    import app.services.auth as auth_service
    import app.services.usage as usage_service

    engine = create_engine(f"sqlite:///{tmp_path / 'tenant.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    main.app.dependency_overrides[database.get_session] = session_override
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "create_db_and_tables", lambda: None)
    monkeypatch.setattr(main, "initialize_auth", lambda: None)
    monkeypatch.setattr(main, "resume_factory_jobs", lambda: None)
    monkeypatch.setattr(main, "resume_meta_packages", lambda: None)
    monkeypatch.setattr(main, "resume_factory_analyses", lambda: 0)
    monkeypatch.setattr(main, "start_translation_worker", lambda: None)
    monkeypatch.setattr(usage_service, "engine", engine)

    with TestClient(main.app) as anonymous:
        assert anonymous.get("/api/dramas").status_code == 401

    first = TestClient(main.app)
    second = TestClient(main.app)
    assert first.post("/api/auth/register", json={"email": "first@example.com", "password": "correct-horse-1"}).status_code == 200
    assert second.post("/api/auth/register", json={"email": "second@example.com", "password": "correct-horse-2"}).status_code == 200

    with Session(engine) as session:
        users = session.exec(select(AppUser).order_by(AppUser.id)).all()
        drama_root = tmp_path / "drama"; drama_root.mkdir()
        drama = Drama(title="共享短剧", file_dir=str(drama_root))
        session.add(drama); session.commit(); session.refresh(drama)
        session.add(Clip(drama_id=drama.id, template_name="u1", owner_user_id=users[0].id))
        session.add(Clip(drama_id=drama.id, template_name="u2", owner_user_id=users[1].id))
        session.commit()

    assert [row["title"] for row in first.get("/api/dramas").json()] == ["共享短剧"]
    assert [row["title"] for row in second.get("/api/dramas").json()] == ["共享短剧"]
    assert [row["template_name"] for row in first.get("/api/clips").json()] == ["u1"]
    assert [row["template_name"] for row in second.get("/api/clips").json()] == ["u2"]
    assert second.get("/api/admin/analytics").status_code == 403

    main.app.dependency_overrides.clear()
