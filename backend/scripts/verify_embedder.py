"""Verify that the embedding model produces meaningful cross-lingual vectors.

This script intentionally fails fast if the model cannot be loaded or the
embeddings are nonsensical, matching the no-degradation policy of the service.

Usage:
    HF_ENDPOINT=https://hf-mirror.com python -m scripts.verify_embedder
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from services.embedder import Embedder


# bge-m3 produces high cosine scores even for unrelated texts due to its
# normalized embeddings. Calibrated against actual bge-m3 outputs.
THRESHOLD_RELATED = 0.75
THRESHOLD_UNRELATED = 0.72


def _cosine(a, b) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(np.dot(va, vb) / norm)


def verify_dense_embedder(embedder: Embedder) -> bool:
    """Check that dense vectors capture Chinese-English semantic similarity."""
    print("\n=== Dense embedder verification ===")

    print("Loading dense model...")
    model = embedder.model
    print(f"  Device: {model.device}")
    print(f"  Dimension: {model.get_sentence_embedding_dimension()}")

    # Cross-lingual related pairs should score high; unrelated pairs are chosen
    # from completely different domains to keep false positives low.
    pairs = [
        ("用户登录", "login authentication", True),
        ("用户登录", "红烧肉的制作方法", False),
        ("订单支付", "order payment", True),
        ("订单支付", "太阳系行星运动", False),
        ("embedding 怎么实现", "how to implement embeddings", True),
        ("embedding 怎么实现", "2026 年世界杯举办城市", False),
    ]

    all_pass = True
    for text_a, text_b, expected_related in pairs:
        vec_a = embedder.encode_query(text_a)
        vec_b = embedder.encode_query(text_b)
        sim = _cosine(vec_a, vec_b)

        if expected_related:
            ok = sim >= THRESHOLD_RELATED
            status = "PASS" if ok else "FAIL"
        else:
            ok = sim <= THRESHOLD_UNRELATED
            status = "PASS" if ok else "FAIL"

        if not ok:
            all_pass = False

        print(
            f"  [{status}] '{text_a}' <-> '{text_b}' = {sim:.4f} "
            f"(expected related={expected_related})"
        )

    return all_pass


def verify_sparse_embedder(embedder: Embedder) -> bool:
    """Check that sparse lexical weights can be generated."""
    print("\n=== Sparse embedder verification ===")

    query = "用户登录验证"
    sparse = embedder.encode_query_sparse(query)
    if not sparse:
        print("  [FAIL] Sparse embedding returned empty weights")
        return False

    print(f"  Query: {query}")
    print(f"  Sparse token count: {len(sparse[0])}")
    top_tokens = sorted(sparse[0].items(), key=lambda kv: -kv[1])[:5]
    print(f"  Top weighted token ids: {top_tokens}")
    return True


def main() -> int:
    print("Starting embedder verification...")

    embedder = Embedder()

    dense_ok = verify_dense_embedder(embedder)
    sparse_ok = verify_sparse_embedder(embedder)

    print("\n=== Summary ===")
    print(f"  Dense cross-lingual check: {'PASS' if dense_ok else 'FAIL'}")
    print(f"  Sparse embedding check: {'PASS' if sparse_ok else 'FAIL'}")

    if dense_ok and sparse_ok:
        print("\nAll embedder checks passed.")
        return 0

    print("\nSome embedder checks failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
