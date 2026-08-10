from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, PublishJob
from app.routers.integrations import _upsert_account
from app.routers.publish import accounts, disconnect_account
from app.routers.workspace import account_matrix_rows


def test_remove_account_clears_credentials_and_hides_it_without_deleting_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'remove-account.db'}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        account = Account(
            platform="youtube",
            platform_user_id="channel-1",
            name="频道",
            account_type="official",
            status="connected",
            credentials_json={"channel_id": "channel-1", "access_token_encrypted": "secret"},
            capabilities=["publish", "metrics"],
            connected_at=datetime.now(),
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        job = PublishJob(post_id=999, account_id=account.id, scheduled_at=datetime.now(), status="published")
        session.add(job)
        session.commit()
        session.refresh(job)

        result = disconnect_account(account.id, session)

        assert result == {"removed": True, "account_id": account.id, "history_preserved": True}
        removed = session.get(Account, account.id)
        assert removed is not None
        assert removed.status == "removed"
        assert removed.removed_at is not None
        assert removed.credentials_json == {}
        assert removed.capabilities == []
        assert removed.connected_at is None
        assert accounts(session) == []
        assert account_matrix_rows(session) == []
        assert session.get(PublishJob, job.id) is not None

        with pytest.raises(HTTPException) as error:
            disconnect_account(account.id, session)
        assert error.value.status_code == 404


def test_oauth_reconnect_restores_the_same_removed_account(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'restore-account.db'}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        account = Account(
            platform="youtube",
            platform_user_id="channel-2",
            name="旧频道",
            account_type="official",
            status="removed",
            credentials_json={},
            removed_at=datetime.now(),
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        original_id = account.id

        restored = _upsert_account(
            session,
            "youtube",
            "channel-2",
            "新频道",
            {"channel_id": "channel-2", "access_token_encrypted": "new-secret"},
            capabilities=["publish"],
        )

        assert restored.id == original_id
        assert restored.status == "connected"
        assert restored.removed_at is None
        assert restored.name == "新频道"
        assert restored.credentials_json["access_token_encrypted"] == "new-secret"
        assert [item["id"] for item in accounts(session)] == [original_id]
