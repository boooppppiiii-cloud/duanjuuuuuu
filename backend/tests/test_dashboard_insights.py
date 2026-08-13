import asyncio
from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.models import Account
from app.routers import publish as publish_router
from app.services import social_integrations


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.text = ""

    def json(self):
        return self._payload


def test_youtube_seven_day_range_uses_settled_days_and_previous_period(monkeypatch):
    social_integrations._account_insight_cache.clear()
    settled_end = social_integrations._business_today() - timedelta(days=2)
    current_start = settled_end - timedelta(days=6)
    previous_start = current_start - timedelta(days=7)
    report_calls = []

    monkeypatch.setattr(social_integrations, "youtube_access_token", lambda account: "token")

    def fake_get(url, **kwargs):
        assert url.endswith("/channels")
        return FakeResponse({"items": [{"snippet": {"publishedAt": "2020-01-01T00:00:00Z"}, "statistics": {"subscriberCount": "123000", "viewCount": "900000", "videoCount": "42"}}]})

    def fake_report(token, start, end, metrics, dimension="day", content_type="all"):
        report_calls.append((start, end, metrics, dimension, content_type))
        rows = []
        cursor = start
        while cursor <= end:
            current = cursor >= current_start
            row = {"day": cursor.isoformat()}
            if metrics.startswith("views,"):
                row.update({"views": 20 if current else 10, "estimatedMinutesWatched": 2 if current else 1, "averageViewDuration": 6, "subscribersGained": 3 if current else 1, "subscribersLost": 1 if current else 0})
            elif metrics.startswith("videoThumbnailImpressions"):
                row.update({"videoThumbnailImpressions": 100 if current else 50, "videoThumbnailImpressionsClickRate": 5 if current else 4})
            else:
                row["estimatedRevenue"] = .2 if current else .05
            rows.append(row)
            cursor += timedelta(days=1)
        return rows, ""

    monkeypatch.setattr(social_integrations.httpx, "get", fake_get)
    monkeypatch.setattr(social_integrations, "_youtube_time_report", fake_report)

    result = social_integrations.account_insights(
        Account(id=77, platform="youtube", name="Channel", account_type="creator", status="connected"),
        "7",
        True,
        "shorts",
    )

    assert result["range"] == {
        "preset": "7",
        "days": 7,
        "start": current_start.isoformat(),
        "end": settled_end.isoformat(),
        "previous_start": previous_start.isoformat(),
        "previous_end": (current_start - timedelta(days=1)).isoformat(),
    }
    assert len(result["series"]) == 7
    assert result["content_type"] == "shorts"
    assert result["totals"]["views"] == 140
    assert result["totals"]["followers"] == 123000
    assert result["changes"]["views"] == 100
    assert result["changes"]["ctr"] == 25
    assert result["changes"]["net_subscribers"] == 100
    assert all(call[0] == previous_start and call[1] == settled_end for call in report_calls)
    assert all(call[4] == "shorts" for call in report_calls)


def test_youtube_time_report_filters_official_creator_content_type(monkeypatch):
    def fake_get(url, **kwargs):
        assert kwargs["params"]["dimensions"] == "day"
        assert kwargs["params"]["filters"] == "creatorContentType==SHORTS"
        return FakeResponse({
            "columnHeaders": [{"name": "day"}, {"name": "views"}],
            "rows": [["2026-08-10", 25]],
        })

    monkeypatch.setattr(social_integrations.httpx, "get", fake_get)
    rows, error = social_integrations._youtube_time_report("token", date(2026, 8, 10), date(2026, 8, 10), "views", "day", "shorts")

    assert error == ""
    assert rows == [{"day": "2026-08-10", "views": 25.0}]


def test_youtube_all_time_monthly_query_aligns_to_month_start(monkeypatch):
    social_integrations._account_insight_cache.clear()
    report_calls = []
    monkeypatch.setattr(social_integrations, "youtube_access_token", lambda account: "token")

    def fake_get(url, **kwargs):
        assert url.endswith("/channels")
        return FakeResponse({"items": [{"snippet": {"publishedAt": "2025-01-03T00:00:00Z"}, "statistics": {"subscriberCount": "10", "viewCount": "99", "videoCount": "3"}}]})

    def fake_report(token, start, end, metrics, dimension="day", content_type="all"):
        report_calls.append((start, dimension))
        key = start.strftime("%Y-%m")
        if metrics.startswith("views,"):
            return [{"month": key, "views": 25, "estimatedMinutesWatched": 5, "averageViewDuration": 12, "subscribersGained": 2, "subscribersLost": 0}], ""
        if metrics.startswith("videoThumbnailImpressions"):
            return [{"month": key, "videoThumbnailImpressions": 100, "videoThumbnailImpressionsClickRate": 5}], ""
        return [{"month": key, "estimatedRevenue": 1}], ""

    monkeypatch.setattr(social_integrations.httpx, "get", fake_get)
    monkeypatch.setattr(social_integrations, "_youtube_time_report", fake_report)

    result = social_integrations.account_insights(
        Account(id=78, platform="youtube", name="Channel", account_type="creator", status="connected"),
        "all", True, "all",
    )

    assert result["range"]["start"] == "2025-01-03"
    assert all(start == date(2025, 1, 1) and dimension == "month" for start, dimension in report_calls)
    assert result["totals"]["views"] == 25
    assert result["totals"]["ctr"] == 5


async def _read_stream(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks).decode("utf-8-sig")


def test_account_csv_contains_summary_comparison_and_daily_rows(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-export.db'}")
    SQLModel.metadata.create_all(engine)
    result = {
        "range": {"start": "2026-08-05", "end": "2026-08-11"},
        "totals": {"views": 100, "impressions": 500, "ctr": 5, "watch_time_seconds": 800, "average_view_duration_seconds": 8, "estimated_revenue": 2, "rpm": 20, "subscribers_gained": 4, "subscribers_lost": 1, "followers": 123000},
        "changes": {"views": 25, "ctr": -2, "net_subscribers": 50},
        "series": [{"date": "2026-08-05", "views": 10, "impressions": 50, "ctr": 5, "watch_time_seconds": 80, "average_view_duration_seconds": 8, "estimated_revenue": .2, "subscribers_gained": 1, "subscribers_lost": 0}],
    }
    monkeypatch.setattr(publish_router, "account_insights", lambda *args, **kwargs: result)

    with Session(engine) as session:
        account = Account(platform="youtube", name="Channel", account_type="creator", status="connected")
        session.add(account); session.commit(); session.refresh(account)
        response = publish_router.export_account_analytics(account.id, "7", "all", session)
        csv_text = asyncio.run(_read_stream(response))

    assert "周期汇总" in csv_text
    assert "环比增减率(%)" in csv_text
    assert "2026-08-05" in csv_text
    assert "123000" in csv_text
