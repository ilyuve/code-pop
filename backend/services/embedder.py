"""Local embedding generation using BGE-M3 via FlagEmbedding.

This module intentionally does NOT provide a degradation fallback. If the
embedding model cannot be loaded, the service must fail fast so that operators
can fix the environment instead of silently serving meaningless pseudo-vectors.

BGE-M3 can produce dense, sparse and ColBERT vectors from a single model. We use
BGEM3FlagModel directly because the public HF mirror used in this environment
ships the raw model files (pytorch_model.bin, tokenizer, sparse/colbert heads)
but is missing the extra SentenceTransformer packaging directories
(2_Normalize) that ``sentence_transformers`` expects.
"""

import logging
from typing import List, Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


class Embedder:
    """Singleton wrapper around BGE-M3 (FlagEmbedding)."""

    _instance: Optional["Embedder"] = None

    def __new__(cls) -> "Embedder":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._m3_model = None
        return cls._instance

    def _ensure_local_m3_files(self, model_name: str) -> str:
        """Download only the files BGEM3FlagModel needs, avoiding 403 junk files.

        The public HF mirror returns 403 for non-model files such as
        ``imgs/.DS_Store``. ``snapshot_download`` would try to fetch everything,
        so we use ``allow_patterns`` to pull only the weights, tokenizer and
        heads required by BGE-M3.
        """
        import os

        from huggingface_hub import snapshot_download

        flag_dir = os.path.expanduser("~/.cache/huggingface/bge-m3-flagembedding")
        required = [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "config_sentence_transformers.json",
            "sentence_bert_config.json",
            "pytorch_model.bin",
            "model.safetensors",
            "colbert_linear.pt",
            "sparse_linear.pt",
        ]

        if os.path.isdir(flag_dir) and all(
            os.path.exists(os.path.join(flag_dir, name)) for name in required
        ):
            return flag_dir

        os.makedirs(flag_dir, exist_ok=True)
        logger.info("Downloading BGE-M3 model files to %s", flag_dir)
        snapshot_download(
            repo_id=model_name,
            local_dir=flag_dir,
            allow_patterns=required,
            local_dir_use_symlinks=False,
        )
        return flag_dir

    def _m3_model_path(self, model_name: str) -> str:
        """Pick a local BGE-M3 checkpoint that has the M3 heads *and* tokenizer."""
        import glob
        import os

        required = ("colbert_linear.pt", "sparse_linear.pt", "tokenizer.json")

        candidates = [
            os.path.expanduser("~/.cache/huggingface/bge-m3-flagembedding"),
        ]

        hub_dir = os.path.expanduser(
            f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots"
        )
        candidates.extend(sorted(glob.glob(os.path.join(hub_dir, "*"))))

        for path in candidates:
            if os.path.isdir(path) and all(
                os.path.exists(os.path.join(path, name)) for name in required
            ):
                return path

        # No usable local checkpoint: prepare a minimal local copy before
        # loading so we do not hit 403 errors on mirror junk files.
        return self._ensure_local_m3_files(model_name)

    def _load_m3_model(self):
        """Lazy-load BGEM3FlagModel from a validated local path."""
        if self._m3_model is not None:
            return self._m3_model

        from FlagEmbedding import BGEM3FlagModel

        model_name = settings.embedding_model
        model_path = self._m3_model_path(model_name)

        logger.info("Loading BGEM3FlagModel from %s", model_path)
        self._m3_model = BGEM3FlagModel(
            model_path,
            devices="cpu",
            use_fp16=False,
        )
        return self._m3_model

    @property
    def model(self):
        """Return the underlying BGE-M3 model (BGEM3FlagModel instance)."""
        return self._load_m3_model()

    def encode(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """Encode texts into normalized dense vectors."""
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

        embeddings = self._load_m3_model().encode(
            texts,
            batch_size=settings.embedding_batch_size,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )["dense_vecs"]

        if isinstance(embeddings, np.ndarray):
            embeddings = embeddings.astype(np.float32)
        else:
            embeddings = np.asarray(embeddings, dtype=np.float32)

        # BGE-M3 dense output is already normalized by default, but enforce it
        # so downstream cosine/dot products are consistent.
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.where(norms == 0, 1.0, norms)
        return embeddings.tolist()

    def encode_sparse(self, texts: List[str]) -> List[dict]:
        """Return sparse embeddings (token weights) using BGEM3FlagModel."""
        if not texts:
            return []

        output = self._load_m3_model().encode(
            texts,
            batch_size=settings.embedding_batch_size,
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

    def encode_colbert(self, texts: List[str]) -> List[np.ndarray]:
        """Return ColBERT token-level vectors using BGEM3FlagModel."""
        if not texts:
            return []

        output = self._load_m3_model().encode(
            texts,
            batch_size=settings.embedding_batch_size,
            return_dense=False,
            return_sparse=False,
            return_colbert_vecs=True,
        )
        return output["colbert_vecs"]

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
            return len(
                self._load_m3_model().tokenizer.encode(text, add_special_tokens=True)
            )
        except Exception:
            return max(1, len(text.split()))
