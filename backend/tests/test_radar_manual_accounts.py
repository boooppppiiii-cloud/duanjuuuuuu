from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.models import AppUser, MonitoredAccount
from app.routers.radar import AccountCreate, AccountUpdate, accounts, create_account, delete_account, update_account
from app.services.radar_accounts import authorization_for
from app.services.radar_search import _match_account


def test_manual_accounts_only_collect_owned_account_fields(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'radar-manual.db'}")
    SQLModel.metadata.create_all(engine)
    user = AppUser(id=1, email="operator@example.com", password_hash="x")
    with Session(engine) as session:
        created = create_account(AccountCreate(
            platform="youtube",
            display_name="  Drama Creator  ",
            platform_account_id=" UC-OWNED ",
            relationship_type="own_creator",
            notes="daily account",
        ), user, session)
        assert created["display_name"] == "Drama Creator"
        assert created["relationship_type"] == "own_creator"
        assert created["authorization_status"] == "authorized"
        assert created["allowed_full_series"] is True
        assert created["authorized_regions"] == []
        assert created["authorization_start"] is None
        assert created["authorization_end"] is None
        assert created["source"] == "manual"
        assert created["dramas"] == []

        account_id = created["id"]
        updated = update_account(account_id, AccountUpdate(relationship_type="own_official"), user, session)
        assert updated["relationship_type"] == "own_official"
        listed = accounts(query="UC-OWNED", page=1, page_size=20, _=user, session=session)
        assert listed["total"] == 1 and listed["items"][0]["id"] == account_id
        teammate = AppUser(id=2, email="teammate@example.com", password_hash="x")
        shared = accounts(query="UC-OWNED", page=1, page_size=20, _=teammate, session=session)
        assert shared["total"] == 1 and shared["items"][0]["id"] == account_id


def test_manual_account_requires_identity_and_rejects_duplicates(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'radar-manual-duplicate.db'}")
    SQLModel.metadata.create_all(engine)
    user = AppUser(id=1, email="operator@example.com", password_hash="x")
    with Session(engine) as session:
        try:
            create_account(AccountCreate(display_name="No identity"), user, session)
            assert False, "account identity should be required"
        except HTTPException as exc:
            assert exc.status_code == 422

        session.add(MonitoredAccount(
            platform="youtube",
            platform_account_id="UC-DUPLICATE",
            display_name="Existing",
            normalized_name="existing",
        ))
        session.commit()
        try:
            create_account(AccountCreate(display_name="New name", platform_account_id="UC-DUPLICATE"), user, session)
            assert False, "duplicate platform identity should be rejected"
        except HTTPException as exc:
            assert exc.status_code == 409


def test_removed_account_is_hidden_stops_matching_and_can_be_restored(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'radar-manual-remove.db'}")
    SQLModel.metadata.create_all(engine)
    user = AppUser(id=1, email="operator@example.com", password_hash="x")
    with Session(engine) as session:
        created = create_account(AccountCreate(
            display_name="Shared Creator",
            platform_account_id="UC-SHARED",
            profile_url="https://youtube.com/channel/UC-SHARED",
            relationship_type="own_creator",
        ), user, session)
        account_id = created["id"]

        assert _match_account(session, "UC-SHARED", "Shared Creator", "") is not None
        assert delete_account(account_id, user, session) == {"ok": True}
        assert accounts(page=1, page_size=20, _=user, session=session)["total"] == 0
        assert _match_account(session, "UC-SHARED", "Shared Creator", "") is None
        removed = session.get(MonitoredAccount, account_id)
        assert removed is not None
        assert authorization_for(session, removed, 999, "US", None)["relationship_type"] == "unknown"

        restored = create_account(AccountCreate(
            display_name="Shared Creator Restored",
            platform_account_id="UC-SHARED",
            relationship_type="own_official",
        ), user, session)
        assert restored["id"] == account_id
        assert restored["active"] is True
        assert restored["source"] == "manual"
        assert restored["relationship_type"] == "own_official"
        assert accounts(page=1, page_size=20, _=user, session=session)["total"] == 1
