"""Compare BGE-M3 embeddings loaded via SentenceTransformer vs BGEM3FlagModel.

Usage:
    HF_ENDPOINT=https://hf-mirror.com python -m scripts.compare_bge_m3_loaders
"""

import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from sentence_transformers import SentenceTransformer
from FlagEmbedding import BGEM3FlagModel


def _local_model_path(model_name: str) -> str:
    """Return the local HuggingFace cache snapshot dir if available."""
    hub_dir = os.path.expanduser(
        f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots"
    )
    snapshot_dirs = sorted(glob.glob(os.path.join(hub_dir, "*")))
    if snapshot_dirs and os.path.isdir(snapshot_dirs[0]):
        return snapshot_dirs[0]
    return model_name


def _cosine(a, b) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(np.dot(va, vb) / norm)


def _colbert_maxsim(q_reps, d_reps) -> float:
    """ColBERT late interaction: max-sim between query and doc tokens."""
    q = np.asarray(q_reps, dtype=np.float32)
    d = np.asarray(d_reps, dtype=np.float32)
    scores = np.dot(q, d.T)
    return float(scores.max(axis=1).sum())


def main():
    print("Loading via SentenceTransformer...")
    st_model = SentenceTransformer("BAAI/bge-m3", device="cpu")

    local_path = _local_model_path("BAAI/bge-m3")
    print(f"Loading via BGEM3FlagModel from {local_path}...")
    m3_model = BGEM3FlagModel(local_path, devices="cpu", use_fp16=False)

    pairs = [
        ("用户登录", "login authentication", True),
        ("用户登录", "红烧肉的制作方法", False),
        ("订单支付", "order payment", True),
        ("订单支付", "太阳系行星运动", False),
    ]

    queries = [p[0] for p in pairs]
    docs = [p[1] for p in pairs]

    # SentenceTransformer dense vectors
    st_q = st_model.encode(queries, normalize_embeddings=True)
    st_d = st_model.encode(docs, normalize_embeddings=True)

    # BGEM3FlagModel dense vectors
    m3_dense_output = m3_model.encode(
        queries + docs,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    m3_dense = m3_dense_output["dense_vecs"]
    m3_q_dense = m3_dense[: len(queries)]
    m3_d_dense = m3_dense[len(queries) :]

    # BGEM3FlagModel colbert vectors
    m3_colbert_output = m3_model.encode(
        queries + docs,
        return_dense=False,
        return_sparse=False,
        return_colbert_vecs=True,
    )
    m3_colbert = m3_colbert_output["colbert_vecs"]
    m3_q_colbert = m3_colbert[: len(queries)]
    m3_d_colbert = m3_colbert[len(queries) :]

    print("\n=== Cosine similarity comparison ===")
    print(f"{'Pair':<40} {'ST-dense':>10} {'M3-dense':>10} {'M3-colbert':>12}")
    for i, (q, d, related) in enumerate(pairs):
        label = f"{q} <-> {d}"
        st_sim = _cosine(st_q[i], st_d[i])
        m3_dense_sim = _cosine(m3_q_dense[i], m3_d_dense[i])
        m3_colbert_score = _colbert_maxsim(m3_q_colbert[i], m3_d_colbert[i])
        print(
            f"{label:<40} {st_sim:>10.4f} {m3_dense_sim:>10.4f} {m3_colbert_score:>12.4f}"
        )

    # Show that ST-dense and M3-dense are essentially identical
    diff = np.abs(np.asarray(st_q) - np.asarray(m3_q_dense)).max()
    print(f"\nMax difference ST-dense vs M3-dense (queries): {diff:.6f}")


if __name__ == "__main__":
    main()
