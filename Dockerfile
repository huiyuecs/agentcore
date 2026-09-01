# AgentCore  Intelligent customer service system — Docker Multi-stage build
#  Target: The production image should be as streamlined as possible. Development image includes debugging tools

# ──  Stage 1:Basic environment ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# curl  for health check; gcc/g++ is no longer required (Local ML model removed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ──  Stage 2:Install Python dependencies ──────────────────────────────────────────────────
FROM base AS dependencies

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

#  Pre-download ChromaDB’s built-in ONNX embedding model (~79MB), Avoid runtime download timeouts
RUN mkdir -p /root/.cache/chroma/onnx_models/all-MiniLM-L6-v2 && \
    curl -L --retry 3 --retry-delay 5 -o /root/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz \
    https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz && \
    cd /root/.cache/chroma/onnx_models/all-MiniLM-L6-v2 && \
    tar -xzf onnx.tar.gz && \
    rm onnx.tar.gz

# ──  Stage 3:Production image ──────────────────────────────────────────────────────────
FROM base AS production

#  Running as non-root user.Create user first, Subsequent COPY directly brings owner. Avoid chown -R copying extra large layers.
RUN useradd -m -u 1000 agentcore

#  Copy installed packages from dependency stage
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin
#  Copy pre-downloaded ONNX model cache
COPY --from=dependencies --chown=agentcore:agentcore /root/.cache/chroma /home/agentcore/.cache/chroma

# Copy application code
COPY --chown=agentcore:agentcore . .

# Create necessary directories, Only adjust the directory permissions that need to be written during runtime. Avoid recursively chowning the entire application.
RUN mkdir -p /app/data/chroma /app/logs /app/config && \
    chown agentcore:agentcore /app/data /app/data/chroma /app/logs /app/config
USER agentcore

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ──  Stage 4:Development image ──────────────────────────────────────────────────────────
FROM dependencies AS development

COPY . .

RUN mkdir -p /app/data/chroma /app/logs /app/config /app/tests && \
    chmod -R 777 /app/data /app/logs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
