"""Start the Medexa FastAPI server (no AWS account required).

Local development:
    python scripts/run_api_server.py
    # → http://localhost:8000/docs (Swagger UI)

Deployment (Docker / Render / Railway / VPS) — bind all interfaces and read
the platform-assigned port. These are controlled via env vars:
    MEDEXA_HOST=0.0.0.0   (default)
    MEDEXA_PORT=8000      (default; most platforms inject $PORT)
    MEDEXA_RELOAD=false   (default; set true only for local dev hot-reload)

A bare $PORT (used by Render/Railway/Heroku) is also honored if set.
"""
from __future__ import annotations

import os
import pathlib
import sys

# Allow running without `pip install -e .` by exposing the src layout.
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    import uvicorn

    from medexa.config import settings

    # Platforms like Render/Railway/Heroku inject a bare $PORT.
    port = int(os.environ.get("PORT", settings.port))

    uvicorn.run(
        "medexa.api.server:app",
        host=settings.host,
        port=port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
