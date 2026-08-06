"""Ensure the target PostgreSQL database exists, then initialize schema."""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from config import settings
from scripts.db.init_db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ensure_database() -> None:
    db_url = make_url(settings.database_url)
    target_db = db_url.database
    if not target_db:
        raise ValueError("DATABASE_URL does not contain a database name")

    # Connect to the maintenance database (postgres) to check/create target DB.
    maintenance_url = db_url.set(database="postgres")
    engine = create_engine(maintenance_url, future=True)

    logger.info("Checking if database '%s' exists...", target_db)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": target_db},
        ).scalar()

        if result:
            logger.info("Database '%s' already exists.", target_db)
        else:
            logger.info("Database '%s' does not exist, creating...", target_db)
            # CREATE DATABASE cannot run inside a transaction block.
            with conn.execution_options(isolation_level="AUTOCOMMIT"):
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
            logger.info("Database '%s' created.", target_db)

    engine.dispose()

    logger.info("Initializing schema...")
    init_db()
    logger.info("Database ready.")


if __name__ == "__main__":
    ensure_database()
