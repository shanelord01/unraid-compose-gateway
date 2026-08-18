"""Entry point: `python -m unraid_compose_gateway`."""

from __future__ import annotations

import uvicorn

from unraid_compose_gateway.config import load_settings
from unraid_compose_gateway.state import set_settings


def main() -> None:
    settings = load_settings()
    set_settings(settings)
    uvicorn.run("unraid_compose_gateway.app:app", host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
