from __future__ import annotations

from mangum import Mangum

from medexa.api.server import app
from medexa.config import settings
from medexa.logging_setup import configure_logging

configure_logging(settings.log_level)

handler = Mangum(app, lifespan="off")
