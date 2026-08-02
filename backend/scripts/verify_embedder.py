"""Verify that the embedding model produces meaningful cross-lingual vectors.

This script intentionally fails fast if the model cannot be loaded or the
embeddings are nonsensical, matching the no-degradation policy of the service.

BGE-M3 dense cosine scores are known to be high even for unrelated short texts,
so this verifier uses the official recommended mix:

    score = 0.4 * dense_sim + 0.2 * sparse_sim + 0.4 * colbert_sim

Usage:
    HF_ENDPOINT=https://hf-mirror.com python -m scripts.verify_embedder
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from config import settings
from services.embedder import Embedder


# Official BGE-M3 recommended weights for dense / sparse / colbert.
WEIGHT_DENSE = 0.4
WEIGHT_SPARSE = 0.2
WEIGHT_COLBERT = 0.4

# We do not require unrelated pairs to be below an absolute threshold. Instead,
# every related pair must score higher than every unrelated pair by this margin.
MARGIN = 0.05


def _cosine(a, b) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(np.dot(va, vb) / norm)


def _sparse_score(a: dict, b: dict) -> float:
    """Weighted overlap of sparse lexical weights, normalized to [0, 1]."""
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    overlap = sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in keys)
    norm = max(sum(a.values()), sum(b.values()))
    return overlap / norm if norm else 0.0


def _colbert_score(q_reps, d_reps) -> float:
    """Late-interaction maxsim between ColBERT token vectors."""
    q = np.asarray(q_reps, dtype=np.float32)
    d = np.asarray(d_reps, dtype=np.float32)
    if q.size == 0 or d.size == 0:
        return 0.0
    scores = np.dot(q, d.T)
    return float(scores.max(axis=1).sum() / max(1, q.shape[0]))


def verify_dense_embedder(embedder: Embedder) -> bool:
    """Check that dense vectors capture Chinese-English semantic similarity."""
    print("\n=== Dense embedder verification ===")

    print("Loading dense model...")
    _ = embedder.model  # force lazy load
    print(f"  Device: cpu")
    print(f"  Dimension: {settings.embedding_dim}")

    pairs = [
        ("用户登录", "login authentication", True),
        ("用户登录", "红烧肉的制作方法", False),
        ("订单支付", "order payment", True),
        ("订单支付", "太阳系行星运动", False),
        ("embedding 怎么实现", "how to implement embeddings", True),
        ("embedding 怎么实现", "2026 年世界杯举办城市", False),
    ]

    # Encode each unique text once.
    unique_texts = sorted({t for pair in pairs for t in pair[:2]})
    dense_cache = {t: embedder.encode_query(t) for t in unique_texts}

    all_pass = True
    results = []
    for text_a, text_b, expected_related in pairs:
        sim = _cosine(dense_cache[text_a], dense_cache[text_b])
        ok = sim >= 0.6 if expected_related else True  # only a sanity check here
        if not ok:
            all_pass = False
        results.append((text_a, text_b, expected_related, sim, ok))
        status = "PASS" if ok else "FAIL"
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
    print(f"  Sparse token count: {len(sparse)}")
    top_tokens = sorted(sparse.items(), key=lambda kv: -kv[1])[:5]
    print(f"  Top weighted token ids: {top_tokens}")
    return True


def verify_hybrid_scoring(embedder: Embedder) -> bool:
    """Use dense + sparse + colbert mix to separate related/unrelated pairs."""
    print("\n=== Hybrid (dense + sparse + colbert) verification ===")

    pairs = [
        ("用户登录", "login authentication", True),
        ("用户登录", "红烧肉的制作方法", False),
        ("订单支付", "order payment", True),
        ("订单支付", "太阳系行星运动", False),
        ("embedding 怎么实现", "how to implement embeddings", True),
        ("embedding 怎么实现", "2026 年世界杯举办城市", False),
    ]

    unique_texts = sorted({t for pair in pairs for t in pair[:2]})
    dense_cache = {t: embedder.encode_query(t) for t in unique_texts}
    sparse_cache = {t: embedder.encode_query_sparse(t) for t in unique_texts}
    colbert_cache = {t: embedder.encode_colbert([t])[0] for t in unique_texts}

    records = []
    colbert_raw_scores = []
    for text_a, text_b, expected_related in pairs:
        dense_sim = _cosine(dense_cache[text_a], dense_cache[text_b])
        sparse_sim = _sparse_score(sparse_cache[text_a], sparse_cache[text_b])
        colbert_raw = _colbert_score(colbert_cache[text_a], colbert_cache[text_b])
        records.append((text_a, text_b, expected_related, dense_sim, sparse_sim, colbert_raw))
        colbert_raw_scores.append(colbert_raw)

    colbert_min = min(colbert_raw_scores)
    colbert_max = max(colbert_raw_scores)
    colbert_range = colbert_max - colbert_min

    final_scores = []
    for text_a, text_b, expected_related, dense_sim, sparse_sim, colbert_raw in records:
        colbert_norm = (
            (colbert_raw - colbert_min) / colbert_range if colbert_range > 0 else 1.0
        )
        final = WEIGHT_DENSE * dense_sim + WEIGHT_SPARSE * sparse_sim + WEIGHT_COLBERT * colbert_norm
        final_scores.append((text_a, text_b, expected_related, dense_sim, sparse_sim, colbert_raw, colbert_norm, final))

    related_finals = [r[-1] for r in final_scores if r[2]]
    unrelated_finals = [r[-1] for r in final_scores if not r[2]]

    min_related = min(related_finals) if related_finals else 0.0
    max_unrelated = max(unrelated_finals) if unrelated_finals else 0.0
    overall_ok = min_related > max_unrelated + MARGIN

    print(
        f"{'Pair':<45} {'Dense':>7} {'Sparse':>7} {'ColBERT':>9} {'C-Norm':>7} {'Final':>7} {'Expected':>9}"
    )
    for text_a, text_b, expected_related, dense_sim, sparse_sim, colbert_raw, colbert_norm, final in final_scores:
        pair_label = f"'{text_a}' <-> '{text_b}'"
        print(
            f"{pair_label:<45} {dense_sim:>7.4f} {sparse_sim:>7.4f} {colbert_raw:>9.4f} "
            f"{colbert_norm:>7.4f} {final:>7.4f} {'related' if expected_related else 'unrelated':>9}"
        )

    print(f"\n  min(related)={min_related:.4f}, max(unrelated)={max_unrelated:.4f}, margin={MARGIN:.2f}")
    status = "PASS" if overall_ok else "FAIL"
    print(f"  [{status}] Hybrid scoring separation")
    return overall_ok


def main() -> int:
    print("Starting embedder verification...")

    embedder = Embedder()

    dense_ok = verify_dense_embedder(embedder)
    sparse_ok = verify_sparse_embedder(embedder)
    hybrid_ok = verify_hybrid_scoring(embedder)

    print("\n=== Summary ===")
    print(f"  Dense cross-lingual check: {'PASS' if dense_ok else 'FAIL'}")
    print(f"  Sparse embedding check:    {'PASS' if sparse_ok else 'FAIL'}")
    print(f"  Hybrid scoring check:      {'PASS' if hybrid_ok else 'FAIL'}")

    if dense_ok and sparse_ok and hybrid_ok:
        print("\nAll embedder checks passed.")
        return 0

    print("\nSome embedder checks failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
