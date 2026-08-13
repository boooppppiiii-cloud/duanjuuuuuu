from datetime import date, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.models import Drama, MonitoredAccount, MonitoredAccountDrama
from app.services.radar_accounts import authorization_for


def test_authorization_is_drama_region_time_and_full_series_specific(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'radar-auth.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drama1 = Drama(title="Drama A", file_dir="a"); drama2 = Drama(title="Drama B", file_dir="b")
        account = MonitoredAccount(platform="youtube", platform_account_id="UC1", display_name="Partner", relationship_type="authorized_partner", authorization_status="authorized", normalized_name="partner")
        session.add(drama1); session.add(drama2); session.add(account); session.commit(); session.refresh(drama1); session.refresh(drama2); session.refresh(account)
        session.add(MonitoredAccountDrama(account_id=account.id, drama_id=drama1.id, authorized_regions=["US"], authorization_start=date.today()-timedelta(days=5), authorization_end=date.today()+timedelta(days=5), allowed_full_series_override=False)); session.commit()
        assert authorization_for(session, account, drama1.id, "US", datetime.utcnow(), False)["authorized"] is True
        assert authorization_for(session, account, drama1.id, "US", datetime.utcnow(), True)["reason"] == "仅允许推广片段"
        assert authorization_for(session, account, drama1.id, "GB", datetime.utcnow(), False)["reason"] == "地区不在授权范围"
        assert authorization_for(session, account, drama2.id, "US", datetime.utcnow(), False)["authorization_status"] == "unknown"
        unknown = authorization_for(session, None, drama1.id, "US", datetime.utcnow(), True)
        assert unknown == {"relationship_type": "unknown", "authorization_status": "unknown", "authorized": False, "reason": "未匹配监测账号"}
