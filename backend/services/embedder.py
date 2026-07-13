"""Local embedding generation using a real HuggingFace model.

No mock fallback: if the model cannot be loaded, the Embedder raises
RuntimeError with actionable guidance. Silently degrading to random vectors
would poison search quality without the user knowing -- unacceptable for
production use.
"""

import logging
from typing import List, Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


class Embedder:
    """Thin singleton wrapper around sentence-transformers."""

    _instance: Optional["Embedder"] = None

    def __new__(cls) -> "Embedder":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
        return cls._instance

    @property
    def model(self):
        if self._model is None:
            model_name = settings.embedding_model
            logger.info("Loading embedding model: %s", model_name)
            try:
                from sentence_transformers import SentenceTransformer
                import os
                
                cache_path = os.path.expanduser(f'~/.cache/huggingface/hub/models--{model_name.replace("/", "--")}/snapshots/main')
                if os.path.exists(cache_path):
                    logger.info(f"Loading model from cache: {cache_path}")
                    self._model = SentenceTransformer(cache_path, device='cpu')
                else:
                    logger.info(f"Loading model from hub: {model_name}")
                    self._model = SentenceTransformer(model_name, trust_remote_code=True, device='cpu')
            except Exception as exc:
                logger.error("Failed to load embedding model '%s': %s", model_name, exc)
                raise RuntimeError(
                    f"Failed to load embedding model '{model_name}'. "
                    f"Run `python scripts/download_models.py` first to pre-download it, "
                    f"or set HF_ENDPOINT=https://hf-mirror.com to use the mirror. "
                    f"Original error: {exc}"
                ) from exc
            logger.info(
                "Embedding model loaded successfully (dim=%d)", settings.embedding_dim
            )
        return self._model

    def encode(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """Encode texts into normalized vectors."""
        if not texts:
            return []

        if is_query:
            texts = [
                f"Represent this sentence for searching relevant passages: {t}"
                for t in texts
            ]

        embeddings = self.model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        if isinstance(embeddings, np.ndarray):
            return embeddings.astype(np.float32).tolist()
        return embeddings

    def encode_query(self, text: str) -> List[float]:
        """Encode a search query."""
        return self.encode([text], is_query=True)[0]

    def encode_documents(self, texts: List[str]) -> List[List[float]]:
        """Encode code chunks as documents."""
        return self.encode(texts, is_query=False)

    def count_tokens(self, text: str) -> int:
        """Count tokenizer tokens for a text."""
        try:
            return len(self.model.tokenizer.encode(text, add_special_tokens=True))
        except Exception:
            return max(1, len(text.split()))
