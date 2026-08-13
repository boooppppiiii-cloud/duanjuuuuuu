from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Drama, DramaSearchProfile, SearchQuery
from app.services.radar_search import query_suggestions, sync_queries


def test_query_suggestions_are_deduplicated_and_capped_when_synced(tmp_path):
    suggestions = query_suggestions("The Crown", ["Crown Story", "the crown"], ["The Crown romance"])
    assert suggestions[0] == {"text": "The Crown", "type": "official_title"}
    assert len({item["text"].casefold() for item in suggestions}) == len(suggestions)
    engine = create_engine(f"sqlite:///{tmp_path / 'queries.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drama = Drama(title="The Crown", file_dir="crown"); session.add(drama); session.commit(); session.refresh(drama)
        profile = DramaSearchProfile(drama_id=drama.id, official_title="The Crown", aliases=["Crown Story"], custom_queries=["The Crown romance"])
        session.add(profile); session.commit(); session.refresh(profile)
        rows = sync_queries(session, profile)
        assert len(rows) == 9
        assert len(session.exec(select(SearchQuery)).all()) == 9
        assert len([row for row in rows if row.enabled]) == 8
        assert rows[0].query_text == "The Crown"
