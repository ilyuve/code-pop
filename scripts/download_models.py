#!/usr/bin/env python3
"""Pre-download HuggingFace embedding model for CodePop.

Replicates the Dockerfile build-time pre-download step for local development.
Supports the HF mirror endpoint for users behind the GFW.

Usage:
    python scripts/download_models.py
    HF_ENDPOINT=https://hf-mirror.com python scripts/download_models.py
    EMBEDDING_MODEL=BAAI/bge-m3 python scripts/download_models.py
"""

import os
import sys
from pathlib import Path


def main() -> int:
    # Default to HF mirror so users behind the GFW can download without a VPN.
    # Set HF_ENDPOINT=https://huggingface.co to use the official endpoint.
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
    hf_endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")

    print("=" * 60)
    print("CodePop embedding model pre-download")
    print("=" * 60)
    print(f"Model:        {model_name}")
    print(f"HF endpoint:  {hf_endpoint}")
    print(f"Cache dir:    {os.environ.get('HF_HOME', os.path.expanduser('~/.cache/huggingface'))}")
    print("=" * 60)
    print()

    # Ensure backend package is importable when running from project root.
    project_root = Path(__file__).resolve().parent.parent
    backend_dir = project_root / "backend"
    if backend_dir.is_dir():
        sys.path.insert(0, str(backend_dir))

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        print(f"ERROR: sentence-transformers is not installed: {exc}", file=sys.stderr)
        print("Run: pip install sentence-transformers", file=sys.stderr)
        return 1

    print(f"Downloading model '{model_name}' from {hf_endpoint} ...")
    print("This may take several minutes (bge-m3 is ~2GB).")
    print()

    try:
        model = SentenceTransformer(model_name, trust_remote_code=True)
    except Exception as exc:
        print()
        print(f"ERROR: failed to download model '{model_name}': {exc}", file=sys.stderr)
        print()
        print("Troubleshooting:", file=sys.stderr)
        print(f"  1. Verify network access to {hf_endpoint}", file=sys.stderr)
        print(f"  2. Try a different mirror: HF_ENDPOINT=https://hf-mirror.com python {__file__}", file=sys.stderr)
        print(f"  3. Or use a VPN to access https://huggingface.co directly", file=sys.stderr)
        return 1

    # Sanity check: encode a sample text in both languages.
    print()
    print("Verifying model with sample encodings (zh + en) ...")
    sample = ["登录流程", "how does authentication work"]
    try:
        vectors = model.encode(sample, normalize_embeddings=True)
        dim = len(vectors[0])
        print(f"  Sample vector dimension: {dim}")
        if dim != 1024:
            print(f"  WARNING: expected dim=1024 for bge-m3, got {dim}", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR: model loaded but encoding failed: {exc}", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("SUCCESS: model downloaded and verified.")
    print("You can now start the backend: bash scripts/start-local-backend.sh")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
