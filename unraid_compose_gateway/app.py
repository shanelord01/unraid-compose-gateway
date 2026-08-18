"""Route definitions. Each handler is a thin translation from the
domain-level exceptions raised in compose_control.py / logs.py / plugins.py
into HTTP status codes - the actual rules live in those modules, not here.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from unraid_compose_gateway import compose_control, logs, plugins
from unraid_compose_gateway.auth import require_token
from unraid_compose_gateway.config import Settings
from unraid_compose_gateway.models import (
    ComposeActionResult,
    ComposeProject,
    ComposeProjectStatus,
    ContainerLogs,
    PluginUpdatesResponse,
    WhoAmI,
)
from unraid_compose_gateway.state import get_settings

app = FastAPI(
    title="unraid-compose-gateway",
    version="0.1.0",
    description=(
        "A scoped sidecar for Docker Compose control, container logs, and "
        "Unraid plugin update detection - without handing a client docker.sock."
    ),
)


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/v1/whoami", response_model=WhoAmI, tags=["meta"], dependencies=[Depends(require_token)])
def whoami(settings: Settings = Depends(get_settings)) -> WhoAmI:
    return WhoAmI(
        allowed_projects=settings.allowed_projects,
        self_exclude_projects=settings.self_exclude_projects,
        plugin_updates_enabled=settings.plugin_dir is not None,
    )


@app.get(
    "/v1/compose/projects",
    response_model=list[ComposeProject],
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def list_compose_projects(settings: Settings = Depends(get_settings)) -> list[ComposeProject]:
    return compose_control.list_projects(settings)


@app.get(
    "/v1/compose/{project}/status",
    response_model=ComposeProjectStatus,
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def compose_status(project: str, settings: Settings = Depends(get_settings)) -> ComposeProjectStatus:
    try:
        services = compose_control.get_status(project, settings)
    except compose_control.ProjectNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except compose_control.ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except compose_control.ComposeCommandFailed as exc:
        raise HTTPException(status_code=502, detail=f"{exc}: {exc.output}"[:2000]) from exc
    return ComposeProjectStatus(project=project, services=services)


def _run_action_route(project: str, action: str, settings: Settings) -> ComposeActionResult:
    try:
        return compose_control.run_action(project, action, settings)
    except compose_control.ProjectNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except compose_control.ProjectSelfExcluded as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except compose_control.ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except compose_control.ComposeCommandFailed as exc:
        raise HTTPException(status_code=502, detail=f"{exc}: {exc.output}"[:2000]) from exc


@app.post(
    "/v1/compose/{project}/restart",
    response_model=ComposeActionResult,
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def compose_restart(project: str, settings: Settings = Depends(get_settings)) -> ComposeActionResult:
    return _run_action_route(project, "restart", settings)


@app.post(
    "/v1/compose/{project}/up",
    response_model=ComposeActionResult,
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def compose_up(project: str, settings: Settings = Depends(get_settings)) -> ComposeActionResult:
    return _run_action_route(project, "up", settings)


@app.post(
    "/v1/compose/{project}/down",
    response_model=ComposeActionResult,
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def compose_down(project: str, settings: Settings = Depends(get_settings)) -> ComposeActionResult:
    return _run_action_route(project, "down", settings)


@app.post(
    "/v1/compose/{project}/pull",
    response_model=ComposeActionResult,
    tags=["compose"],
    dependencies=[Depends(require_token)],
)
def compose_pull(project: str, settings: Settings = Depends(get_settings)) -> ComposeActionResult:
    return _run_action_route(project, "pull", settings)


@app.get(
    "/v1/containers/{name}/logs",
    response_model=ContainerLogs,
    tags=["logs"],
    dependencies=[Depends(require_token)],
)
def container_logs(
    name: str,
    tail: int | None = Query(default=None, ge=1),
    since: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> ContainerLogs:
    effective_tail = tail if tail is not None else settings.log_tail_default
    try:
        lines = logs.get_logs(name, effective_tail, since, settings)
    except logs.ContainerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContainerLogs(container=name, tail=effective_tail, lines=lines)


@app.get(
    "/v1/plugins/updates",
    response_model=PluginUpdatesResponse,
    tags=["plugins"],
    dependencies=[Depends(require_token)],
)
async def plugin_updates(
    force: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
) -> PluginUpdatesResponse:
    try:
        results, cache_age = await plugins.check_updates(settings, force=force)
    except plugins.PluginUpdatesDisabled as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return PluginUpdatesResponse(plugins=results, cache_age_seconds=cache_age)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:  # noqa: ANN001
    # Anything reaching here is a bug, not an expected failure mode - the
    # expected ones are already mapped to specific status codes above. Log
    # the real exception server-side but never let its message reach the
    # caller, since it could contain paths or command output.
    import logging

    logging.getLogger("unraid_compose_gateway").exception("unhandled error in %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
