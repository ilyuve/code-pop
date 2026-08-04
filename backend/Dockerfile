# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Use a BuildKit cache mount for pip so interrupted downloads can resume on
# the next build. Show a progress bar even when Docker build is not a TTY.
ENV PIP_PROGRESS_BAR=on
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir --force-reinstall --index-url https://pypi.org/simple mcp==1.9.0 && \
    pip install uv modelscope && \
    python -c "from mcp.server.fastmcp import FastMCP; print('mcp fastmcp ok')"

# Patch FlagEmbedding: XLMRobertaModel expects `torch_dtype`, not `dtype`.
# This is a known upstream bug when loading BGE-M3 with newer transformers.
RUN sed -i 's/dtype=dtype/torch_dtype=dtype/' \
    /usr/local/lib/python3.11/site-packages/FlagEmbedding/finetune/embedder/encoder_only/m3/runner.py

COPY . .

RUN mkdir -p /app/repos

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
