FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies: git for cloning repositories.
# psycopg2-binary and torch provide pre-built wheels, so only git is needed.
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies.
# Install PyTorch CPU wheel first to avoid pulling the large CUDA variant.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# Pre-download embedding model to avoid runtime downloads on container restart.
# Default to the HF mirror so builds succeed behind the GFW; override with
# --build-arg HF_ENDPOINT=https://huggingface.co for direct access.
ARG HF_ENDPOINT=https://hf-mirror.com
ENV HF_ENDPOINT=${HF_ENDPOINT}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', trust_remote_code=True)"

# Ensure repository storage directory exists.
RUN mkdir -p /app/repos

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
