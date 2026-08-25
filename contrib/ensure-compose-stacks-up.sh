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
SETTLE_SECONDS=150

log() { logger "ensure-compose-stacks-up: $*"; }

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
