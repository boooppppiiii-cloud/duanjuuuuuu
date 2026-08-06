from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Account
from app.routers import integrations
from app.routers.integrations import _redirect, _upsert_account


def test_oauth_reuses_single_manual_placeholder_account():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        placeholder = Account(platform="youtube", name="手动账号", account_type="creator", platform_user_id="", status="error")
        session.add(placeholder)
        session.commit()
        session.refresh(placeholder)
        placeholder_id = placeholder.id

        connected = _upsert_account(
            session,
            "youtube",
            "UC-real-channel",
            "真实频道",
            {"access_token_encrypted": "encrypted"},
            profile_url="https://www.youtube.com/channel/UC-real-channel",
            capabilities=["publish", "metrics"],
        )

        assert connected.id == placeholder_id
        assert connected.platform_user_id == "UC-real-channel"
        assert connected.status == "connected"
        assert len(session.exec(select(Account)).all()) == 1


def test_oauth_redirect_returns_to_management(monkeypatch):
    settings = type("Settings", (), {"public_ui_origin": "http://127.0.0.1:5174"})()
    monkeypatch.setattr(integrations, "get_settings", lambda: settings)
    response = _redirect("youtube", 1)
    assert response.headers["location"] == "http://127.0.0.1:5174/management?oauth=success&platform=youtube&accounts=1"
