"""Base repository class."""

from sqlalchemy.orm import Session


class BaseRepository:
    """Provides a shared database session to all repositories."""

    def __init__(self, db: Session):
        self.db = db
