#!/bin/bash

export PYTHONPATH="/Users/moon/PycharmProjects/code-pop/backend:$PYTHONPATH"
export DATABASE_URL="postgresql://postgres:codepop123@localhost:5432/codepop"
export REPOS_DIR="/Users/moon/PycharmProjects/code-pop/repos"
export API_HOST="0.0.0.0"
export API_PORT="8080"
export LOG_LEVEL="DEBUG"

# Embedding model: BAAI/bge-m3 (1024-dim, supports Chinese + English).
export EMBEDDING_MODEL="BAAI/bge-m3"
export EMBEDDING_DIM="1024"
export EMBEDDING_BATCH_SIZE="16"

# Use the HF mirror so model downloads succeed behind the GFW.
# Override with `HF_ENDPOINT=https://huggingface.co` for direct access.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

MODEL_CACHE="${HF_HOME:-$HOME/.cache/huggingface}/hub"
if [ ! -d "$MODEL_CACHE" ] || [ -z "$(ls -A "$MODEL_CACHE" 2>/dev/null)" ]; then
    echo "WARNING: HuggingFace model cache appears empty."
    echo "  If the backend fails to start, run: python scripts/download_models.py"
    echo ""
fi

PYTHON="/opt/homebrew/bin/python3.11"

echo "启动本地后端服务..."
echo "Python: $($PYTHON --version)"
echo "数据库: $DATABASE_URL"
echo "仓库目录: $REPOS_DIR"
echo "嵌入模型: $EMBEDDING_MODEL (dim=$EMBEDDING_DIM)"
echo "HF 镜像: $HF_ENDPOINT"
echo ""

cd /Users/moon/PycharmProjects/code-pop/backend
$PYTHON -m uvicorn main:app --host $API_HOST --port $API_PORT --reload
