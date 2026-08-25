"""Entry point: `python -m unraid_compose_gateway`."""

from __future__ import annotations

import logging

import uvicorn

from unraid_compose_gateway.config import load_settings
from unraid_compose_gateway.state import set_settings


def main() -> None:
    # uvicorn configures its own loggers only; the gateway's startup report
    # goes through the "unraid_compose_gateway" logger at INFO and needs a
    # root handler to be visible in `docker logs`.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
    settings = load_settings()
    set_settings(settings)
    uvicorn.run("unraid_compose_gateway.app:app", host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
