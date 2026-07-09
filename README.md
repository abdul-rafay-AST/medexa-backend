---
title: Medexa Backend
emoji: 🩺
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# Medexa MVP

Real-time therapy session intelligence API (FastAPI, rules-only, no AWS required).

- **Live docs:** `/docs` (Swagger UI)
- **Health:** `/health`
- **Deployment:** see [`DEPLOYMENT.md`](DEPLOYMENT.md)

The block at the top of this file is **Hugging Face Spaces** configuration. It tells
Spaces to build the `Dockerfile` and route traffic to port `8000`. It is ignored by
local development and other hosts.
