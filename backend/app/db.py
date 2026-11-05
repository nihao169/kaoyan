from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    engine = create_engine(url, pool_pre_ping=True, connect_args={'check_same_thread': False, 'timeout': 15} if url.startswith('sqlite') else {})
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def configure(conn, _):
            conn.isolation_level = None
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=15000')
        @event.listens_for(engine, 'begin')
        def begin(conn):
            # SQLite read-then-write upgrades can fail immediately with BUSY_SNAPSHOT
            # even with busy_timeout. Reserve the single writer at transaction start.
            # External model calls release their session before any network I/O.
            conn.exec_driver_sql('BEGIN IMMEDIATE')
    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
