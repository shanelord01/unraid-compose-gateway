#!/bin/bash
# Boot-time self-heal for Unraid Compose Manager stacks.
#
# Compose Manager launches every autostart project's `docker compose up -d`
# in parallel at boot with no stagger, no retry, and output discarded, so on
# a busy boot a stack can end up partly running with nothing logged. This
# waits for the boot storm to settle, then asks the unraid-compose-gateway
# API for each autostart project's real container state and calls `up` only
# on projects that report at least one service not running.
#
# Install as a User Scripts script scheduled "At Startup of Array".
#
# Rules that keep this from causing harm:
#   - A status with zero services is treated as unknown and skipped. It is
#     what the gateway returns while a project is still creating, or when
#     Compose cannot list it, and calling `up` on "unknown" is how boot-time
#     recreate storms start.
#   - `up` is only called when the count of not-running services is a
#     positive number.
#   - A 409 from the gateway means its Compose version differs from what
#     created the containers; `up` would recreate them all. Log it, do not
#     force it.

ENV_FILE="/boot/config/plugins/compose.manager/projects/unraid-compose-gateway/.env"
GATEWAY="http://127.0.0.1:8091"
GATEWAY_CONTAINER="unraid-compose-gateway"
SETTLE_SECONDS=150
# Where the gateway reads the host's Compose version from (its
# HOST_COMPOSE_VERSION_FILE, under the PLUGIN_DIR mount of /boot/config/plugins).
HOST_VERSION_FILE="/boot/config/plugins/unraid-compose-gateway/host-compose-version"
HOST_COMPOSE_BIN="/usr/local/bin/docker-compose"

log() { logger "ensure-compose-stacks-up: $*"; }

# Publish the host's Compose version first, before any waiting, so the
# gateway (which starts in parallel with this script) can align itself as
# early as possible. Compose Manager updates replace the binary, so this
# is what carries a new version across.
if [ -x "$HOST_COMPOSE_BIN" ]; then
    host_version=$("$HOST_COMPOSE_BIN" version --short 2>/dev/null | tr -d '[:space:]')
    if echo "$host_version" | grep -Eq '^v?[0-9]+\.[0-9]+\.[0-9]+$'; then
        mkdir -p "$(dirname "$HOST_VERSION_FILE")"
        printf '%s\n' "${host_version#v}" > "$HOST_VERSION_FILE"
        log "host docker-compose version ${host_version#v} written to $HOST_VERSION_FILE"
    else
        log "could not read a version from $HOST_COMPOSE_BIN (got '${host_version}'), not updating $HOST_VERSION_FILE"
    fi
else
    log "$HOST_COMPOSE_BIN not found, not updating $HOST_VERSION_FILE"
fi

log "waiting ${SETTLE_SECONDS}s for boot to settle"
sleep "$SETTLE_SECONDS"

if [ ! -f "$ENV_FILE" ]; then
    log "gateway .env not found at $ENV_FILE, aborting"
    exit 1
fi
TOKEN=$(grep -m1 '^GATEWAY_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
if [ -z "$TOKEN" ]; then
    log "no GATEWAY_TOKEN found, aborting"
    exit 1
fi
AUTH=(-H "Authorization: Bearer $TOKEN")

tries=0
until curl -s -f -m 10 "${AUTH[@]}" "$GATEWAY/healthz" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 12 ]; then
        log "gateway never became reachable after ${tries} tries, aborting"
        exit 1
    fi
    sleep 5
done

# If the gateway is still on a different Compose version than the host,
# give it one restart so it re-syncs now rather than at its next interval.
# The gateway only ever switches to a verified download of the exact host
# version, so this cannot make things worse; and its 409 guard still
# refuses a mismatched `up` if the sync did not succeed.
whoami=$(curl -s -m 30 "${AUTH[@]}" "$GATEWAY/v1/whoami")
gw_version=$(echo "$whoami" | jq -r '.compose_version // empty' 2>/dev/null)
host_file_version=$(cat "$HOST_VERSION_FILE" 2>/dev/null | tr -d '[:space:]')
if [ -n "$gw_version" ] && [ -n "$host_file_version" ] && [ "$gw_version" != "$host_file_version" ]; then
    log "gateway runs Compose ${gw_version}, host has ${host_file_version}; restarting ${GATEWAY_CONTAINER} to re-sync"
    timeout 120 docker restart "$GATEWAY_CONTAINER" >/dev/null 2>&1
    tries=0
    until curl -s -f -m 10 "${AUTH[@]}" "$GATEWAY/healthz" >/dev/null 2>&1; do
        tries=$((tries + 1))
        if [ "$tries" -ge 12 ]; then
            log "gateway did not come back after restart, aborting"
            exit 1
        fi
        sleep 5
    done
    gw_version=$(curl -s -m 30 "${AUTH[@]}" "$GATEWAY/v1/whoami" | jq -r '.compose_version // empty' 2>/dev/null)
    if [ "$gw_version" = "$host_file_version" ]; then
        log "gateway now runs Compose ${gw_version}, matching the host"
    else
        log "gateway still runs Compose ${gw_version:-unknown} (host ${host_file_version}); its up calls will be refused until this resolves"
    fi
fi

projects=$(curl -s -m 30 "${AUTH[@]}" "$GATEWAY/v1/compose/projects")
if ! echo "$projects" | jq -e 'type == "array"' >/dev/null 2>&1; then
    log "could not list projects from the gateway, aborting"
    exit 1
fi

echo "$projects" | jq -r '.[] | select(.exists == true and .autostart == true) | .name' | while read -r project; do
    status=$(curl -s -m 60 "${AUTH[@]}" "$GATEWAY/v1/compose/${project}/status")
    total=$(echo "$status" | jq -r '.services | length' 2>/dev/null)
    not_running=$(echo "$status" | jq -r '[.services[] | select(.state != "running")] | length' 2>/dev/null)

    case "$total" in
        ''|*[!0-9]*|0)
            log "${project}: status unknown (${total:-no} services reported), skipping"
            continue
            ;;
    esac
    case "$not_running" in
        ''|*[!0-9]*)
            log "${project}: could not count services, skipping"
            continue
            ;;
    esac

    if [ "$not_running" -gt 0 ]; then
        log "${project}: ${not_running}/${total} services not running, calling up"
        code=$(curl -s -m 300 -o /tmp/ensure-compose-up.out -w '%{http_code}' -X POST "${AUTH[@]}" "$GATEWAY/v1/compose/${project}/up")
        if [ "$code" = "409" ]; then
            log "${project}: gateway refused up (409, Compose version mismatch), not forcing: $(head -c 300 /tmp/ensure-compose-up.out)"
        else
            log "${project}: up returned ${code}: $(head -c 300 /tmp/ensure-compose-up.out)"
        fi
    else
        log "${project}: OK (${total}/${total} services running)"
    fi
done

log "check complete"
