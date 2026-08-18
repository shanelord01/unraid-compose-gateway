# unraid-compose-gateway

A small HTTP sidecar that gives an automation client - an AI agent, a script, anything - scoped control over specific Docker Compose projects and read access to container logs, without ever handing it `docker.sock` directly. It also detects available updates for Unraid plugins, a check Unraid's own API cannot do.

## The problem this solves

Docker's socket is all-or-nothing. Mount it into a container and that container can control every other container on the host, including itself - there is no built-in way to say "you can restart these three services but never touch your own container." Generic socket proxies help at the API-verb level (allow `GET /containers`, deny `POST /containers/*/stop`) but none of them filter by *which* container is the target, so they cannot express "control anything except this one" either.

unraid-compose-gateway sits in front of the socket instead of exposing it. It never forwards raw Docker API calls - it has a small, fixed set of endpoints, and every mutating one checks the target project against an exclude list before it does anything. The exclusion is enforced here, server-side, not left to the calling client to police itself.

## What it does

- Start, stop, restart, and pull images for named Docker Compose projects - scoped to an explicit allowlist, with an explicit exclude list that start/stop/restart can never touch
- Report status for a compose project's services
- Tail logs for any container by name (read-only, not restricted by the allowlist - reading output isn't a control operation)
- Detect available updates for installed Unraid plugins by replicating exactly what Unraid's own "Check for Updates" button does

What it deliberately does not do: install or apply plugin updates, run arbitrary Docker API calls, or manage anything outside the projects you've explicitly allowed.

## Security model

- **Bearer token auth.** One static token per instance, checked with a constant-time comparison. There is no user system - if you need different permission sets for different callers, run separate instances with different `ALLOWED_PROJECTS`.
- **Two-list authorization for compose control.** `ALLOWED_PROJECTS` is what this instance will act on at all; `SELF_EXCLUDE_PROJECTS` is a subset of that list which the state-changing endpoints (`restart`, `up`, `down`) always refuse, regardless of how the request is phrased. Both checks happen before any `docker compose` command runs. `pull` is exempt - it only downloads images into local storage and cannot affect a running container until a later `up` recreates it, and `up` stays gated as normal.
- **Read endpoints are not gated by the exclude list.** Listing status or tailing logs for an excluded project is fine - the risk is control, not visibility.
- **No shell access, no arbitrary command execution.** The only commands this service ever runs are `docker compose -f <file> [-f <override file>] {ps|up -d|down|restart|pull}`, run with the project directory as the working directory, with the project name resolved against your own allowlist first, never taken as a raw string handed to a shell. Deliberately no `-p`: Compose infers the project name from the file's own `name:` field (falling back to the directory name), the same way it would if you ran it by hand from inside that directory - forcing `-p` to whatever the allowlist entry happens to be called would create a second, mismatched project if that name differs from the directory or file, which is routine on Unraid (a Compose Manager project directory named `Hermes` commonly wraps a file declaring `name: hermes`).
- **What this does not protect against:** a leaked token grants everything `ALLOWED_PROJECTS` permits, this container still needs `docker.sock`, and anyone who can reach it can act on the whole allowlist. Put it on a private network, not the public internet, and scope `ALLOWED_PROJECTS` narrowly.

## Quick start

```bash
cp .env.example .env
# edit .env: set GATEWAY_TOKEN, ALLOWED_PROJECTS, SELF_EXCLUDE_PROJECTS
docker compose -f docker-compose.example.yml up -d
```

See [`docker-compose.example.yml`](docker-compose.example.yml) for a complete example, including how a calling agent container reaches it.

```bash
curl -H "Authorization: Bearer $GATEWAY_TOKEN" http://localhost:8080/v1/whoami
```

## API reference

Interactive OpenAPI docs are served at `/docs` once the container is running. Summary:

| Method | Path | Purpose | Blocked by SELF_EXCLUDE_PROJECTS? |
|---|---|---|---|
| GET | `/healthz` | Liveness, no auth required | - |
| GET | `/v1/whoami` | This instance's allowlist, exclude list, and whether plugin checks are enabled | no |
| GET | `/v1/compose/projects` | List allowed projects, whether each has a compose file on disk, and its exclusion state | no |
| GET | `/v1/compose/{project}/status` | Per-service state for one project | no |
| POST | `/v1/compose/{project}/restart` | `docker compose restart` | **yes** |
| POST | `/v1/compose/{project}/up` | `docker compose up -d` | **yes** |
| POST | `/v1/compose/{project}/down` | `docker compose down` | **yes** |
| POST | `/v1/compose/{project}/pull` | `docker compose pull` | no - see below |
| GET | `/v1/containers/{name}/logs` | Tail logs for any container (`?tail=`, `?since=`) | no |
| GET | `/v1/plugins/updates` | Version-check installed Unraid plugins (`?force=true` to bypass the cache) | n/a |

All `/v1/*` routes require `Authorization: Bearer <token>`.

## Configuration

All configuration is environment variables - see [`.env.example`](.env.example) for the full list with defaults. The two that matter most:

| Variable | Required | Purpose |
|---|---|---|
| `GATEWAY_TOKEN` | yes | Bearer token every request must present |
| `ALLOWED_PROJECTS` | for compose control | Comma-separated compose project names this instance will act on |
| `SELF_EXCLUDE_PROJECTS` | recommended | Subset of the above that mutating calls always refuse |

## Hermes plugin

[`hermes-plugin/`](hermes-plugin/) is a [Hermes Agent](https://hermes-agent.nousresearch.com/) plugin that talks to a running instance of this gateway over HTTP. It lives in this repo rather than a separate one because the two are versioned together - a change to the gateway's API and the plugin that calls it should land in the same commit.

Because it is a subdirectory rather than the repo root, Hermes's one-line installer (`hermes plugins install owner/repo`, which expects `plugin.yaml` at the repo root) does not apply here. Install it manually instead:

```bash
git clone https://github.com/shanelord01/unraid-compose-gateway.git
cp -r unraid-compose-gateway/hermes-plugin ~/.hermes/plugins/unraid_compose_gateway
# that is /opt/data/plugins/unraid_compose_gateway/ inside the Hermes Docker image
```

It also adds a **Compose Gateway** tab to the Hermes dashboard - `GATEWAY_URL`, `GATEWAY_TOKEN`, `GATEWAY_ALLOW_WRITES`, and `GATEWAY_TIMEOUT_SECONDS` can all be set there instead of as environment variables, with a "Test connection" button that calls the gateway's own `/v1/whoami` to prove the URL and token actually work. Either way, a Hermes gateway restart is required for a `GATEWAY_ALLOW_WRITES` change to take effect, since tool registration happens once at startup.

Set its environment variables (or the dashboard fields) and restart the Hermes gateway:

| Variable | Required | Purpose |
|---|---|---|
| `GATEWAY_URL` | yes | Base URL of the running gateway, e.g. `http://unraid-compose-gateway:8080` |
| `GATEWAY_TOKEN` | yes | Must match the gateway's own `GATEWAY_TOKEN` |
| `GATEWAY_ALLOW_WRITES` | no, default `false` | Registers the mutating tools (restart/up/down/pull). Read-only tools register regardless. This is a client-side intent switch only - the gateway's own `ALLOWED_PROJECTS` and `SELF_EXCLUDE_PROJECTS` are enforced either way |
| `GATEWAY_TIMEOUT_SECONDS` | no, default `30` | HTTP timeout for calls to the gateway |

| Tool | Gated by GATEWAY_ALLOW_WRITES? | What it does |
|---|---|---|
| `unraid_compose_gateway_whoami` | no | The gateway's allowed projects, exclude list, and whether plugin-update checking is enabled |
| `unraid_compose_gateway_projects` | no | List projects the gateway can act on |
| `unraid_compose_gateway_status` | no | Per-service status for one project |
| `unraid_compose_gateway_logs` | no | Tail logs for any container by name |
| `unraid_compose_gateway_plugin_updates` | no | Check installed Unraid plugins for available updates |
| `unraid_compose_gateway_restart` | yes | Restart a project's services |
| `unraid_compose_gateway_up` | yes | `docker compose up -d` |
| `unraid_compose_gateway_down` | yes | `docker compose down` |
| `unraid_compose_gateway_pull` | yes | Pull the latest images for a project's services |

This plugin only detects Unraid plugin updates, it does not apply them - applying one means running that plugin's install script as root on the host, a different trust level than anything else this gateway does. If you also run [hermes-unraid](https://github.com/shanelord01/hermes-unraid), its `unraid_install_plugin` tool is what actually applies an update this plugin found: `unraid_install_plugin` installs or updates a plugin from its `.plg` URL, which is exactly what `unraid_compose_gateway_plugin_updates` returns for anything with `update_available: true`. The two plugins are complementary - one detects, the other applies, and applying stays a distinct, deliberate step either way.

## Plugin update detection

Unraid's own "Check for Updates" button does nothing more sophisticated than this: every installed plugin has a local descriptor at `/boot/config/plugins/<name>.plg`, an XML file whose `<!DOCTYPE>` defines a `version` entity and a `pluginURL` entity pointing at the canonical copy of that same file (typically on GitHub). Checking for an update means fetching `pluginURL` and comparing its `version` entity against the local one - no registry, no authentication, no semantic version comparison, just a string inequality check.

Unraid's GraphQL API cannot do this check itself: `installedUnraidPlugins` returns bare plugin names with no version or update information at all. `GET /v1/plugins/updates` fills that gap by replicating the same file-based check the web UI uses, read-only, against a directory you mount in yourself.

To enable it, bind-mount your Unraid `/boot/config/plugins` directory read-only into the container and set `PLUGIN_DIR` to that mount point. Leave it unset to disable the feature entirely - the endpoint then returns `501 Not Implemented` rather than an error.

This endpoint only detects updates. Applying one means running that plugin's install script as root on the host - a fundamentally different trust level than anything else in this service, and deliberately out of scope here. If you want an agent to be able to apply an update it discovered through this endpoint, pair this with something that already has that permission on your Unraid API key, and treat that step as a separate, explicitly-confirmed action rather than something chained automatically off this endpoint's result.

## Limitations

- **Compose file discovery** checks for `docker-compose.yml`, `docker-compose.yaml`, `compose.yml`, and `compose.yaml`, in that order, in the project's directory. Projects using `-f` chains, override files, or `.env` files outside the project directory are not specially handled - `docker compose` reads what's normally alongside the primary file, but nothing beyond that.
- **No rollback.** `up`, `down`, `restart`, and `pull` do exactly what those `docker compose` subcommands do. If a restart leaves a service unhealthy, this service reports that as a failed check, not an automatic revert. `pull` never recreates a container by itself - follow it with `up` to actually run the pulled image.
- **Version comparison is a plain string inequality**, matching what Unraid itself does. It cannot tell "older" from "newer" - only "different." A plugin with a non-standard version scheme or a `.plg` that doesn't follow the conventional entity layout is reported with an explicit error rather than a guess.
- **Requires the Docker CLI and compose plugin inside the sidecar's own image** (already included in the provided `Dockerfile`), since Compose v2 has no stable Python library, only a CLI plugin.

## Requirements

- Docker with the Compose plugin (v2) on the host
- Access to `/var/run/docker.sock`
- Python 3.12+ if running outside the provided container image

## License

MIT
