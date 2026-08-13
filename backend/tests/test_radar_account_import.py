import csv
import io

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Drama, MonitoredAccount, RadarUnmatchedDrama
from app.services.radar_accounts import import_accounts, preview_import, template_bytes


def csv_bytes(rows, encoding="utf-8-sig"):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


def test_csv_chinese_headers_duplicate_update_and_unmatched(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'radar-import.db'}")
    SQLModel.metadata.create_all(engine)
    rows = [
        ["平台", "账号名称", "账号ID", "账号主页", "账号类型", "授权状态", "负责剧目", "授权地区", "是否允许完整剧"],
        ["youtube", "Partner One", "UC-1", "https://youtube.com/@partner", "authorized_partner", "authorized", "Known Drama,Missing Drama", "US,CA", "否"],
    ]
    data = csv_bytes(rows)
    preview = preview_import("accounts.csv", data)
    assert preview["valid_count"] == 1
    assert preview["mapping"]["platform_account_id"] == "账号ID"
    with Session(engine) as session:
        drama = Drama(title="Known Drama", file_dir=str(tmp_path / "known")); session.add(drama); session.commit()
        first = import_accounts(session, "accounts.csv", data, 1)
        assert first.created_count == 1
        assert first.unmatched_count == 1
        assert session.exec(select(RadarUnmatchedDrama)).one().raw_name == "Missing Drama"
        updated = csv_bytes([rows[0], ["youtube", "Partner Renamed", "UC-1", "https://youtube.com/@partner", "authorized_partner", "partial", "Known Drama", "GB", "是"]])
        second = import_accounts(session, "accounts.csv", updated, 1)
        assert second.updated_count == 1
        accounts = session.exec(select(MonitoredAccount)).all()
        assert len(accounts) == 1
        assert accounts[0].display_name == "Partner Renamed"
        assert accounts[0].allowed_full_series is True


def test_xlsx_template_round_trip_preview():
    preview = preview_import("template.xlsx", template_bytes())
    assert preview["row_count"] == 1
    assert preview["invalid_count"] == 0
    assert preview["mapping"]["profile_url"] == "账号主页"


def test_gb18030_csv_supported():
    data = csv_bytes([["平台", "账号名称", "账号类型", "授权状态"], ["youtube", "测试账号", "unknown", "unknown"]], "gb18030")
    assert preview_import("accounts.csv", data)["valid_count"] == 1
