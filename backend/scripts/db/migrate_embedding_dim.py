"""One-time migration: rebuild embeddings table for new dimension."""

from database import engine, Base
from models import Embedding
from sqlalchemy import text


def migrate():
    """Drop and recreate embeddings table with new dimension."""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS embeddings CASCADE"))
        conn.commit()

    Base.metadata.create_all(bind=engine, tables=[Embedding.__table__])
    print("Embeddings table recreated with dimension 1024.")
    print("NOTE: You must re-index all repositories after this migration.")


if __name__ == "__main__":
    migrate()