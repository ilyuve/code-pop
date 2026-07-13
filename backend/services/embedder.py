"""Local embedding generation using a real HuggingFace model with degradation fallback."""

import logging
from typing import List, Optional

import numpy as np

from config import settings
from services.degradation_tracker import get_degradation_tracker

logger = logging.getLogger(__name__)


class Embedder:
    """Thin singleton wrapper around sentence-transformers with degradation fallback."""

    _instance: Optional["Embedder"] = None

    def __new__(cls) -> "Embedder":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._degraded = False
        return cls._instance

    @property
    def is_degraded(self) -> bool:
        return self._degraded

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
                logger.info(
                    "Embedding model loaded successfully (dim=%d)", settings.embedding_dim
                )
            except Exception as exc:
                logger.warning("Failed to load embedding model '%s': %s", model_name, exc)
                self._degraded = True
                get_degradation_tracker().record(
                    component="embedder",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    fallback_action="Using hash-based pseudo vectors",
                )
                raise RuntimeError(
                    f"Failed to load embedding model '{model_name}'. "
                    f"Run `python scripts/download_models.py` first to pre-download it, "
                    f"or set HF_ENDPOINT=https://hf-mirror.com to use the mirror. "
                    f"Original error: {exc}"
                ) from exc
        return self._model

    def _degraded_encode(self, texts: List[str]) -> List[List[float]]:
        """Generate stable pseudo-vectors based on text hash."""
        dim = settings.embedding_dim
        results = []
        for t in texts:
            np.random.seed(hash(t) % 2**32)
            v = np.random.normal(0, 0.01, dim).astype(np.float32)
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
            results.append(v.tolist())
        return results

    def encode(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """Encode texts into normalized vectors."""
        if not texts:
            return []

        if self._degraded:
            return self._degraded_encode(texts)

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

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=settings.embedding_batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            if isinstance(embeddings, np.ndarray):
                return embeddings.astype(np.float32).tolist()
            return embeddings
        except Exception as exc:
            logger.warning("Embedding encode failed, falling back to pseudo vectors: %s", exc)
            self._degraded = True
            get_degradation_tracker().record(
                component="embedder",
                error_type=type(exc).__name__,
                error_message=str(exc),
                fallback_action="Using hash-based pseudo vectors",
            )
            return self._degraded_encode(texts)

    def encode_sparse(self, texts: List[str]) -> List[dict]:
        """Return sparse embeddings (token weights) using transformers auto model."""
        if not texts:
            return []

        if self._degraded:
            return [{} for _ in texts]

        try:
            import torch
            from transformers import AutoTokenizer, AutoModel

            model_name = settings.embedding_model

            if not hasattr(self, '_sparse_tokenizer') or self._sparse_tokenizer is None:
                self._sparse_tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._sparse_model = AutoModel.from_pretrained(model_name)
                self._sparse_model.eval()
                if torch.cuda.is_available():
                    self._sparse_model = self._sparse_model.to('cuda')

            results = []
            with torch.no_grad():
                for text in texts:
                    inputs = self._sparse_tokenizer(
                        text,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=512,
                    )
                    if torch.cuda.is_available():
                        inputs = {k: v.to('cuda') for k, v in inputs.items()}

                    outputs = self._sparse_model(**inputs)
                    embeddings = outputs.last_hidden_state.squeeze(0)
                    weights = torch.norm(embeddings, dim=-1).tolist()
                    tokens = inputs["input_ids"].squeeze(0).tolist()

                    sparse_dict = {}
                    special_ids = {
                        self._sparse_tokenizer.pad_token_id,
                        self._sparse_tokenizer.cls_token_id,
                        self._sparse_tokenizer.sep_token_id,
                    }
                    for token_id, weight in zip(tokens, weights):
                        if token_id in special_ids or weight <= 0.1:
                            continue
                        sparse_dict[token_id] = weight
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
        if self._degraded:
            return max(1, len(text.split()))
        try:
            return len(self.model.tokenizer.encode(text, add_special_tokens=True))
        except Exception:
            return max(1, len(text.split()))
