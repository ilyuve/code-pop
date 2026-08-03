#!/usr/bin/env python3
"""Standalone BGE-M3 model downloader for CodePop.

Downloads only the files needed by BGEM3FlagModel into a single local directory
so the embedder can load offline. Supports:

- Environment variables: HF_ENDPOINT, HTTPS_PROXY, HTTP_PROXY
- VPN/proxy auto-detection via requests
- Weight fallback: model.safetensors -> pytorch_model.bin
- Resume-friendly individual file downloads

Usage:
    uv run python scripts/download_bge_m3.py
    HF_ENDPOINT=https://hf-mirror.com uv run python scripts/download_bge_m3.py
    HTTPS_PROXY=http://127.0.0.1:7890 uv run python scripts/download_bge_m3.py
"""

import os
import sys
from pathlib import Path
from typing import List, Optional


MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
LOCAL_DIR = os.path.expanduser("~/.cache/huggingface/bge-m3-flagembedding")

REQUIRED_FILES: List[str] = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "colbert_linear.pt",
    "sparse_linear.pt",
]

WEIGHT_CANDIDATES: List[str] = ["model.safetensors", "pytorch_model.bin"]


def _clean_endpoint(raw: Optional[str]) -> str:
    if not raw:
        return "https://huggingface.co"
    endpoint = raw.strip().strip("`'\"").strip()
    if not endpoint.startswith(("http://", "https://")):
        endpoint = "https://huggingface.co"
    return endpoint


def _has_all_files(local_dir: str) -> bool:
    if not os.path.isdir(local_dir):
        return False
    for name in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(local_dir, name)):
            return False
    if not any(os.path.isfile(os.path.join(local_dir, w)) for w in WEIGHT_CANDIDATES):
        return False
    return True


def main() -> int:
    from huggingface_hub import hf_hub_download

    os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")
    endpoint = _clean_endpoint(os.environ.get("HF_ENDPOINT"))
    os.environ["HF_ENDPOINT"] = endpoint

    print("=" * 60)
    print("CodePop BGE-M3 model downloader")
    print("=" * 60)
    print(f"Model:        {MODEL_NAME}")
    print(f"Endpoint:     {endpoint}")
    print(f"Local dir:    {LOCAL_DIR}")
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    print(f"Proxy:        {proxy or '(none)'}")
    print("=" * 60)
    print()

    os.makedirs(LOCAL_DIR, exist_ok=True)

    if _has_all_files(LOCAL_DIR):
        print("All required files already present. Skipping download.")
        print(f"  -> {LOCAL_DIR}")
        return 0

    print("Downloading required files...")
    print()

    failed_optional: List[str] = []
    for filename in REQUIRED_FILES:
        try:
            print(f"  - {filename}")
            hf_hub_download(
                repo_id=MODEL_NAME,
                filename=filename,
                local_dir=LOCAL_DIR,
            )
        except Exception as exc:
            failed_optional.append(filename)
            print(f"    WARNING: {exc}")

    print()
    print("Downloading model weights...")
    weight_ok = False
    last_error: Optional[Exception] = None
    for filename in WEIGHT_CANDIDATES:
        try:
            print(f"  - trying {filename}")
            hf_hub_download(
                repo_id=MODEL_NAME,
                filename=filename,
                local_dir=LOCAL_DIR,
            )
            weight_ok = True
            print(f"    OK: using {filename}")
            break
        except Exception as exc:
            last_error = exc
            print(f"    WARNING: {exc}")

    if not weight_ok:
        print()
        print("ERROR: Could not download model weights.", file=sys.stderr)
        print(f"  Last error: {last_error}", file=sys.stderr)
        print("  Troubleshooting:", file=sys.stderr)
        print("    1. Check network / VPN / proxy", file=sys.stderr)
        print("    2. Try a mirror: HF_ENDPOINT=https://hf-mirror.com uv run python scripts/download_bge_m3.py", file=sys.stderr)
        return 1

    if failed_optional:
        print()
        print("NOTE: Some optional files were not downloaded:")
        for name in failed_optional:
            print(f"  - {name}")

    if not _has_all_files(LOCAL_DIR):
        print()
        print("ERROR: Download finished but local files are still incomplete.", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("SUCCESS: BGE-M3 model files are ready.")
    print(f"  -> {LOCAL_DIR}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
