# (syntax directive removed: BuildKit built-in frontend supports RUN --mount=type=cache)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Switch to a domestic Debian mirror to avoid network failures during apt-get update.
RUN (sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g; s|http://security.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g; s|http://security.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null) && \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Use a BuildKit cache mount for pip so interrupted downloads can resume on
# the next build. Show a progress bar even when Docker build is not a TTY.
ENV PIP_PROGRESS_BAR=on
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    python -c "from mcp.server.fastmcp import FastMCP; print('mcp fastmcp ok')"

# Install model downloader tools. These are not strictly required at runtime
# but make it easy to fetch BGE-M3 inside the container for offline use.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://pypi.org/simple uv modelscope

# Patch FlagEmbedding: AutoModel.from_pretrained expects `torch_dtype`, not
# `dtype`, with transformers 4.50. FlagEmbedding 1.2/1.3 writes `dtype=dtype`
# and 1.4 writes `dtype=torch_dtype`; normalize only inside the
# from_pretrained(...) call so torch.nn.Linear(dtype=...) stays untouched.
RUN sed -i -E '/from_pretrained\(/,/^\s*\)\s*$/ s/\bdtype=(dtype|torch_dtype)/torch_dtype=\1/g' \
    /usr/local/lib/python3.11/site-packages/FlagEmbedding/finetune/embedder/encoder_only/m3/runner.py

COPY . .

RUN mkdir -p /app/repos

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
