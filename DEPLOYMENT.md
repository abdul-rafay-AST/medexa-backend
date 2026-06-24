# Medexa Backend — Deployment Guide (No AWS Required)

The backend runs **fully without AWS**. By default it uses an in-memory session
store (`MEDEXA_USE_DYNAMODB=false`), so you can deploy it to any host that can
run a Python web process: Render, Railway, Fly.io, a plain VPS, or Docker.

> **Trade-off of in-memory mode:** session state lives in the process. It is
> perfect for the MVP demo and frontend integration, but state is lost on
> restart and is **not shared across multiple instances**. Run a **single
> instance** (no horizontal autoscaling) until you enable DynamoDB. This is fine
> for the current demo/integration phase.

---

## 1. Run locally

```bash
pip install -e ".[dev]"        # base install — no AWS libraries needed
copy .env.example .env          # Windows  (cp on macOS/Linux)
python scripts/run_api_server.py
```

- Swagger UI: http://localhost:8000/docs
- Health: http://localhost:8000/health

For local hot-reload set `MEDEXA_RELOAD=true` in `.env`.

---

## 2. Environment variables

| Variable | Default | Notes |
|----------|---------|-------|
| `MEDEXA_HOST` | `0.0.0.0` | Bind address. Keep `0.0.0.0` for containers/hosts. |
| `MEDEXA_PORT` | `8000` | Port. A bare `$PORT` (Render/Railway/Heroku) overrides it. |
| `MEDEXA_RELOAD` | `false` | `true` only for local dev. |
| `MEDEXA_CORS_ALLOW_ORIGINS` | `*` | Comma-separated **or** JSON array. Set exact frontend origin in prod. |
| `MEDEXA_LOG_LEVEL` | `INFO` | |
| `MEDEXA_USE_DYNAMODB` | `false` | Leave `false` to run without AWS. |

`MEDEXA_CORS_ALLOW_ORIGINS` accepts both forms:

```env
MEDEXA_CORS_ALLOW_ORIGINS=http://localhost:3000,https://app.medexa.com
# or
MEDEXA_CORS_ALLOW_ORIGINS=["http://localhost:3000","https://app.medexa.com"]
```

---

## 3. Docker

```bash
docker build -t medexa-api .
docker run -p 8000:8000 \
  -e MEDEXA_CORS_ALLOW_ORIGINS=http://localhost:3000 \
  medexa-api
```

---

## 4. Render / Railway / Fly (no Docker required)

These platforms detect Python + the `Procfile`:

```
web: python scripts/run_api_server.py
```

- Build command: `pip install .`
- Start command: handled by the `Procfile` (or use the Dockerfile)
- Set `MEDEXA_CORS_ALLOW_ORIGINS` to the deployed frontend URL
- The platform injects `$PORT`, which the start script honors automatically
- Keep instance count = **1** (in-memory store)

Point the frontend at the deployed URL:

```env
NEXT_PUBLIC_MEDEXA_API_URL=https://<your-backend-host>
```

---

## 5. Pre-deploy checklist

- [ ] `pip install .` succeeds with **no AWS packages**
- [ ] `python scripts/run_api_server.py` starts and `/health` returns `{"status":"ok"}`
- [ ] `pytest` passes (`pip install -e ".[dev]"` first)
- [ ] `MEDEXA_CORS_ALLOW_ORIGINS` matches the exact frontend origin
- [ ] Single instance (no autoscaling) while on the in-memory store

---

## 6. Upgrading to AWS later (optional)

When you need durable, multi-instance state:

```bash
pip install -e ".[aws]"          # adds boto3 + mangum
python -m medexa.aws.dynamodb_setup   # create the table
# then set in env:
MEDEXA_USE_DYNAMODB=true
MEDEXA_DYNAMODB_TABLE_NAME=medexa-sessions
MEDEXA_AWS_REGION=us-east-1
```

Lambda deployment uses `medexa.aws.lambda_handler:handler` (Mangum adapter).
No application code changes are required — only the env flag and the `aws` extra.
