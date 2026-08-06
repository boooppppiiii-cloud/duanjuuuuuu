from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    # SQLModel 不自带迁移工具；P0 只对单机 SQLite 做向后兼容增列。
    if settings.database_url.startswith("sqlite") and "clip" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("clip")}
        additions = {
            "source_start": "FLOAT NOT NULL DEFAULT 0",
            "source_end": "FLOAT NOT NULL DEFAULT 0",
            "progress": "INTEGER NOT NULL DEFAULT 0",
            "current_step": "VARCHAR NOT NULL DEFAULT 'queued'",
            "error_message": "VARCHAR NOT NULL DEFAULT ''",
            "hit_words": "JSON NOT NULL DEFAULT '[]'",
            "review_note": "VARCHAR NOT NULL DEFAULT ''",
            "reviewed_at": "DATETIME",
            "error_advice": "VARCHAR NOT NULL DEFAULT ''",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "final_video_path": "VARCHAR NOT NULL DEFAULT ''",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE clip ADD COLUMN {name} {definition}"))
    if settings.database_url.startswith("sqlite") and "account" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("account")}
        additions = {
            "platform_user_id": "VARCHAR NOT NULL DEFAULT ''",
            "avatar_url": "VARCHAR NOT NULL DEFAULT ''",
            "profile_url": "VARCHAR NOT NULL DEFAULT ''",
            "follower_count": "INTEGER NOT NULL DEFAULT 0",
            "last_checked_at": "DATETIME",
            "connected_at": "DATETIME",
            "last_error": "VARCHAR NOT NULL DEFAULT ''",
            "capabilities": "JSON NOT NULL DEFAULT '[]'",
        }
        with engine.begin() as connection:
            if "strategy_id" not in existing:
                connection.execute(text("ALTER TABLE account ADD COLUMN strategy_id INTEGER"))
            if "auto_publish" not in existing:
                connection.execute(text("ALTER TABLE account ADD COLUMN auto_publish BOOLEAN NOT NULL DEFAULT 0"))
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE account ADD COLUMN {name} {definition}"))
    if settings.database_url.startswith("sqlite") and "metricsnapshot" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("metricsnapshot")}
        if "followers" not in existing:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE metricsnapshot ADD COLUMN followers INTEGER NOT NULL DEFAULT 0"))
    if settings.database_url.startswith("sqlite") and "publishjob" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("publishjob")}
        additions = {
            "publish_options": "JSON NOT NULL DEFAULT '{}'",
            "platform_url": "VARCHAR NOT NULL DEFAULT ''",
            "status_checked_at": "DATETIME",
            "submitted_at": "DATETIME",
            "completed_at": "DATETIME",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE publishjob ADD COLUMN {name} {definition}"))
    if settings.database_url.startswith("sqlite") and "metadeliverypackage" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("metadeliverypackage")}
        additions = {
            "drive_folder_id": "VARCHAR NOT NULL DEFAULT ''",
            "drive_folder_url": "VARCHAR NOT NULL DEFAULT ''",
            "last_error": "VARCHAR NOT NULL DEFAULT ''",
            "uploaded_at": "DATETIME",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE metadeliverypackage ADD COLUMN {name} {definition}"))
    if settings.database_url.startswith("sqlite") and "socialcomment" in inspect(engine).get_table_names():
        existing = {item["name"] for item in inspect(engine).get_columns("socialcomment")}
        additions = {"reply_id": "VARCHAR NOT NULL DEFAULT ''", "reply_text": "VARCHAR NOT NULL DEFAULT ''", "replied_at": "DATETIME"}
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE socialcomment ADD COLUMN {name} {definition}"))


def get_session():
    with Session(engine) as session:
        yield session
