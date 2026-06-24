"""Initialize the CodePop database: extensions, tables and vector index."""

import logging

from sqlalchemy import text

from database import Base, engine, init_pgvector_extension
from models import *  # noqa: F401,F403 - registers all models with Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db() -> None:
    logger.info("Creating pgvector extension if needed...")
    init_pgvector_extension()

    logger.info("Creating tables...")
    Base.metadata.create_all(bind=engine)

    logger.info("Creating IVFFlat vector index...")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_vector "
                "ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_symbols_name "
                "ON symbols (name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_code_files_path "
                "ON code_files (repo_id, path)"
            )
        )
        conn.commit()

    logger.info("Database initialization complete.")


if __name__ == "__main__":
    init_db()
