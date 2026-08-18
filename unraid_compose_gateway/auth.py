"""Bearer token authentication.

One static token, one scope: it can do everything ALLOWED_PROJECTS and the
plugin-update endpoints permit, nothing more, and nothing less. There is no
per-caller identity because there is only ever one intended caller - the
agent this sidecar was deployed for. If you need more than one caller with
different permissions, run more than one instance with different
ALLOWED_PROJECTS rather than adding a user table here.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status

from unraid_compose_gateway.config import Settings
from unraid_compose_gateway.state import get_settings


def require_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(presented, settings.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
