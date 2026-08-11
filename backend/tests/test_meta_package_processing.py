from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app import database
from app.models import AppUser, Drama, MetaDeliveryPackage
from app.routers import meta_sfs as meta_router
from app.schemas import MetaSFSRequest
from app.services import meta_package_processing


def _engine(tmp_path: Path):
    return create_engine(
        f"sqlite:///{tmp_path / 'meta-jobs.db'}",
        connect_args={"check_same_thread": False},
    )


def _queued_package(session: Session, tmp_path: Path) -> MetaDeliveryPackage:
    user = AppUser(email="meta@example.com", password_hash="test")
    drama = Drama(title="Meta job", file_dir=str(tmp_path / "drama"), description="Synopsis", genres=["Drama"])
    session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
    source = tmp_path / "source.mp4"; source.write_bytes(b"video")
    item = MetaDeliveryPackage(
        drama_id=drama.id,
        series_slug="meta-job",
        output_dir="",
        status="queued",
        owner_user_id=user.id,
        validation_json={
            "request": {
                "drama_id": drama.id,
                "series_slug": "meta-job",
                "description": "Synopsis",
                "locale": "en_US",
                "genres": ["Drama"],
                "release_date": "08/11/2026",
            },
            "source_paths": [str(source)],
            "output_parent": str(tmp_path / "packages"),
        },
    )
    session.add(item); session.commit(); session.refresh(item)
    return item


def test_pipeline_completes_persisted_package_job(monkeypatch, tmp_path: Path):
    engine = _engine(tmp_path); SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    with Session(engine) as session:
        item = _queued_package(session, tmp_path); package_id = item.id

    def fake_build(_drama, _payload, *, output_parent, delivery):
        assert delivery[1] == "factory_meta_split"
        assert delivery[0][0].name == "source.mp4"
        output = output_parent / "meta-job-ready"; output.mkdir(parents=True)
        return output, {"status": "passed", "series_slug": "meta-job"}

    monkeypatch.setattr(meta_package_processing, "build_package", fake_build)
    meta_package_processing.MetaPackagePipeline().process_queued()

    with Session(engine) as session:
        completed = session.get(MetaDeliveryPackage, package_id)
        assert completed.status == "ready"
        assert Path(completed.output_dir).is_dir()
        assert completed.validation_json["status"] == "passed"


def test_pipeline_keeps_failed_job_visible_with_error(monkeypatch, tmp_path: Path):
    engine = _engine(tmp_path); SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    with Session(engine) as session:
        item = _queued_package(session, tmp_path); package_id = item.id

    def failed_build(*_args, **_kwargs):
        raise RuntimeError("encoder unavailable")

    monkeypatch.setattr(meta_package_processing, "build_package", failed_build)
    meta_package_processing.MetaPackagePipeline().process_queued()

    with Session(engine) as session:
        failed = session.get(MetaDeliveryPackage, package_id)
        assert failed.status == "failed"
        assert "encoder unavailable" in failed.last_error


def test_build_endpoint_registers_job_before_background_generation(monkeypatch, tmp_path: Path):
    engine = _engine(tmp_path); SQLModel.metadata.create_all(engine)
    source = tmp_path / "source.mp4"; source.write_bytes(b"video")
    monkeypatch.setattr(meta_router, "_delivery_for_user", lambda *_: ([source], "factory_meta_split"))
    monkeypatch.setattr(meta_router, "preflight", lambda *_: {"series_slug": "queued-show", "blockers": []})
    monkeypatch.setattr(meta_router.meta_package_pipeline, "start", lambda: None)

    with Session(engine) as session:
        user = AppUser(email="queued@example.com", password_hash="test")
        drama = Drama(title="Queued show", file_dir=str(tmp_path / "drama"))
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        payload = MetaSFSRequest(
            drama_id=drama.id,
            description="Synopsis",
            release_date="08/11/2026",
        )

        item = meta_router.create_package(payload, session, user)
        listed = meta_router.list_packages(session, user)

        assert item.status == "queued"
        assert item.output_dir == ""
        assert listed[0].id == item.id
        assert listed[0].status == "queued"
