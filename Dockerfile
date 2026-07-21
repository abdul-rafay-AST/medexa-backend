# Medexa backend — runs WITHOUT AWS (in-memory session store by default).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_NO_CACHE_DIR=1 \
    MEDEXA_HOST=0.0.0.0 \
    MEDEXA_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[aws]"

RUN mkdir -p /app/data/sessions

# Runtime assets (rule files + entrypoint script).
COPY config ./config
COPY scripts ./scripts

# Fail the image build if required Saudi Path A flatfiles are missing.
RUN test -f /app/config/regions/sa/codes/medexa_sbs_lookup.json \
 && test -f /app/config/regions/sa/codes/medexa_icd10_lookup.json \
 && test -f /app/config/regions/sa/codes/sbs_v3_snomed.json \
 && test -f /app/config/regions/sa/codes/icd10_am_ksa.json \
 && test -f /app/config/regions/sa/codes/unique_icd10_codes.json \
 && test -f /app/config/regions/sa/rules/sbs_icd10_mapping.json \
 && test -f /app/config/regions/sa/region_profile.json

EXPOSE 8000

# App Runner / ECS / ALB health checks — does not call Bedrock (fast).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# Honor the platform-assigned $PORT if present (App Runner/Render), else 8000.
CMD ["python", "scripts/run_api_server.py"]
