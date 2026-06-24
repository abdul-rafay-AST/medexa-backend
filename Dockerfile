# Medexa backend — runs WITHOUT AWS (in-memory session store by default).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDEXA_HOST=0.0.0.0 \
    MEDEXA_PORT=8000

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Runtime assets (rule files + entrypoint script).
COPY config ./config
COPY scripts ./scripts

EXPOSE 8000

# Honor the platform-assigned $PORT if present (Render/Railway/Fly), else 8000.
CMD ["python", "scripts/run_api_server.py"]
