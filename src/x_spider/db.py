from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from x_spider.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def create_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    import x_spider.models  # noqa: F401

    settings = settings or get_settings()
    db_path = settings.resolved_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
