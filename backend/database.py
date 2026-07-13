"""SQLAlchemy engine, session management and pgvector setup with connection retry."""

import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

logger = logging.getLogger(__name__)


class DatabaseUnavailableException(Exception):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    max_overflow=5,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_pgvector_extension() -> None:
    """Ensure the pgvector extension exists in PostgreSQL."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()


def get_db_with_retry(max_retries: int = 3):
    """Get database session with retry logic."""
    delays = [0.5, 1.0, 2.0]
    last_exception = None

    for attempt in range(max_retries):
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            return db
        except Exception as e:
            last_exception = e
            logger.warning("Database connection attempt %d/%d failed: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(delays[attempt])

    logger.error("Database connection failed after %d attempts", max_retries)
    raise DatabaseUnavailableException(f"Database unavailable after {max_retries} attempts") from last_exception


def get_db():
    """FastAPI dependency that yields a database session with retry."""
    db = get_db_with_retry()
    try:
        yield db
    finally:
        db.close()
