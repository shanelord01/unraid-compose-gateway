"""Entry point: `python -m compose_sentry`."""

from __future__ import annotations

import uvicorn

from compose_sentry.config import load_settings
from compose_sentry.state import set_settings


def main() -> None:
    settings = load_settings()
    set_settings(settings)
    uvicorn.run("compose_sentry.app:app", host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
