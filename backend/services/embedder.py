"""Local embedding generation using a real HuggingFace model.

This module intentionally does NOT provide a degradation fallback. If the
embedding model cannot be loaded, the service must fail fast so that operators
can fix the environment instead of silently serving meaningless pseudo-vectors.
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
            from sentence_transformers import SentenceTransformer
            import os

            cache_path = os.path.expanduser(
                f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots/main"
            )
            if os.path.exists(cache_path):
                logger.info("Loading model from cache: %s", cache_path)
                self._model = SentenceTransformer(cache_path, device="cpu")
            else:
                logger.info("Loading model from hub: %s", model_name)
                self._model = SentenceTransformer(
                    model_name, trust_remote_code=True, device="cpu"
                )
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
        else:
            texts = [
                f"Represent this document for retrieval: {t}"
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

    def encode_sparse(self, texts: List[str]) -> List[dict]:
        """Return sparse embeddings (token weights) using BGEM3FlagModel."""
        if not texts:
            return []

        try:
            model_name = settings.embedding_model

            if not hasattr(self, "_m3_model") or self._m3_model is None:
                from FlagEmbedding import BGEM3FlagModel

                # Prefer the local cache path if the dense model has already
                # been downloaded. This avoids repeated hub lookups and spurious
                # 403 errors on non-model files (e.g. .DS_Store) when mirrors are
                # used.
                import glob
                import os

                hub_dir = os.path.expanduser(
                    f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots"
                )
                snapshot_dirs = sorted(glob.glob(os.path.join(hub_dir, "*")))
                local_cache = snapshot_dirs[0] if snapshot_dirs else None
                model_path = local_cache if local_cache and os.path.isdir(local_cache) else model_name

                logger.info("Loading BGEM3FlagModel for sparse embeddings from %s", model_path)
                self._m3_model = BGEM3FlagModel(
                    model_path,
                    devices="cpu",
                    use_fp16=False,
                )

            output = self._m3_model.encode(
                texts,
                return_dense=False,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            lexical_weights = output["lexical_weights"]

            results = []
            for s in lexical_weights:
                sparse_dict = {}
                for k, v in s.items():
                    if float(v) > 0.0:
                        sparse_dict[int(k)] = float(v)
                results.append(sparse_dict)

            return results
        except Exception as exc:
            logger.warning("Sparse embedding encode failed: %s", exc)
            return [{} for _ in texts]

    def encode_query_sparse(self, text: str) -> dict:
        """Return sparse embedding for a query."""
        return self.encode_sparse([text])[0]

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
