FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies: git for cloning repositories.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies using Tsinghua PyPI mirror.
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple torch && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Copy application code.
COPY . .

# Set HF_ENDPOINT for model downloads (default to mirror for China).
# Model will be downloaded at runtime on first startup.
ENV HF_ENDPOINT=https://hf-mirror.com

# Ensure repository storage directory exists.
RUN mkdir -p /app/repos

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
