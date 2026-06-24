"""Local embedding generation with sentence-transformers."""

import logging
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

from config import settings

logger = logging.getLogger(__name__)


class Embedder:
    """Thin wrapper around sentence-transformers."""

    _instance: "Embedder | None" = None

    def __new__(cls) -> "Embedder":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
        return cls._instance

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s", settings.embedding_model)
            self._model = SentenceTransformer(settings.embedding_model)
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode a list of texts into normalized 768-d vectors."""
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.astype(np.float32).tolist()

    def encode_query(self, text: str) -> List[float]:
        """Encode a single query string."""
        return self.encode([text])[0]
