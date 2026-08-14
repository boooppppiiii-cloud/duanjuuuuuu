from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.models import AppUser, MonitoredAccount
from app.routers.radar import AccountCreate, AccountUpdate, accounts, create_account, update_account


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
