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
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Ensure repository storage directory exists.
RUN mkdir -p /app/repos

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
